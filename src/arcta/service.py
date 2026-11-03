from __future__ import annotations
from collections.abc import Callable
from typing import Any
import numpy as np
import pandas as pd
from cta_core.parsing import coerce_numeric_series
from .analysis_config import ArctaAnalysisConfig, DEFAULT_ARCTA_ANALYSIS_CONFIG
from .autofrein import build_autofrein_sheets_in_memory
from .columns import detect_analysis_mode, group_concat_columns_by_trial, pick_first
from .compute import (
    build_compute_sheets_from_polyfits_df,
    build_polyfits_from_df,
    build_polyfits_stats_from_compute_sheets,
)
from .friction import build_mu_df_from_clean
from .profiles import get_profile_config

ProgressCallback = Callable[[float, str], None]

def analyze_in_memory_summary(
    df_clean: pd.DataFrame,
    profile: str,
) -> dict[str, pd.DataFrame]:
    """Synthèse mémoire ARCTA avec comptage réel des points finis."""
    mode = detect_analysis_mode(df_clean)
    rows = []
    for trial_id, cols in group_concat_columns_by_trial(df_clean).items():
        y_col = pick_first(cols, "Y_")
        xg_col = pick_first(cols, "Xg_")
        a_col = pick_first(cols, "A_")
        y = coerce_numeric_series(df_clean[y_col]) if y_col else pd.Series(dtype=float)
        xg = coerce_numeric_series(df_clean[xg_col]) if xg_col else pd.Series(dtype=float)
        a = coerce_numeric_series(df_clean[a_col]) if a_col else pd.Series(dtype=float)
        y_arr = y.to_numpy(dtype=float) if len(y) else np.array([], dtype=float)
        xg_arr = xg.to_numpy(dtype=float) if len(xg) else np.array([], dtype=float)
        a_arr = a.to_numpy(dtype=float) if len(a) else np.array([], dtype=float)
        n_y = int(np.isfinite(y_arr).sum()) if len(y_arr) else 0
        n_xg = int(np.isfinite(xg_arr).sum()) if len(xg_arr) else 0
        n_pair = (
            int((np.isfinite(y_arr) & np.isfinite(xg_arr)).sum())
            if len(y_arr) and len(xg_arr)
            else n_y
        )
        rows.append({
            "Trial_ID": trial_id,
            "N_rows_dataframe": int(max(len(y_arr), len(xg_arr), len(a_arr))),
            "N_points_clean": n_pair,
            "N_points_Y_clean": n_y,
            "N_points_Xg_clean": n_xg,
            "Y_max": float(np.nanmax(y_arr)) if n_y else np.nan,
            "Xg_max": float(np.nanmax(xg_arr)) if n_xg else np.nan,
            "Aeff_min": float(np.nanmin(a_arr)) if len(a_arr) and np.isfinite(a_arr).any() else np.nan,
            "Aeff_max": float(np.nanmax(a_arr)) if len(a_arr) and np.isfinite(a_arr).any() else np.nan,
            "Angle_Basis_in_CONCAT_CLEAN": "A_eff = A_raw - A0_elastic_Y" if a_col else "NA",
            "Mode": mode,
            "Profile": profile,
        })
    return {"ARCTA_MEMORY_SUMMARY": pd.DataFrame(rows)}

def analyze_in_memory(
    df_clean: pd.DataFrame,
    constants: dict[str, Any],
    profile: str,
    progress: ProgressCallback | None = None,
    diag: dict[str, pd.DataFrame] | None = None,
    analysis_config: ArctaAnalysisConfig = DEFAULT_ARCTA_ANALYSIS_CONFIG,
) -> dict[str, pd.DataFrame]:
    """Service headless ARCTA : µ, POLY_FITS, COMPUTE, stats et autofrein."""
    cfg = get_profile_config(profile)
    mode = detect_analysis_mode(df_clean)
    sheets: dict[str, pd.DataFrame] = {}
    sheets.update(analyze_in_memory_summary(df_clean, profile))
    from arcta.notation import nomenclature_rows
    sheets["ARCTA_NOTATIONS_ISO"] = pd.DataFrame(nomenclature_rows())
    from .run_mechanics import corrected
    df_work, correction = corrected(df_clean, diag or {}, analysis_config.subtract_selflock)
    if analysis_config.subtract_selflock:
        sheets["ARCTA_SELFLOCK_CORRECTION"] = correction
        sheets["CONCAT_EFFECTIVE"] = df_work.copy()
    analysis_input = df_work

    if cfg.get("do_mu"):
        if progress:
            progress(48, "Calcul des coefficients de frottement K&K en mémoire…")
        try:
            df_mu = build_mu_df_from_clean(analysis_input, constants)
            sheet_mu = "CONCAT_CLEAN+µ_fine" if mode == "fine" else "CONCAT_CLEAN+µ_global"
            sheets[sheet_mu] = df_mu
            df_work = df_mu
        except Exception as exc:
            if constants.get("kk_model") or analysis_config.subtract_selflock:
                raise
            sheets["MU_ERRORS"] = pd.DataFrame([{"Error": str(exc)}])

    if cfg.get("do_polyfits"):
        if progress:
            progress(58, "Polynomisation en mémoire sur abscisses Y, Xg et A…")
        df_poly = build_polyfits_from_df(df_work, profile)
        sheets["POLY_FITS"] = df_poly
    else:
        df_poly = pd.DataFrame()

    if cfg.get("do_compute") and df_poly is not None and not df_poly.empty:
        if progress:
            progress(68, "Recalcul sur abscisses communes 200 points…")
        compute_sheets = build_compute_sheets_from_polyfits_df(
            df_poly,
            n_points=int(cfg.get("compute_n_points", 200)),
            analysis_config=analysis_config,
        )
        sheets.update(compute_sheets)
        if cfg.get("do_polyfits_stats"):
            if progress:
                progress(78, "Polynomisation des statistiques COMPUTE…")
            sheets["POLY_FITS_STATS"] = build_polyfits_stats_from_compute_sheets(
                compute_sheets,
                profile,
            )

    if cfg.get("do_autofrein"):
        if progress:
            progress(84, "Calcul autofrein : refit linéaire et comparaison DIAG…")
        try:
            sheets.update(
                build_autofrein_sheets_in_memory(
                    df_clean,
                    df_poly=None if analysis_config.subtract_selflock else df_poly,
                    diag=diag,
                )
            )
        except Exception as exc:
            sheets["AUTOFREIN_ERRORS"] = pd.DataFrame([{"Error": str(exc)}])

    return sheets