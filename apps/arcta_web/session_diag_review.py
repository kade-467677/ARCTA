from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, replace, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from apps.arcta_web.diag_visual_data import pack_curves, pack_iso_boxplots

from cta_core.diag_review import (
    ArctaDiagReview,
    DIAG_REVIEW_STATUS_DRAFT,
    DIAG_REVIEW_STATUS_VALIDATED,
    arcta_diag_review_from_dict,
)

from apps.arcta_web.diag_execution_service import (
    WebDiagExecutionResult,
)
from apps.arcta_web.session_mapping import (
    load_session_mapping,
)
from web_common.sessions import is_trial_source


SESSION_DIAG_REVIEW_SCHEMA_VERSION = "1.0"
DIAG_CAMPAIGN_CONTEXT_SCHEMA_VERSION = "1.0"
SESSION_DIAG_REVIEW_FILENAME = "arcta_diag_review.json"
_WINDOWS_REPLACE_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.4)


class SessionDiagReviewError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = str(code)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_file_with_retry(
    source: Path,
    destination: Path,
) -> None:
    """Replace atomically, tolerating short-lived Windows file locks."""
    for attempt in range(
        len(_WINDOWS_REPLACE_RETRY_DELAYS) + 1
    ):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt >= len(
                _WINDOWS_REPLACE_RETRY_DELAYS
            ):
                raise

            time.sleep(
                _WINDOWS_REPLACE_RETRY_DELAYS[attempt]
            )


def _canonical_sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(serialized).hexdigest()


def _session_sources(session) -> tuple:
    raw_sources = getattr(session, "sources", {})

    if isinstance(raw_sources, dict):
        return tuple(
            source
            for source in raw_sources.values()
            if is_trial_source(source)
        )

    return tuple(
        source
        for source in raw_sources
        if is_trial_source(source)
    )


def _source_context(source) -> dict[str, object]:
    path = Path(getattr(source, "storage_path", ""))
    exists = path.is_file()
    stat = path.stat() if exists else None

    return {
        "source_id": str(getattr(source, "source_id", "")),
        "original_name": str(getattr(source, "original_name", "")),
        "stored_name": str(getattr(source, "stored_name", "")),
        "size_bytes": int(getattr(source, "size_bytes", 0)),
        "uploaded_at": str(getattr(source, "uploaded_at", "")),
        "file_exists": exists,
        "actual_size_bytes": (
            int(stat.st_size)
            if stat is not None
            else None
        ),
        "modified_time_ns": (
            int(stat.st_mtime_ns)
            if stat is not None
            else None
        ),
    }


def build_diag_campaign_context(
    session,
) -> dict[str, object]:
    stored_mapping = load_session_mapping(session)

    mapping_payload = (
        {
            "status": stored_mapping.status,
            "mapping": stored_mapping.mapping.to_dict(),
        }
        if stored_mapping is not None
        else None
    )

    sources = sorted(
        (
            _source_context(source)
            for source in _session_sources(session)
        ),
        key=lambda item: str(item["source_id"]),
    )

    mapping_fingerprint = _canonical_sha256(mapping_payload)
    sources_fingerprint = _canonical_sha256(sources)

    signature_payload = {
        "schema_version": DIAG_CAMPAIGN_CONTEXT_SCHEMA_VERSION,
        "mapping_fingerprint": mapping_fingerprint,
        "sources_fingerprint": sources_fingerprint,
    }

    return {
        "schema_version": DIAG_CAMPAIGN_CONTEXT_SCHEMA_VERSION,
        "signature": _canonical_sha256(signature_payload),
        "mapping_fingerprint": mapping_fingerprint,
        "sources_fingerprint": sources_fingerprint,
        "source_count": len(sources),
        "sources": sources,
    }


def _dataframe_records(
    dataframe: pd.DataFrame,
) -> tuple[dict[str, object], ...]:
    if dataframe is None or dataframe.empty:
        return ()

    rows = json.loads(
        dataframe.to_json(
            orient="records",
            date_format="iso",
            force_ascii=False,
        )
    )

    return tuple(dict(row) for row in rows)


