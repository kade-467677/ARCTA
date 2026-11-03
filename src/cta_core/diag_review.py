from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isfinite
from typing import Iterable, Mapping, Optional


ARCTA_DIAG_REVIEW_SCHEMA_VERSION = "1.0"

DIAG_AUTOMATIC_STATUS_OK = "OK"
DIAG_AUTOMATIC_STATUS_WARNING = "WARNING"
DIAG_AUTOMATIC_STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"

DIAG_AUTOMATIC_STATUSES = frozenset({
    DIAG_AUTOMATIC_STATUS_OK,
    DIAG_AUTOMATIC_STATUS_WARNING,
    DIAG_AUTOMATIC_STATUS_MANUAL_REVIEW,
})

DIAG_REVIEW_DECISION_PENDING = "PENDING"
DIAG_REVIEW_DECISION_ACCEPTED = "ACCEPTED"
DIAG_REVIEW_DECISION_REJECTED = "REJECTED"

DIAG_REVIEW_DECISIONS = frozenset({
    DIAG_REVIEW_DECISION_PENDING,
    DIAG_REVIEW_DECISION_ACCEPTED,
    DIAG_REVIEW_DECISION_REJECTED,
})

DIAG_REVIEW_STATUS_DRAFT = "DRAFT"
DIAG_REVIEW_STATUS_VALIDATED = "VALIDATED"

DIAG_REVIEW_STATUSES = frozenset({
    DIAG_REVIEW_STATUS_DRAFT,
    DIAG_REVIEW_STATUS_VALIDATED,
})


def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _required_text(
    value: object,
    field_name: str,
) -> str:
    normalized = str(
        value or ""
    ).strip()

    if not normalized:
        raise ValueError(
            f"{field_name} est obligatoire."
        )

    return normalized


def _normalize_flags(
    value: object,
) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(value, str):
        raw_flags = value.split(";")
    else:
        try:
            raw_flags = list(value)
        except TypeError:
            raw_flags = [value]

    flags: list[str] = []

    for raw_flag in raw_flags:
        flag = str(
            raw_flag or ""
        ).strip()

        if (
            not flag
            or flag.upper() == "OK"
            or flag in flags
        ):
            continue

        flags.append(
            flag
        )

    return tuple(flags)


