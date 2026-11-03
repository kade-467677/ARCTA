from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SUPPORTED_ARCTA_MANIFEST_SCHEMAS_FOR_DABCTA = frozenset({"1.0"})
DABCTA_SUPPORTED_ARCTA_MODES = frozenset({"basic", "global", "fine"})
DABCTA_INGESTIBLE_RUN_STATUSES = frozenset({
    "COMPLETED",
    "COMPLETED_WITH_WARNINGS",
})
DABCTA_REQUIRED_ARCTA_SHEETS = frozenset({
    "CONCAT_CLEAN",
})

@dataclass(frozen=True)
class ArctaDabctaCompatibility:
    """Résultat de validation d'un manifeste ARCTA pour ingestion DABCTA."""
    manifest_valid: bool
    ingestible: bool
    schema_version: str
    profile: str
    mode: str
    run_status: str
    xlsx_path: str
    validation_errors: tuple[str, ...] = ()
    ingestion_blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_valid": self.manifest_valid,
            "ingestible": self.ingestible,
            "schema_version": self.schema_version,
            "profile": self.profile,
            "mode": self.mode,
            "run_status": self.run_status,
            "xlsx_path": self.xlsx_path,
            "validation_errors": list(self.validation_errors),
            "ingestion_blockers": list(self.ingestion_blockers),
            "warnings": list(self.warnings),
        }

def _find_artifact(
    payload: Mapping[str, Any],
    kind: str,
) -> Mapping[str, Any] | None:
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, (list, tuple)):
        return None
    expected = str(kind).strip().lower()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        artifact_kind = str(
            artifact.get("kind", "")
        ).strip().lower()
        if artifact_kind == expected:
            return artifact
    return None

def evaluate_arcta_manifest_for_dabcta(
    payload: Mapping[str, Any],
) -> ArctaDabctaCompatibility:
    """
    Évalue la compatibilité technique d'un manifeste ARCTA avec DABCTA.

    Cette fonction ne lit aucun fichier XLSX : elle valide uniquement le
    contrat de run. La validation du contenu physique du classeur sera faite
    à la frontière d'import DABCTA.
    """
    validation_errors: list[str] = []
    ingestion_blockers: list[str] = []
    warnings: list[str] = []

    schema_version = str(
        payload.get("schema_version", "")
    ).strip()

    profile = str(
        payload.get("profile", "")
    ).strip()

    mode = str(
        payload.get("mode", "")
    ).strip().lower()

    run_status = str(
        payload.get("run_status", "")
    ).strip().upper()

    if not schema_version:
        validation_errors.append(
            "MISSING_SCHEMA_VERSION"
        )
    elif (
        schema_version
        not in SUPPORTED_ARCTA_MANIFEST_SCHEMAS_FOR_DABCTA
    ):
        validation_errors.append(
            "UNSUPPORTED_SCHEMA_VERSION"
        )

    if not profile:
        validation_errors.append(
            "MISSING_PROFILE"
        )

    if not mode:
        validation_errors.append(
            "MISSING_MODE"
        )
    elif mode not in DABCTA_SUPPORTED_ARCTA_MODES:
        validation_errors.append(
            "UNSUPPORTED_MODE"
        )

    if not run_status:
        validation_errors.append(
            "MISSING_RUN_STATUS"
        )

    raw_sheets = payload.get(
        "sheet_names",
        [],
    )

    if not isinstance(
        raw_sheets,
        (list, tuple),
    ):
        validation_errors.append(
            "INVALID_SHEET_NAMES"
        )
        sheet_names: set[str] = set()
    else:
        sheet_names = {
            str(name)
            for name in raw_sheets
        }

    raw_artifacts = payload.get(
        "artifacts",
        [],
    )

    if not isinstance(
        raw_artifacts,
        (list, tuple),
    ):
        validation_errors.append(
            "INVALID_ARTIFACTS"
        )

    xlsx_artifact = _find_artifact(
        payload,
        "xlsx",
    )

    xlsx_path = ""

    if xlsx_artifact is None:
        validation_errors.append(
            "MISSING_XLSX_ARTIFACT"
        )
    else:
        xlsx_status = str(
            xlsx_artifact.get(
                "status",
                "",
            )
        ).strip().upper()

        xlsx_path = str(
            xlsx_artifact.get(
                "path",
                "",
            )
            or ""
        ).strip()

        if xlsx_status != "SAVED":
            ingestion_blockers.append(
                "XLSX_NOT_SAVED"
            )

        if not xlsx_path:
            ingestion_blockers.append(
                "MISSING_XLSX_PATH"
            )

    for required_sheet in sorted(
        DABCTA_REQUIRED_ARCTA_SHEETS
    ):
        if required_sheet not in sheet_names:
            ingestion_blockers.append(
                f"MISSING_REQUIRED_SHEET:{required_sheet}"
            )

    if (
        run_status
        and run_status
        not in DABCTA_INGESTIBLE_RUN_STATUSES
    ):
        ingestion_blockers.append(
            f"RUN_STATUS_NOT_INGESTIBLE:{run_status}"
        )

    if run_status == "COMPLETED_WITH_WARNINGS":
        warnings.append(
            "ARCTA_RUN_COMPLETED_WITH_WARNINGS"
        )

    pdf_artifact = _find_artifact(
        payload,
        "pdf",
    )

    if pdf_artifact is not None:
        pdf_status = str(
            pdf_artifact.get(
                "status",
                "",
            )
        ).strip().upper()

        if pdf_status in {
            "ERROR",
            "CANCELLED",
        }:
            warnings.append(
                f"PDF_EXPORT_{pdf_status}"
            )

    manifest_valid = not validation_errors

    ingestible = (
        manifest_valid
        and not ingestion_blockers
    )

    return ArctaDabctaCompatibility(
        manifest_valid=manifest_valid,
        ingestible=ingestible,
        schema_version=schema_version,
        profile=profile,
        mode=mode,
        run_status=run_status,
        xlsx_path=xlsx_path,
        validation_errors=tuple(
            validation_errors
        ),
        ingestion_blockers=tuple(
            ingestion_blockers
        ),
        warnings=tuple(
            warnings
        ),
    )