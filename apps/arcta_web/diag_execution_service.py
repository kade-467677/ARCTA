from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import pandas as pd

from cta_core.config import (
    DEFAULT_DIAG_NUMERICAL_CONFIG,
)
from cta_core.diag.batch import (
    analyze_diag_batch,
)
from cta_core.diag.iso16269_4 import (
    build_iso16269_4_outliers,
)
from cta_core.diag_review import (
    ArctaDiagReview,
    build_diag_review_from_summary,
)
from arcta.diag_summary import (
    DIAG_ISO16269_4_IQR_FAIL_K,
    DIAG_ISO16269_4_IQR_WARN_K,
    DIAG_ISO16269_4_MIN_N,
    DIAG_ISO16269_4_ROBUST_Z_FAIL,
    DIAG_ISO16269_4_ROBUST_Z_WARN,
    DIAG_ISO16269_4_SCALARS,
    build_diag_short_selection_sheet,
)

from apps.arcta_web.campaign_mapping_service import (
    inspect_session_mapping_compatibility,
)
from apps.arcta_web.session_mapping import (
    load_session_mapping,
)
from apps.arcta_web.session_canonical_config import (
    load_session_canonical_config,
)
from apps.arcta_web.source_preview import (
    read_source_dataframe,
)
from web_common.sessions import is_trial_source


ProgressCallback = Callable[[float, str], None]


class DiagExecutionPrerequisiteError(ValueError):
    """L'exécution DIAG est bloquée par un prérequis Web."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        compatibility: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.compatibility = (
            dict(compatibility)
            if compatibility is not None
            else None
        )


@dataclass(frozen=True)
class WebDiagExecutionResult:
    """Résultat interne du jalon 61B, sans persistance ni API."""

    compatibility: dict[str, object]
    source_preparation: tuple[dict[str, object], ...]
    source_errors: tuple[dict[str, object], ...]
    diag: dict[str, pd.DataFrame]
    trial_results: dict[str, dict[str, Any]]
    review_summary: pd.DataFrame
    review: ArctaDiagReview


def _session_sources(session) -> tuple:
    raw_sources = getattr(
        session,
        "sources",
        {},
    )

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


def _source_id(source) -> str:
    return str(
        getattr(source, "source_id", "")
    ).strip()


def _source_name(source) -> str:
    return str(
        getattr(
            source,
            "original_name",
            _source_id(source),
        )
    ).strip()


def _source_path(source) -> Path:
    raw_path = getattr(
        source,
        "storage_path",
        None,
    )

    if raw_path is None:
        raise ValueError(
            "La source ne possède pas de chemin de stockage."
        )

    return Path(raw_path)


def _sheet_for_source(
    source,
    sheet_name: str | None,
) -> str | None:
    if _source_path(source).suffix.lower() == ".xlsx":
        return sheet_name

    return None


def _source_error_summary(
    source_id: str,
) -> dict[str, object]:
    return {
        "Trial_ID": source_id,
        "Mode": "UNAVAILABLE",
        "Status": "MANUAL_REVIEW",
        "Quality_Score": 0.0,
        "Use_For_ARCTA": False,
        "Main_Flags": "SOURCE_PREPARATION_ERROR",
        "Main_Notes": (
            "La source n'a pas pu être préparée pour le DIAG."
        ),
    }


def _ordered_summary(
    summary: pd.DataFrame,
    sources: tuple,
    source_error_ids: set[str],
) -> pd.DataFrame:
    rows = (
        summary.to_dict(orient="records")
        if summary is not None
        else []
    )

    rows_by_id = {
        str(row.get("Trial_ID")): row
        for row in rows
    }

    ordered_rows: list[dict[str, object]] = []

    for source in sources:
        source_id = _source_id(source)
        row = rows_by_id.pop(source_id, None)

        if row is not None:
            ordered_rows.append(row)
        elif source_id in source_error_ids:
            ordered_rows.append(
                _source_error_summary(source_id)
            )

    ordered_rows.extend(rows_by_id.values())

    return pd.DataFrame(ordered_rows)


def _add_torsion_geometry_from_config(
    session,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Transmet au DIAG le diamètre explicite, sans approximation cachée."""
    state = load_session_canonical_config(session)
    if state is None or not state.extracted or state.config is None:
        return config

    field = state.config.get_field("screw_torsion_diameter_mm")
    if field.missing or field.status == "AMBIGUOUS":
        return config
    try:
        diameter = float(field.value)
    except (TypeError, ValueError):
        return config
    if not math.isfinite(diameter) or diameter <= 0:
        return config

    location = "CONFIG canonique"
    if field.source_file:
        location += f" — {field.source_file}"
    if field.source_sheet:
        location += f" — {field.source_sheet}"
    if field.source_cell:
        location += f"!{field.source_cell}"
    config["screw_torsion_diameter_mm"] = diameter
    config["screw_torsion_diameter_source"] = location
    return config


