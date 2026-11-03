from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Mapping, Optional


ARCTA_CAMPAIGN_RUN_SCHEMA_VERSION = "1.0"

RUN_STATUS_PENDING = "PENDING"
RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_SUCCEEDED = "SUCCEEDED"
RUN_STATUS_FAILED = "FAILED"

RUN_STATUSES = frozenset({
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_SUCCEEDED,
    RUN_STATUS_FAILED,
})

TERMINAL_RUN_STATUSES = frozenset({
    RUN_STATUS_SUCCEEDED,
    RUN_STATUS_FAILED,
})


def _required_text(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} est obligatoire.")
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ArctaCampaignRunSource:
    source_id: str
    source_name: str
    stored_name: str
    size_bytes: int
    uploaded_at: str
    accepted: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required_text(
            self.source_id, "source_id"
        ))
        object.__setattr__(self, "source_name", _required_text(
            self.source_name, "source_name"
        ))
        object.__setattr__(self, "stored_name", _required_text(
            self.stored_name, "stored_name"
        ))
        object.__setattr__(self, "uploaded_at", _required_text(
            self.uploaded_at, "uploaded_at"
        ))
        if int(self.size_bytes) < 0:
            raise ValueError("size_bytes ne peut pas être négatif.")
        object.__setattr__(self, "size_bytes", int(self.size_bytes))
        object.__setattr__(self, "accepted", bool(self.accepted))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "stored_name": self.stored_name,
            "size_bytes": self.size_bytes,
            "uploaded_at": self.uploaded_at,
            "accepted": self.accepted,
        }


