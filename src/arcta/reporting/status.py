from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class ExportStatus(str, Enum):
    SAVED = "SAVED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"

@dataclass(frozen=True)
class ExportResult:
    """Résultat explicite et sérialisable d'une opération d'export."""
    status: ExportStatus
    path: str
    message: str = ""
    error_type: str | None = None

    @property
    def saved(self) -> bool:
        return self.status is ExportStatus.SAVED

    @property
    def cancelled(self) -> bool:
        return self.status is ExportStatus.CANCELLED

    @property
    def failed(self) -> bool:
        return self.status is ExportStatus.ERROR

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "path": self.path,
            "message": self.message,
            "error_type": self.error_type,
            "saved": self.saved,
        }

    @classmethod
    def saved_result(
        cls,
        path: str,
        message: str = "Export sauvegardé.",
    ) -> "ExportResult":
        return cls(
            status=ExportStatus.SAVED,
            path=str(path),
            message=message,
        )

    @classmethod
    def cancelled_result(
        cls,
        path: str,
        message: str = "Export annulé.",
    ) -> "ExportResult":
        return cls(
            status=ExportStatus.CANCELLED,
            path=str(path),
            message=message,
        )

    @classmethod
    def error_result(
        cls,
        path: str,
        error: Exception | str,
    ) -> "ExportResult":
        if isinstance(error, Exception):
            message = str(error)
            error_type = type(error).__name__
        else:
            message = str(error)
            error_type = None
        return cls(
            status=ExportStatus.ERROR,
            path=str(path),
            message=message,
            error_type=error_type,
        )

    @classmethod
    def skipped_result(
        cls,
        path: str,
        message: str = "Export non demandé.",
    ) -> "ExportResult":
        return cls(
            status=ExportStatus.SKIPPED,
            path=str(path),
            message=message,
        )

def export_result_status_fields(
        prefix: str,
        result: ExportResult,
) -> dict[str, object]:
    """Convertit un ExportResult en champs de statut préfixés."""
    key = str(prefix).strip().lower()
    if not key:
        raise ValueError("Le préfixe d'export ne peut pas être vide.")
    return {
        f"{key}_saved": result.saved,
        f"{key}_status": result.status.value,
        f"{key}_path": result.path,
        f"{key}_message": result.message,
        f"{key}_error_type": result.error_type,
    }