def execute_session_diag(
    session,
    *,
    progress: ProgressCallback | None = None,
    numerical_config: Mapping[str, Any] | None = None,
) -> WebDiagExecutionResult:
    """
    Prépare puis exécute le DIAG headless pour toute une campagne.

    Le mapping validé est unique pour la campagne. Sa compatibilité
    est recalculée juste avant toute lecture intégrale ou tout calcul.
    """
    stored_mapping = load_session_mapping(session)

    if stored_mapping is None:
        raise DiagExecutionPrerequisiteError(
            "Le DIAG requiert un mapping de campagne enregistré.",
            code="MAPPING_MISSING",
        )

    if not stored_mapping.validated:
        raise DiagExecutionPrerequisiteError(
            "Le DIAG requiert un mapping de campagne VALIDATED.",
            code="MAPPING_NOT_VALIDATED",
        )

    mapping = stored_mapping.mapping
    mapping.validate()

    try:
        compatibility = inspect_session_mapping_compatibility(
            session,
            mapping,
        )
    except Exception as exc:
        raise DiagExecutionPrerequisiteError(
            "Le contrôle de compatibilité campagne a échoué : "
            f"{exc}",
            code="COMPATIBILITY_CHECK_FAILED",
        ) from exc

    if not compatibility.get("all_compatible"):
        raise DiagExecutionPrerequisiteError(
            "Le DIAG est bloqué : au moins une source est "
            "incompatible avec le mapping de campagne.",
            code="CAMPAIGN_INCOMPATIBLE",
            compatibility=compatibility,
        )

    sources = _session_sources(session)
    source_names = {
        _source_id(source): _source_name(source)
        for source in sources
    }

    import_sheets: dict[str, pd.DataFrame] = {}
    preparation: list[dict[str, object]] = []
    source_errors: list[dict[str, object]] = []

    for source in sources:
        source_id = _source_id(source)
        source_name = _source_name(source)
        sheet_name = _sheet_for_source(
            source,
            mapping.sheet_name,
        )

        try:
            prepared = read_source_dataframe(
                _source_path(source),
                sheet_name=sheet_name,
            )

            dataframe = prepared["dataframe"]

            if not isinstance(dataframe, pd.DataFrame):
                raise TypeError(
                    "Le lecteur de source n'a pas retourné de DataFrame."
                )

            mapping.validate(dataframe.columns)
            import_sheets[source_id] = dataframe

            preparation.append({
                "source_id": source_id,
                "source_name": source_name,
                "status": "READY",
                "sheet_name": prepared.get("selected_sheet"),
                "header_row_1based": prepared.get(
                    "header_row_1based"
                ),
                "units_row_1based": prepared.get(
                    "units_row_1based"
                ),
                "row_count": int(prepared.get("row_count", 0)),
                "columns": list(prepared.get("columns", [])),
            })

        except Exception as exc:
            error = {
                "source_id": source_id,
                "source_name": source_name,
                "sheet_name": sheet_name,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }

            source_errors.append(error)
            preparation.append({
                "source_id": source_id,
                "source_name": source_name,
                "status": "ERROR",
                "sheet_name": sheet_name,
                "header_row_1based": None,
                "units_row_1based": None,
                "row_count": 0,
                "columns": [],
            })

    config = (
        dict(numerical_config)
        if numerical_config is not None
        else DEFAULT_DIAG_NUMERICAL_CONFIG.to_dict()
    )
    config = _add_torsion_geometry_from_config(session, config)

    batch = analyze_diag_batch(
        import_sheets,
        mapping.to_column_selection(),
        config,
        progress=progress,
    )

    diag = dict(batch["diag"])
    diag["DIAG_SHORT_SELECTION"] = build_diag_short_selection_sheet()
    diag = build_iso16269_4_outliers(
        diag,
        DIAG_ISO16269_4_SCALARS,
        min_n=DIAG_ISO16269_4_MIN_N,
        iqr_warn_k=DIAG_ISO16269_4_IQR_WARN_K,
        iqr_fail_k=DIAG_ISO16269_4_IQR_FAIL_K,
        robust_z_warn=DIAG_ISO16269_4_ROBUST_Z_WARN,
        robust_z_fail=DIAG_ISO16269_4_ROBUST_Z_FAIL,
    )
    source_error_ids = {
        str(error["source_id"])
        for error in source_errors
    }

    review_summary = _ordered_summary(
        diag.get("DIAG_SUMMARY", pd.DataFrame()),
        sources,
        source_error_ids,
    )

    review = build_diag_review_from_summary(
        review_summary,
        source_names=source_names,
    )

    return WebDiagExecutionResult(
        compatibility=dict(compatibility),
        source_preparation=tuple(preparation),
        source_errors=tuple(source_errors),
        diag=diag,
        trial_results=dict(batch["trial_results"]),
        review_summary=review_summary,
        review=review,
    )
