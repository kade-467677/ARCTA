from __future__ import annotations
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
import pandas as pd
from cta_core.models import ColumnSelection
from .analysis_config import ArctaAnalysisConfig, DEFAULT_ARCTA_ANALYSIS_CONFIG
from .columns import detect_analysis_mode
from .concat import build_column_map_sheet, build_concat_clean_df, build_concat_df
from .diag_summary import build_diag_synthesis, get_diag_short_vars_from_diag
from .profiles import require_profile_config
from .service import analyze_in_memory
from .documentation import build_diag_definitions_sheet
from .tolerance import tolerance_warnings
from .tolerance_explanations import tolerance_details

ProgressCallback = Callable[[float, str], None]

DIAG_AUDIT_SHEETS = (
    "DIAG_POP_VALUES", "DIAG_POP_DETAILS", "DIAG_POP_RULES",
    "DIAG_REVIEW",
    "DIAG_SHORT_SELECTION",
    "DIAG_SUMMARY",
    "DIAG_SYNTHESIS",
    "DIAG_ISO16269_4_SUMMARY",
    "DIAG_ISO16269_4_OUTLIERS",
    "DIAG_ISO16269_4_PLOTS",
    "DIAG_ISO16269_4_PLOTS_FULL",
    "DIAG_ISO16269_4_PLOTS_SHORT",
    "DIAG_PRE_CLEAN",
    "DIAG_BALANCE",
    "DIAG_COUPLE_CROSS",
    "DIAG_AUTOFREIN",
    "DIAG_UNWIND",
    "DIAG_EVENTS",
)

@dataclass
class ArctaCampaignResult:
    """Résultat analytique headless d'une campagne ARCTA."""
    profile: str
    mode: str
    constants: dict[str, Any]
    result_sheets: dict[str, pd.DataFrame] = field(default_factory=dict)
    mechanical_results: dict[str, "ArctaCampaignResult"] = field(default_factory=dict)

def build_arcta_settings_sheet(
    analysis_config: ArctaAnalysisConfig = DEFAULT_ARCTA_ANALYSIS_CONFIG,
) -> pd.DataFrame:
    """Trace les paramètres scientifiques réellement utilisés pour le run."""
    return pd.DataFrame([
        {
            "Parameter": "THR_RATIO_DEFAULT",
            "Value": analysis_config.thr_ratio,
            "Meaning": "Seuil CONCAT_CLEAN : début conservé lorsque Y >= ratio * Ymax",
        },
        {
            "Parameter": "ISO_TOL_P_CONTENT",
            "Value": analysis_config.iso_tol_p_content,
            "Meaning": "Proportion couverte par l'intervalle de tolérance ISO 16269-6",
        },
        {
            "Parameter": "ISO_TOL_CONF_LEVEL",
            "Value": analysis_config.iso_tol_conf_level,
            "Meaning": "Niveau de confiance de l'intervalle de tolérance ISO 16269-6",
        },
        {
            "Parameter": "ISO_MEDIAN_CONF_LEVEL",
            "Value": analysis_config.iso_median_conf_level,
            "Meaning": "Niveau de confiance cible de l'IC médiane ISO 16269-7",
        },
        {
            "Parameter": "MEAN_CI_CONF_LEVEL",
            "Value": analysis_config.mean_ci_conf_level,
            "Meaning": "Niveau de confiance bilatéral de l’IC de la moyenne (Student)",
        },
        {
            "Parameter": "NORMALITY_ALPHA",
            "Value": analysis_config.normality_alpha,
            "Meaning": "Seuil alpha du test de normalité",
        },
        {
            "Parameter": "NORMALITY_MIN_N",
            "Value": analysis_config.normality_min_n,
            "Meaning": "Effectif minimal avant test de normalité",
        },
    ])