@dataclass(frozen=True)
class DiagTrialReview:
    source_id: str
    source_name: str
    automatic_status: str
    quality_score: float
    main_flags: tuple[str, ...] = ()
    decision: str = DIAG_REVIEW_DECISION_PENDING
    comment: str = ""
    reviewed_at: Optional[str] = None

    def __post_init__(self) -> None:
        source_id = _required_text(
            self.source_id,
            "source_id",
        )

        source_name = _required_text(
            self.source_name,
            "source_name",
        )

        automatic_status = str(
            self.automatic_status or ""
        ).strip().upper()

        if automatic_status not in DIAG_AUTOMATIC_STATUSES:
            raise ValueError(
                "Statut DIAG automatique invalide : "
                f"{self.automatic_status!r}"
            )

        decision = str(
            self.decision or ""
        ).strip().upper()

        if decision not in DIAG_REVIEW_DECISIONS:
            raise ValueError(
                "Décision de revue DIAG invalide : "
                f"{self.decision!r}"
            )

        try:
            quality_score = float(
                self.quality_score
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "quality_score doit être numérique."
            ) from exc

        if (
            not isfinite(quality_score)
            or quality_score < 0.0
            or quality_score > 100.0
        ):
            raise ValueError(
                "quality_score doit être compris entre 0 et 100."
            )

        reviewed_at = (
            str(self.reviewed_at).strip()
            if self.reviewed_at is not None
            else None
        )

        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "automatic_status", automatic_status)
        object.__setattr__(self, "quality_score", quality_score)
        object.__setattr__(self, "main_flags", _normalize_flags(self.main_flags))
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "comment", str(self.comment or "").strip())
        object.__setattr__(self, "reviewed_at", reviewed_at or None)

    @property
    def suggested_decision(self) -> str:
        if self.automatic_status in {
            DIAG_AUTOMATIC_STATUS_OK,
            DIAG_AUTOMATIC_STATUS_WARNING,
        }:
            return DIAG_REVIEW_DECISION_ACCEPTED

        return DIAG_REVIEW_DECISION_PENDING

    @property
    def decided(self) -> bool:
        return self.decision != DIAG_REVIEW_DECISION_PENDING

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []

        if not self.decided:
            errors.append(
                "Une décision ACCEPTED ou REJECTED est obligatoire."
            )

        if self.decided and not self.reviewed_at:
            errors.append(
                "La date de revue est obligatoire pour une décision explicite."
            )

        if (
            self.decision == DIAG_REVIEW_DECISION_REJECTED
            and not self.comment
        ):
            errors.append(
                "Un commentaire est obligatoire pour rejeter un essai."
            )

        if (
            self.decision == DIAG_REVIEW_DECISION_ACCEPTED
            and self.automatic_status == DIAG_AUTOMATIC_STATUS_MANUAL_REVIEW
            and not self.comment
        ):
            errors.append(
                "Un commentaire est obligatoire pour accepter un essai "
                "classé MANUAL_REVIEW par le DIAG."
            )

        return tuple(errors)

    def validate(self) -> None:
        errors = self.validation_errors()

        if errors:
            raise ValueError(
                f"Revue DIAG invalide pour {self.source_name!r} : "
                + " ".join(errors)
            )

    def with_decision(
        self,
        decision: str,
        comment: str = "",
        reviewed_at: Optional[str] = None,
    ) -> "DiagTrialReview":
        normalized_decision = str(
            decision or ""
        ).strip().upper()

        if normalized_decision == DIAG_REVIEW_DECISION_PENDING:
            reviewed_at = None
        elif reviewed_at is None:
            reviewed_at = _utc_now_iso()

        return replace(
            self,
            decision=normalized_decision,
            comment=comment,
            reviewed_at=reviewed_at,
        )

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "automatic_status": self.automatic_status,
            "quality_score": self.quality_score,
            "main_flags": list(self.main_flags),
            "suggested_decision": self.suggested_decision,
            "decision": self.decision,
            "comment": self.comment,
            "reviewed_at": self.reviewed_at,
        }


@dataclass(frozen=True)
class ArctaDiagReview:
    trials: tuple[DiagTrialReview, ...]
    status: str = DIAG_REVIEW_STATUS_DRAFT
    updated_at: Optional[str] = None
    schema_version: str = ARCTA_DIAG_REVIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        trials = tuple(self.trials)

        if not trials:
            raise ValueError(
                "La revue DIAG doit contenir au moins un essai."
            )

        source_ids = [
            trial.source_id
            for trial in trials
        ]

        if len(source_ids) != len(set(source_ids)):
            raise ValueError(
                "Chaque source ne peut apparaître qu'une fois "
                "dans la revue DIAG."
            )

        status = str(
            self.status or ""
        ).strip().upper()

        if status not in DIAG_REVIEW_STATUSES:
            raise ValueError(
                "Statut de revue DIAG invalide : "
                f"{self.status!r}"
            )

        schema_version = str(
            self.schema_version or ""
        ).strip()

        if schema_version != ARCTA_DIAG_REVIEW_SCHEMA_VERSION:
            raise ValueError(
                "Version de schéma de revue DIAG non supportée : "
                f"{schema_version!r}"
            )

        updated_at = (
            str(self.updated_at).strip()
            if self.updated_at is not None
            else None
        )

        object.__setattr__(self, "trials", trials)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "updated_at", updated_at or None)

        if status == DIAG_REVIEW_STATUS_VALIDATED:
            self.validate()

    @property
    def validated(self) -> bool:
        return self.status == DIAG_REVIEW_STATUS_VALIDATED

    @property
    def all_decided(self) -> bool:
        return all(
            trial.decided
            for trial in self.trials
        )

    @property
    def accepted_source_ids(self) -> tuple[str, ...]:
        return tuple(
            trial.source_id
            for trial in self.trials
            if trial.decision == DIAG_REVIEW_DECISION_ACCEPTED
        )

    @property
    def rejected_source_ids(self) -> tuple[str, ...]:
        return tuple(
            trial.source_id
            for trial in self.trials
            if trial.decision == DIAG_REVIEW_DECISION_REJECTED
        )

    @property
    def pending_source_ids(self) -> tuple[str, ...]:
        return tuple(
            trial.source_id
            for trial in self.trials
            if trial.decision == DIAG_REVIEW_DECISION_PENDING
        )

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_source_ids)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_source_ids)

    @property
    def pending_count(self) -> int:
        return len(self.pending_source_ids)

    def validate(self) -> None:
        errors: list[str] = []

        for trial in self.trials:
            for error in trial.validation_errors():
                errors.append(
                    f"{trial.source_name}: {error}"
                )

        if errors:
            raise ValueError(
                "La revue DIAG ne peut pas être validée. "
                + " ".join(errors)
            )

    def with_status(
        self,
        status: str,
        updated_at: Optional[str] = None,
    ) -> "ArctaDiagReview":
        if updated_at is None:
            updated_at = _utc_now_iso()

        return replace(
            self,
            status=status,
            updated_at=updated_at,
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "validated": self.validated,
            "updated_at": self.updated_at,
            "total_count": len(self.trials),
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "pending_count": self.pending_count,
            "all_decided": self.all_decided,
            "accepted_source_ids": list(self.accepted_source_ids),
            "rejected_source_ids": list(self.rejected_source_ids),
            "pending_source_ids": list(self.pending_source_ids),
            "trials": [
                trial.to_dict()
                for trial in self.trials
            ],
        }


