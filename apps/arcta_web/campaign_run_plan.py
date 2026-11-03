from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from arcta.profiles import require_profile_config
from apps.arcta_web.analysis_settings import read_settings, validate_settings
from cta_core.campaign_run import (
    ArctaCampaignRunPlan,
    ArctaCampaignRunSource,
)

from apps.arcta_web.session_config import load_session_config
from apps.arcta_web.session_diag_review import (
    assess_session_diag_review,
    load_session_diag_review,
)
from apps.arcta_web.session_mapping import load_session_mapping
from web_common.sessions import is_trial_source


class CampaignRunPrerequisiteError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = str(code)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_sha256(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _require_profile(profile: str) -> str:
    normalized = str(profile or "").strip().upper()
    try:
        require_profile_config(normalized)
    except ValueError as exc:
        raise CampaignRunPrerequisiteError(
            str(exc), code="RUN_PROFILE_INVALID"
        ) from exc
    return normalized


def build_campaign_run_plan(session, *, profile: str, analysis_settings=None) -> ArctaCampaignRunPlan:
    normalized_profile = _require_profile(profile)

    config_state = load_session_config(session)
    if config_state is None:
        raise CampaignRunPrerequisiteError(
            "La CONFIG de campagne est absente.", code="CONFIG_MISSING"
        )
    if not config_state.validated:
        raise CampaignRunPrerequisiteError(
            "La CONFIG de campagne doit être validée.",
            code="CONFIG_NOT_VALIDATED",
        )
    if not config_state.config.validation_summary()["valid"]:
        raise CampaignRunPrerequisiteError(
            "La CONFIG validée contient des champs obligatoires invalides.",
            code="CONFIG_INVALID",
        )

    mapping_state = load_session_mapping(session)
    if mapping_state is None:
        raise CampaignRunPrerequisiteError(
            "Le mapping de campagne est absent.", code="MAPPING_MISSING"
        )
    if not mapping_state.validated:
        raise CampaignRunPrerequisiteError(
            "Le mapping de campagne doit être validé.",
            code="MAPPING_NOT_VALIDATED",
        )

    review_state = load_session_diag_review(session)
    if review_state is None:
        raise CampaignRunPrerequisiteError(
            "La revue DIAG est absente.", code="DIAG_REVIEW_MISSING"
        )
    assessment = assess_session_diag_review(session, review_state)
    if assessment["stale"]:
        raise CampaignRunPrerequisiteError(
            "La revue DIAG est obsolète.", code="DIAG_REVIEW_STALE"
        )
    if not review_state.review.validated:
        raise CampaignRunPrerequisiteError(
            "La revue DIAG doit être validée.",
            code="DIAG_REVIEW_NOT_VALIDATED",
        )

    accepted = set(review_state.review.accepted_source_ids)
    if not accepted:
        raise CampaignRunPrerequisiteError(
            "Aucun essai n'est accepté pour le pipeline ARCTA.",
            code="NO_ACCEPTED_TRIALS",
        )
    decisions = {
        trial.source_id: trial.decision
        for trial in review_state.review.trials
    }
    session_sources = getattr(session, "sources", {})
    if not isinstance(session_sources, dict):
        session_sources = {
            source.source_id: source
            for source in session_sources
            if is_trial_source(source)
        }
    else:
        session_sources = {
            source_id: source
            for source_id, source in session_sources.items()
            if is_trial_source(source)
        }
    if set(decisions) != set(session_sources):
        raise CampaignRunPrerequisiteError(
            "Les sources de la revue ne correspondent pas à la session.",
            code="RUN_SOURCE_SET_MISMATCH",
        )

    sources = tuple(
        ArctaCampaignRunSource(
            source_id=source_id,
            source_name=source.original_name,
            stored_name=source.stored_name,
            size_bytes=source.size_bytes,
            uploaded_at=source.uploaded_at,
            accepted=source_id in accepted,
        )
        for source_id, source in session_sources.items()
    )

    try:
        settings = (read_settings(session)["values"] if analysis_settings is None
                    else validate_settings(dict(analysis_settings)))
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        raise CampaignRunPrerequisiteError(
            "Paramètres statistiques invalides : " + str(exc), code="RUN_SETTINGS_INVALID"
        ) from exc

    # 64H9 : l'ancien choix est conservé en lecture des archives seulement.
    settings["subtract_selflock"] = False
    if require_profile_config(normalized_profile).get("do_compute"):
        from .run_mechanics import check_autofrein
        try:
            check_autofrein(review_state, accepted)
        except ValueError as exc:
            raise CampaignRunPrerequisiteError(str(exc), code="SELFLOCK_NOT_USABLE") from exc
    config_payload = config_state.to_dict()
    from .run_mechanics import geometry_snapshot
    config_payload["run_geometry"] = geometry_snapshot(session)
    mapping_payload = mapping_state.to_dict()
    review_payload = review_state.to_dict()
    config_fingerprint = _canonical_sha256(config_payload)
    mapping_fingerprint = _canonical_sha256(mapping_payload)
    review_fingerprint = _canonical_sha256(review_payload)
    diag_context_signature = review_state.context_signature
    from arcta.selflock_policy import POLICY
    context_signature = _canonical_sha256({
        'selflock_policy': POLICY,
        "mechanical_contract": "DUAL_SELFLOCK_64H9",
        "profile": normalized_profile,
        "analysis_settings": settings,
        "config_fingerprint": config_fingerprint,
        "mapping_fingerprint": mapping_fingerprint,
        "review_fingerprint": review_fingerprint,
        "diag_context_signature": diag_context_signature,
        "sources": [item.to_dict() for item in sources],
    })

    return ArctaCampaignRunPlan(
        session_id=str(session.session_id),
        campaign_id=config_state.config.campaign_id,
        profile=normalized_profile,
        context_signature=context_signature,
        config_fingerprint=config_fingerprint,
        mapping_fingerprint=mapping_fingerprint,
        review_fingerprint=review_fingerprint,
        diag_context_signature=diag_context_signature,
        sources=sources,
        created_at=_utc_now_iso(),
        analysis_settings=tuple(settings.items()),
    )
