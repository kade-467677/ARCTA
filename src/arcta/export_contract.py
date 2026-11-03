from __future__ import annotations
from collections.abc import Mapping, Sequence
from pathlib import Path

ARCTA_WORKBOOK_SHEET_ORDER = (
    "Configuration_Testée",
    "TEMPLATESYNTH_CONSTANTS",
    "ARCTA_SOURCES",
    "CONCAT",
    "CONCAT_CLEAN",
    "CONCAT_CLEAN+µ_global",
    "CONCAT_CLEAN+µ_fine",
    "POLY_FITS",
    "POLY_FITS_STATS",
    "SELF_LOCK_REFIT",
    "AUTOFREIN_COMPARISON",
    "ARCTA_PLOTS",
    "ARCTA_PLOTS_ERRORS",
    "ARCTA_PDF_INVENTORY",
    "ARCTA_PDF_SELECTION",
    "ARCTA_PDF_REPORT",
    "ARCTA_MEMORY_SUMMARY",
    "ARCTA_COLUMN_MAP",
    "DIAG_REVIEW",
    "DIAG_SYNTHESIS",
    "DIAG_DEFINITIONS",
    "DIAG_SUMMARY",
    "DIAG_ISO16269_4_SUMMARY",
    "DIAG_ISO16269_4_OUTLIERS",
    "DIAG_ISO16269_4_PLOTS",
    "DIAG_ISO16269_4_PLOTS_SHORT",
    "DIAG_ISO16269_4_PLOTS_FULL",
    "DIAG_PRE_CLEAN",
    "DIAG_BALANCE",
    "DIAG_COUPLE_CROSS",
    "DIAG_AUTOFREIN",
    "DIAG_UNWIND",
    "DIAG_EVENTS",
    "ARCTA_SETTINGS",
)


def make_output_path(import_path: str) -> str:
    """Construit le chemin XLSX ARCTA à partir du chemin IMPORT."""
    path = Path(
        str(import_path).replace(
            "\\",
            "/",
        )
    )
    stem = path.stem
    suffix = (
        stem[len("IMPORT_"):]
        if stem.upper().startswith("IMPORT_")
        else stem
    )
    return str(
        path.parent
        / f"CONCAT_{suffix}.xlsx"
    )


def ordered_workbook_sheet_names(
    sheets: Mapping[str, object],
    preferred_order: Sequence[str] = ARCTA_WORKBOOK_SHEET_ORDER,
) -> list[str]:
    """
    Retourne les noms de feuilles dans l'ordre contractuel ARCTA.

    Les feuilles connues suivent l'ordre officiel.
    Les feuilles supplémentaires sont ajoutées ensuite dans leur ordre
    d'insertion afin de ne perdre aucune sortie future ou expérimentale.
    """
    out: list[str] = []
    seen: set[str] = set()

    for name in preferred_order:
        if name in sheets and name not in seen:
            out.append(name)
            seen.add(name)

    for name in sheets:
        if name not in seen:
            out.append(name)
            seen.add(name)

    return out