@dataclass(frozen=True)
class ArctaSessionDiagReview:
    review: ArctaDiagReview
    review_summary: tuple[dict[str, object], ...]
    source_preparation: tuple[dict[str, object], ...]
    source_errors: tuple[dict[str, object], ...]
    compatibility: dict[str, object]
    campaign_context: dict[str, object]
    created_at: str
    updated_at: str
    schema_version: str = SESSION_DIAG_REVIEW_SCHEMA_VERSION
    visual_curves: tuple[dict[str, object], ...] = ()
    diag_boxplots: tuple[dict[str, object], ...] = ()
    population: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SESSION_DIAG_REVIEW_SCHEMA_VERSION:
            raise ValueError(
                "Version de schéma de session DIAG non supportée : "
                f"{self.schema_version!r}"
            )

        signature = str(
            self.campaign_context.get("signature", "")
        ).strip()

        if not signature:
            raise ValueError(
                "La signature du contexte de campagne DIAG est absente."
            )

        if not str(self.created_at).strip():
            raise ValueError("created_at est obligatoire.")

        if not str(self.updated_at).strip():
            raise ValueError("updated_at est obligatoire.")

    @property
    def context_signature(self) -> str:
        return str(self.campaign_context["signature"])

    def to_dict(self) -> dict[str, object]:
        from apps.arcta_web.diag_population import review_payload
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "campaign_context": dict(self.campaign_context),
            "compatibility": dict(self.compatibility),
            "source_preparation": [
                dict(item)
                for item in self.source_preparation
            ],
            "source_errors": [
                dict(item)
                for item in self.source_errors
            ],
            "review_summary": [
                dict(item)
                for item in self.review_summary
            ],
            "visual_curves": list(self.visual_curves),
            "diag_boxplots": list(self.diag_boxplots),
            "review": review_payload(self),
            "population": self.population,
        }

    def with_review(
        self,
        review: ArctaDiagReview,
    ) -> "ArctaSessionDiagReview":
        return replace(
            self,
            review=review,
            updated_at=_utc_now_iso(),
        )


def session_diag_review_path(session) -> Path:
    return Path(session.storage_dir) / SESSION_DIAG_REVIEW_FILENAME


def session_diag_review_from_dict(
    payload: Mapping[str, Any],
) -> ArctaSessionDiagReview:
    if not isinstance(payload, Mapping):
        raise TypeError(
            "La revue DIAG de session doit être un objet JSON."
        )

    def list_of_dicts(field_name: str) -> tuple[dict[str, object], ...]:
        value = payload.get(field_name, [])

        if not isinstance(value, list) or not all(
            isinstance(item, Mapping)
            for item in value
        ):
            raise ValueError(
                f"Le champ {field_name!r} de la revue DIAG est invalide."
            )

        return tuple(dict(item) for item in value)

    raw_review = payload.get("review")
    raw_context = payload.get("campaign_context")
    raw_compatibility = payload.get("compatibility", {})

    if not isinstance(raw_review, Mapping):
        raise ValueError("Le champ 'review' est absent ou invalide.")

    if not isinstance(raw_context, Mapping):
        raise ValueError(
            "Le champ 'campaign_context' est absent ou invalide."
        )

    if not isinstance(raw_compatibility, Mapping):
        raise ValueError("Le champ 'compatibility' est invalide.")

    return ArctaSessionDiagReview(
        visual_curves=list_of_dicts("visual_curves"),
        diag_boxplots=list_of_dicts("diag_boxplots"),
        population=dict(payload.get("population") or {}),
        review=arcta_diag_review_from_dict(raw_review),
        review_summary=list_of_dicts("review_summary"),
        source_preparation=list_of_dicts("source_preparation"),
        source_errors=list_of_dicts("source_errors"),
        compatibility=dict(raw_compatibility),
        campaign_context=dict(raw_context),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        schema_version=str(payload.get("schema_version", "")),
    )


def load_session_diag_review(
    session,
) -> ArctaSessionDiagReview | None:
    path = session_diag_review_path(session)

    if not path.is_file():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    return session_diag_review_from_dict(payload)