@dataclass(frozen=True)
class ArctaCampaignRunPlan:
    session_id: str
    campaign_id: str
    profile: str
    context_signature: str
    config_fingerprint: str
    mapping_fingerprint: str
    review_fingerprint: str
    diag_context_signature: str
    sources: tuple[ArctaCampaignRunSource, ...]
    created_at: str
    schema_version: str = ARCTA_CAMPAIGN_RUN_SCHEMA_VERSION
    analysis_settings: tuple[tuple[str, float | int], ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != ARCTA_CAMPAIGN_RUN_SCHEMA_VERSION:
            raise ValueError(
                "Version de schéma de run ARCTA non supportée : "
                f"{self.schema_version!r}"
            )
        for name in (
            "session_id", "campaign_id", "profile", "context_signature",
            "config_fingerprint", "mapping_fingerprint",
            "review_fingerprint", "diag_context_signature", "created_at",
        ):
            object.__setattr__(self, name, _required_text(
                getattr(self, name), name
            ))
        sources = tuple(self.sources)
        if not sources:
            raise ValueError("Le plan ARCTA doit contenir au moins une source.")
        if not all(isinstance(item, ArctaCampaignRunSource) for item in sources):
            raise TypeError("sources doit contenir des ArctaCampaignRunSource.")
        source_ids = [item.source_id for item in sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Chaque source ne peut apparaître qu'une fois.")
        if not any(item.accepted for item in sources):
            raise ValueError("Au moins un essai doit être accepté pour le run.")
        object.__setattr__(self, "sources", sources)
        settings = tuple(tuple(pair) for pair in self.analysis_settings)
        if any(len(pair) != 2 for pair in settings):
            raise ValueError("Instantané de paramètres invalide.")
        if len({pair[0] for pair in settings}) != len(settings):
            raise ValueError("Paramètres dupliqués dans le plan.")
        for key, value in settings:
            if key == "subtract_selflock":
                if type(value) is not bool: raise ValueError("Choix autofrein non booléen")
                continue
            if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Valeur non numérique dans l'instantané de paramètres.")
        object.__setattr__(self, "analysis_settings", settings)

    @property
    def accepted_source_ids(self) -> tuple[str, ...]:
        return tuple(item.source_id for item in self.sources if item.accepted)

    @property
    def rejected_source_ids(self) -> tuple[str, ...]:
        return tuple(item.source_id for item in self.sources if not item.accepted)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "analysis_settings": dict(self.analysis_settings),
            "session_id": self.session_id,
            "campaign_id": self.campaign_id,
            "profile": self.profile,
            "context_signature": self.context_signature,
            "config_fingerprint": self.config_fingerprint,
            "mapping_fingerprint": self.mapping_fingerprint,
            "review_fingerprint": self.review_fingerprint,
            "diag_context_signature": self.diag_context_signature,
            "created_at": self.created_at,
            "accepted_source_ids": list(self.accepted_source_ids),
            "rejected_source_ids": list(self.rejected_source_ids),
            "sources": [item.to_dict() for item in self.sources],
        }


@dataclass(frozen=True)
class ArctaCampaignRun:
    run_id: str
    plan: ArctaCampaignRunPlan
    status: str = RUN_STATUS_PENDING
    progress_percent: float = 0.0
    message: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    artifacts: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _required_text(self.run_id, "run_id"))
        if not isinstance(self.plan, ArctaCampaignRunPlan):
            raise TypeError("plan doit être un ArctaCampaignRunPlan.")
        status = str(self.status or "").strip().upper()
        if status not in RUN_STATUSES:
            raise ValueError(f"Statut de run ARCTA invalide : {self.status!r}")
        progress = float(self.progress_percent)
        if not 0.0 <= progress <= 100.0:
            raise ValueError("progress_percent doit être compris entre 0 et 100.")
        if status == RUN_STATUS_PENDING and (self.started_at or self.finished_at):
            raise ValueError("Un run PENDING ne peut pas être daté comme exécuté.")
        if status == RUN_STATUS_RUNNING and not self.started_at:
            raise ValueError("Un run RUNNING doit avoir une date de démarrage.")
        if status in TERMINAL_RUN_STATUSES and not self.finished_at:
            raise ValueError("Un run terminé doit avoir une date de fin.")
        if status == RUN_STATUS_SUCCEEDED and progress != 100.0:
            raise ValueError("Un run SUCCEEDED doit être à 100 %.")
        if status == RUN_STATUS_FAILED and not str(self.error_code or "").strip():
            raise ValueError("Un run FAILED doit exposer error_code.")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "progress_percent", progress)
        object.__setattr__(self, "message", str(self.message or "").strip())
        object.__setattr__(self, "artifacts", tuple(dict(x) for x in self.artifacts))

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    def start(self, *, at: Optional[str] = None) -> "ArctaCampaignRun":
        if self.status != RUN_STATUS_PENDING:
            raise ValueError("Seul un run PENDING peut démarrer.")
        return replace(
            self,
            status=RUN_STATUS_RUNNING,
            started_at=at or _utc_now_iso(),
            message="Exécution ARCTA démarrée.",
        )

    def with_progress(self, percent: float, message: str = "") -> "ArctaCampaignRun":
        if self.status != RUN_STATUS_RUNNING:
            raise ValueError("La progression exige un run RUNNING.")
        value = float(percent)
        if value < self.progress_percent:
            raise ValueError("La progression d'un run ne peut pas reculer.")
        if value >= 100.0:
            raise ValueError("La réussite doit être enregistrée avec succeed().")
        return replace(self, progress_percent=value, message=message)

    def succeed(
        self,
        artifacts: tuple[Mapping[str, object], ...] = (),
        *,
        at: Optional[str] = None,
    ) -> "ArctaCampaignRun":
        if self.status != RUN_STATUS_RUNNING:
            raise ValueError("Seul un run RUNNING peut réussir.")
        return replace(
            self,
            status=RUN_STATUS_SUCCEEDED,
            progress_percent=100.0,
            message="Exécution ARCTA terminée.",
            finished_at=at or _utc_now_iso(),
            artifacts=tuple(dict(item) for item in artifacts),
        )

    def fail(
        self,
        code: str,
        message: str,
        *,
        at: Optional[str] = None,
    ) -> "ArctaCampaignRun":
        if self.status != RUN_STATUS_RUNNING:
            raise ValueError("Seul un run RUNNING peut échouer.")
        return replace(
            self,
            status=RUN_STATUS_FAILED,
            message="Exécution ARCTA en échec.",
            finished_at=at or _utc_now_iso(),
            error_code=_required_text(code, "error_code"),
            error_message=_required_text(message, "error_message"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "artifacts": [dict(item) for item in self.artifacts],
            "plan": self.plan.to_dict(),
        }


def campaign_run_source_from_dict(payload: Mapping) -> ArctaCampaignRunSource:
    return ArctaCampaignRunSource(
        source_id=payload.get("source_id", ""),
        source_name=payload.get("source_name", ""),
        stored_name=payload.get("stored_name", ""),
        size_bytes=payload.get("size_bytes", 0),
        uploaded_at=payload.get("uploaded_at", ""),
        accepted=payload.get("accepted", False),
    )


def campaign_run_plan_from_dict(payload: Mapping) -> ArctaCampaignRunPlan:
    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raise TypeError("sources doit être une liste.")
    return ArctaCampaignRunPlan(
        session_id=payload.get("session_id", ""),
        campaign_id=payload.get("campaign_id", ""),
        profile=payload.get("profile", ""),
        context_signature=payload.get("context_signature", ""),
        config_fingerprint=payload.get("config_fingerprint", ""),
        mapping_fingerprint=payload.get("mapping_fingerprint", ""),
        review_fingerprint=payload.get("review_fingerprint", ""),
        diag_context_signature=payload.get("diag_context_signature", ""),
        sources=tuple(campaign_run_source_from_dict(item) for item in raw_sources),
        created_at=payload.get("created_at", ""),
        schema_version=payload.get("schema_version", ""),
        analysis_settings=tuple(payload.get("analysis_settings", {}).items()),
    )


def campaign_run_from_dict(payload: Mapping) -> ArctaCampaignRun:
    raw_plan = payload.get("plan")
    if not isinstance(raw_plan, Mapping):
        raise TypeError("plan est absent ou invalide.")
    raw_artifacts = payload.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise TypeError("artifacts doit être une liste.")
    return ArctaCampaignRun(
        run_id=payload.get("run_id", ""),
        plan=campaign_run_plan_from_dict(raw_plan),
        status=payload.get("status", RUN_STATUS_PENDING),
        progress_percent=payload.get("progress_percent", 0.0),
        message=payload.get("message", ""),
        started_at=payload.get("started_at"),
        finished_at=payload.get("finished_at"),
        error_code=payload.get("error_code"),
        error_message=payload.get("error_message"),
        artifacts=tuple(dict(item) for item in raw_artifacts),
    )