def analyze_campaign(
    import_sheets: Mapping[str, pd.DataFrame],
    sel: ColumnSelection,
    diag: Mapping[str, pd.DataFrame],
    accepted: Sequence[str],
    constants: Mapping[str, Any],
    profile: str,
    analysis_config: ArctaAnalysisConfig = DEFAULT_ARCTA_ANALYSIS_CONFIG,
    progress: ProgressCallback | None = None,
    template_sheets: Mapping[str, pd.DataFrame] | None = None,
) -> ArctaCampaignResult:
    """
    Pipeline analytique ARCTA entièrement headless.

    Ne lit ni n'écrit de fichier.
    Ne génère ni graphe ni PDF.
    Ne dépend d'aucune UI.
    """
    require_profile_config(profile)
    sheets: dict[str, pd.DataFrame] = {}

    if template_sheets:
        sheets.update({
            str(name): df.copy()
            for name, df in template_sheets.items()
        })

    if "TEMPLATESYNTH_CONSTANTS" not in sheets:
        sheets["TEMPLATESYNTH_CONSTANTS"] = pd.DataFrame([dict(constants)])

    sheets["ARCTA_SETTINGS"] = build_arcta_settings_sheet(
        analysis_config
    )

    from .run_mechanics import settings_rows
    sheets["ARCTA_SETTINGS"] = pd.concat([sheets["ARCTA_SETTINGS"],
        settings_rows(constants, analysis_config.subtract_selflock)], ignore_index=True)

    if progress:
        progress(
            10,
            "Construction CONCAT en mémoire…",
        )

    df_concat = build_concat_df(
        import_sheets,
        sel,
        accepted,
    )

    sheets["CONCAT"] = df_concat
    sheets["ARCTA_COLUMN_MAP"] = build_column_map_sheet(
        sel,
        accepted,
    )

    if progress:
        progress(
            30,
            "Génération CONCAT_CLEAN en mémoire avec angles recalés A_eff…",
        )

    df_clean = build_concat_clean_df(
        df_concat,
        thr_ratio=analysis_config.thr_ratio,
        diag=diag,
    )

    sheets["CONCAT_CLEAN"] = df_clean
    mode = detect_analysis_mode(df_clean)

    if progress:
        progress(
            45,
            "Analyse ARCTA mémoire : µ, polynômes, COMPUTE…",
        )

    sheets.update(
        analyze_in_memory(
            df_clean,
            dict(constants),
            profile,
            progress=progress,
            diag=dict(diag),
            analysis_config=analysis_config,
        )
    )

    # ------------------------------------------------------------------
    # DIAG : synthèse métier + feuilles d'audit de la campagne
    # ------------------------------------------------------------------
    selected_short_vars = get_diag_short_vars_from_diag(
        diag
    )

    diag_synthesis = build_diag_synthesis(
        diag,
        selected_vars=selected_short_vars,
    )

    if (
        isinstance(diag_synthesis, pd.DataFrame)
        and not diag_synthesis.empty
    ):
        sheets["DIAG_SYNTHESIS"] = diag_synthesis

    # Conservation du comportement historique :
    # si une feuille DIAG existe déjà dans diag, elle est recopiée telle quelle.
    # DIAG_SYNTHESIS fait volontairement partie de cette liste pour conserver
    # la priorité historique d'une éventuelle feuille déjà présente.
    for key in DIAG_AUDIT_SHEETS:
        if key in diag:
            sheets[key] = diag[key]

    sheets["DIAG_DEFINITIONS"] = build_diag_definitions_sheet(
        analysis_config
    )

    for key in ("POLY_FITS", "POLY_FITS_STATS"):
        if key in sheets:
            sheets[key]["Torque_Basis"] = "EFFECTIVE" if analysis_config.subtract_selflock else "TOTAL"
            sheets[key]["KK_Model"] = constants.get("kk_model", "LEGACY_0577")
    sheets["ARCTA_TOLERANCE_WARNINGS"] = tolerance_warnings(sheets)
    sheets["ARCTA_TOLERANCE_DETAILS"] = tolerance_details(sheets)

    return ArctaCampaignResult(
        profile=profile,
        mode=mode,
        constants=dict(constants),
        result_sheets=sheets,
    )