def diag_trial_review_from_dict(
    payload: Mapping,
) -> DiagTrialReview:
    if not isinstance(payload, Mapping):
        raise TypeError(
            "La revue d'un essai doit être un mapping."
        )

    return DiagTrialReview(
        source_id=payload.get("source_id", ""),
        source_name=payload.get("source_name", ""),
        automatic_status=payload.get("automatic_status", ""),
        quality_score=payload.get("quality_score", 0.0),
        main_flags=_normalize_flags(payload.get("main_flags")),
        decision=payload.get(
            "decision",
            DIAG_REVIEW_DECISION_PENDING,
        ),
        comment=payload.get("comment", ""),
        reviewed_at=payload.get("reviewed_at"),
    )


def arcta_diag_review_from_dict(
    payload: Mapping,
) -> ArctaDiagReview:
    if not isinstance(payload, Mapping):
        raise TypeError(
            "La revue DIAG doit être un mapping."
        )

    trials_payload = payload.get("trials")

    if not isinstance(trials_payload, list):
        raise TypeError(
            "Le champ 'trials' de la revue DIAG doit être une liste."
        )

    return ArctaDiagReview(
        trials=tuple(
            diag_trial_review_from_dict(item)
            for item in trials_payload
        ),
        status=payload.get(
            "status",
            DIAG_REVIEW_STATUS_DRAFT,
        ),
        updated_at=payload.get("updated_at"),
        schema_version=payload.get(
            "schema_version",
            ARCTA_DIAG_REVIEW_SCHEMA_VERSION,
        ),
    )


def build_diag_review_from_summary(
    summary_rows: Iterable[Mapping],
    source_names: Optional[Mapping[str, str]] = None,
) -> ArctaDiagReview:
    if hasattr(summary_rows, "to_dict"):
        rows = summary_rows.to_dict(
            orient="records"
        )
    else:
        rows = list(summary_rows)

    names = {
        str(source_id): str(source_name)
        for source_id, source_name in dict(
            source_names or {}
        ).items()
    }

    trials: list[DiagTrialReview] = []

    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError(
                "Chaque ligne DIAG doit être un mapping."
            )

        source_id = _required_text(
            row.get("Trial_ID"),
            "Trial_ID",
        )

        source_name = str(
            row.get("Source_Name")
            or names.get(source_id)
            or source_id
        ).strip()

        trials.append(
            DiagTrialReview(
                source_id=source_id,
                source_name=source_name,
                automatic_status=row.get("Status", ""),
                quality_score=row.get("Quality_Score", 0.0),
                main_flags=_normalize_flags(
                    row.get("Main_Flags")
                ),
            )
        )

    return ArctaDiagReview(
        trials=tuple(trials),
    )
