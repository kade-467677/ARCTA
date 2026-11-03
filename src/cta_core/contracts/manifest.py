from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from .schema_version import ARCTA_RUN_MANIFEST_SCHEMA_VERSION

ARCTA_ARTIFACT_STATUSES = frozenset({
    "SAVED",
    "CANCELLED",
    "ERROR",
    "SKIPPED",
    "UNKNOWN",
})

@dataclass(frozen=True)
class ArctaArtifactManifest:
    """État d'un artefact produit par un run ARCTA."""
    kind: str
    status: str
    path: str = ""
    message: str = ""
    error_type: str | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind).strip().lower()
        status = str(self.status).strip().upper() or "UNKNOWN"
        if not kind:
            raise ValueError("Le type d'artefact ne peut pas être vide.")
        if status not in ARCTA_ARTIFACT_STATUSES:
            raise ValueError(f"Statut d'artefact ARCTA inconnu : {status}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "path", str(self.path or ""))
        object.__setattr__(self, "message", str(self.message or ""))

    @property
    def saved(self) -> bool:
        return self.status == "SAVED"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "status": self.status,
            "path": self.path,
            "message": self.message,
            "error_type": self.error_type,
            "saved": self.saved,
        }

@dataclass(frozen=True)
class ArctaRunManifest:
    """Contrat versionné décrivant un run ARCTA terminé."""
    schema_version: str
    profile: str
    mode: str
    import_path: str
    output_path: str
    sheet_names: tuple[str, ...]
    artifacts: tuple[ArctaArtifactManifest, ...]

    def artifact(self, kind: str) -> ArctaArtifactManifest | None:
        key = str(kind).strip().lower()
        for artifact in self.artifacts:
            if artifact.kind == key:
                return artifact
        return None

    @property
    def run_status(self) -> str:
        xlsx = self.artifact("xlsx")
        if xlsx is None:
            return "UNKNOWN"
        if xlsx.status == "ERROR":
            return "ERROR"
        if xlsx.status == "CANCELLED":
            return "COMPLETED_WITH_WARNINGS"
        if xlsx.status != "SAVED":
            return "UNKNOWN"
        if any(
            artifact.status in {"ERROR", "CANCELLED"}
            for artifact in self.artifacts
            if artifact.kind != "xlsx"
        ):
            return "COMPLETED_WITH_WARNINGS"
        return "COMPLETED"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_status": self.run_status,
            "profile": self.profile,
            "mode": self.mode,
            "import_path": self.import_path,
            "output_path": self.output_path,
            "sheet_names": list(self.sheet_names),
            "artifacts": [
                artifact.to_dict()
                for artifact in self.artifacts
            ],
        }

def _artifact_from_write_status(
    prefix: str,
    write_status: Mapping[str, Any],
) -> ArctaArtifactManifest:
    key = str(prefix).strip().lower()
    status = str(
        write_status.get(
            f"{key}_status",
            "UNKNOWN",
        )
    ).strip().upper() or "UNKNOWN"
    if status not in ARCTA_ARTIFACT_STATUSES:
        status = "UNKNOWN"
    return ArctaArtifactManifest(
        kind=key,
        status=status,
        path=str(
            write_status.get(
                f"{key}_path",
                "",
            )
            or ""
        ),
        message=str(
            write_status.get(
                f"{key}_message",
                "",
            )
            or ""
        ),
        error_type=write_status.get(
            f"{key}_error_type"
        ),
    )

def build_arcta_run_manifest(
    *,
    profile: str,
    mode: str,
    import_path: str,
    output_path: str,
    sheet_names: Sequence[str],
    write_status: Mapping[str, Any],
) -> ArctaRunManifest:
    """Construit le manifeste public d'un run ARCTA."""
    unique_sheets: list[str] = []
    for name in sheet_names:
        value = str(name)
        if value not in unique_sheets:
            unique_sheets.append(value)
    artifacts = tuple(
        _artifact_from_write_status(
            kind,
            write_status,
        )
        for kind in ("xlsx", "pdf")
    )
    return ArctaRunManifest(
        schema_version=ARCTA_RUN_MANIFEST_SCHEMA_VERSION,
        profile=str(profile),
        mode=str(mode),
        import_path=str(import_path),
        output_path=str(output_path),
        sheet_names=tuple(unique_sheets),
        artifacts=artifacts,
    )