def save_session_diag_review(
    session,
    state: ArctaSessionDiagReview,
) -> ArctaSessionDiagReview:
    from apps.arcta_web.diag_population import recalculate
    state = recalculate(state)
    path = session_diag_review_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")

    try:
        temporary.write_text(
            json.dumps(
                state.to_dict(),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        _replace_file_with_retry(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return state


def create_session_diag_review(
    session,
    execution: WebDiagExecutionResult,
    *,
    campaign_context: Mapping[str, object] | None = None,
) -> ArctaSessionDiagReview:
    timestamp = _utc_now_iso()
    state = ArctaSessionDiagReview(
        visual_curves=pack_curves(execution.trial_results),
        diag_boxplots=pack_iso_boxplots(execution.diag),
        review=execution.review,
        review_summary=_dataframe_records(execution.review_summary),
        source_preparation=tuple(
            dict(item)
            for item in execution.source_preparation
        ),
        source_errors=tuple(
            dict(item)
            for item in execution.source_errors
        ),
        compatibility=dict(execution.compatibility),
        campaign_context=dict(
            campaign_context
            if campaign_context is not None
            else build_diag_campaign_context(session)
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )

    return save_session_diag_review(session, state)


def assess_session_diag_review(
    session,
    state: ArctaSessionDiagReview,
) -> dict[str, object]:
    current_context = build_diag_campaign_context(session)
    stored_context = state.campaign_context
    reasons: list[str] = []

    if (
        stored_context.get("mapping_fingerprint")
        != current_context.get("mapping_fingerprint")
    ):
        reasons.append("MAPPING_CHANGED")

    if (
        stored_context.get("sources_fingerprint")
        != current_context.get("sources_fingerprint")
    ):
        reasons.append("SOURCES_CHANGED")

    if (
        stored_context.get("schema_version")
        != current_context.get("schema_version")
    ):
        reasons.append("CONTEXT_SCHEMA_CHANGED")

    if (
        stored_context.get("signature")
        != current_context.get("signature")
        and not reasons
    ):
        reasons.append("CONTEXT_SIGNATURE_CHANGED")

    return {
        "stale": bool(reasons),
        "reasons": reasons,
        "stored_signature": state.context_signature,
        "current_signature": current_context["signature"],
    }


def _require_current_review(
    session,
    state: ArctaSessionDiagReview,
) -> None:
    assessment = assess_session_diag_review(session, state)

    if assessment["stale"]:
        raise SessionDiagReviewError(
            "La revue DIAG est obsolète : une nouvelle exécution "
            "est obligatoire.",
            code="DIAG_REVIEW_STALE",
        )


def update_session_diag_trial_decision(
    session,
    state: ArctaSessionDiagReview,
    *,
    source_id: str,
    decision: str,
    comment: str = "",
) -> ArctaSessionDiagReview:
    _require_current_review(session, state)

    if state.review.validated:
        raise SessionDiagReviewError(
            "Une revue DIAG validée ne peut plus être modifiée.",
            code="DIAG_REVIEW_ALREADY_VALIDATED",
        )

    normalized_source_id = str(source_id).strip()
    updated_trials = []
    found = False

    for trial in state.review.trials:
        if trial.source_id != normalized_source_id:
            updated_trials.append(trial)
            continue

        found = True
        updated_trial = trial.with_decision(
            decision,
            comment=comment,
        )

        if updated_trial.decided:
            updated_trial.validate()

        updated_trials.append(updated_trial)

    if not found:
        raise SessionDiagReviewError(
            f"Source absente de la revue DIAG : {normalized_source_id}",
            code="DIAG_REVIEW_SOURCE_NOT_FOUND",
        )

    review = ArctaDiagReview(
        trials=tuple(updated_trials),
        status=DIAG_REVIEW_STATUS_DRAFT,
        updated_at=_utc_now_iso(),
        schema_version=state.review.schema_version,
    )

    return save_session_diag_review(
        session,
        state.with_review(review),
    )


def validate_session_diag_review(
    session,
    state: ArctaSessionDiagReview,
    *, selflock_token: str | None = None,
) -> ArctaSessionDiagReview:
    _require_current_review(session, state)

    if state.review.validated:
        return state

    review = state.review.with_status(
        DIAG_REVIEW_STATUS_VALIDATED
    )

    from .diag_selflock_config import apply_proposal
    apply_proposal(session, state, selflock_token)

    return save_session_diag_review(
        session,
        state.with_review(review),
    )
