from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .analysis_config import ArctaAnalysisConfig, DEFAULT_ARCTA_ANALYSIS_CONFIG
from .columns import group_concat_columns_by_trial, var_col_for_trial
from .polynomial import (
    _clean_xy_np,
    compute_sheet_name_from_type,
    fit_best_poly_mem,
    poly_eval_from_coeffs,
)
from .profiles import get_profile_config
from .statistics import append_stats_columns


def build_polyfits_from_df(
    df_data: pd.DataFrame,
    profile: str,
) -> pd.DataFrame:
    cfg = get_profile_config(profile)
    max_deg = int(cfg.get("max_deg", 6))
    r2_target = float(cfg.get("r2_target", 0.999))
    rows = []

    groups = group_concat_columns_by_trial(df_data)

    # Abscisses communes futures Y, Xg, A.
    input_vars = ["Y", "Xg", "A"]
    output_vars = [
        "Y",
        "Xg",
        "Xh",
        "Xt",
        "A",
        "µg",
        "µh",
        "µt",
    ]

    for trial_id, cols in groups.items():
        colmap = {
            var: var_col_for_trial(cols, var)
            for var in output_vars
        }

        for xvar in input_vars:
            xcol = colmap.get(xvar)

            if not xcol:
                continue

            for yvar in output_vars:
                if yvar == xvar:
                    continue

                ycol = colmap.get(yvar)

                if not ycol:
                    continue

                x, y = _clean_xy_np(
                    df_data[xcol],
                    df_data[ycol],
                )

                if len(x) < 7:
                    continue

                xmin = float(np.nanmin(x))
                xmax = float(np.nanmax(x))

                if (
                    not np.isfinite(xmin)
                    or not np.isfinite(xmax)
                    or xmax <= xmin
                ):
                    continue

                res = fit_best_poly_mem(
                    x,
                    y,
                    r2_target=r2_target,
                    max_deg=max_deg,
                    min_points=7,
                )

                row = {
                    "Essai": trial_id,
                    "Type": f"{yvar}=f({xvar})",
                    "X_var": xvar,
                    "Y_var": yvar,
                    "X_col": xcol,
                    "Y_col": ycol,
                    "X_min": xmin,
                    "X_max": xmax,
                    "R2": res["r2"],
                    "Degree": res["degree"],
                    "N": res["n"],
                    "Mean_AE": res.get("mae", np.nan),
                    "Med_AE": res.get("medae", np.nan),
                }

                for k, c in enumerate(
                    res["coeffs_0_to_6"]
                ):
                    row[f"coeff{k}"] = c

                rows.append(row)

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values(["Type", "Essai"])
        .reset_index(drop=True)
    )


def build_compute_sheets_from_polyfits_df(
    df_poly: pd.DataFrame,
    n_points: int = 200,
    analysis_config: ArctaAnalysisConfig = DEFAULT_ARCTA_ANALYSIS_CONFIG,
) -> Dict[str, pd.DataFrame]:
    sheets: Dict[str, pd.DataFrame] = {}

    if df_poly is None or df_poly.empty:
        return sheets

    for typ, dfp in df_poly.groupby("Type"):
        xmin_i = pd.to_numeric(
            dfp["X_min"],
            errors="coerce",
        ).max()

        xmax_i = pd.to_numeric(
            dfp["X_max"],
            errors="coerce",
        ).min()

        # Si l'intersection stricte est vide : fallback union historique.
        if (
            not np.isfinite(xmin_i)
            or not np.isfinite(xmax_i)
            or xmax_i <= xmin_i
        ):
            xmin_i = pd.to_numeric(
                dfp["X_min"],
                errors="coerce",
            ).min()

            xmax_i = pd.to_numeric(
                dfp["X_max"],
                errors="coerce",
            ).max()

        if (
            not np.isfinite(xmin_i)
            or not np.isfinite(xmax_i)
            or xmax_i <= xmin_i
        ):
            continue

        grid = np.linspace(
            float(xmin_i),
            float(xmax_i),
            int(n_points),
        )

        dfc = pd.DataFrame({
            "Abscisse": grid,
        })

        essai_cols = []

        for _, row in dfp.iterrows():
            essai = str(row["Essai"])

            coeffs = [
                pd.to_numeric(
                    pd.Series([
                        row.get(f"coeff{k}")
                    ]),
                    errors="coerce",
                ).iloc[0]
                for k in range(7)
            ]

            dfc[essai] = poly_eval_from_coeffs(
                grid,
                coeffs,
            )

            essai_cols.append(essai)

        dfc = append_stats_columns(
            dfc,
            essai_cols,
            analysis_config=analysis_config,
        )

        sheets[
            compute_sheet_name_from_type(str(typ))
        ] = dfc

    return sheets




def _finite_segments(x, y):
    """64I1 : découpe (x, y) en segments contigus à valeurs finies.

    Une position non finie interrompt le segment courant ; aucune
    interpolation n'est jamais faite à travers la zone indisponible.
    Retourne une liste de couples (x_seg, y_seg) finis et contigus.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    mask = np.isfinite(x) & np.isfinite(y)
    segments = []
    start = None
    for index in range(n + 1):
        active = index < n and bool(mask[index])
        if active and start is None:
            start = index
        elif not active and start is not None:
            segments.append((x[start:index], y[start:index]))
            start = None
    return segments

def build_polyfits_stats_from_compute_sheets(
    compute_sheets: Dict[str, pd.DataFrame],
    profile: str,
) -> pd.DataFrame:
    cfg = get_profile_config(profile)
    rows = []

    for sheet, dfc in compute_sheets.items():
        if (
            dfc is None
            or dfc.empty
            or "Abscisse" not in dfc.columns
        ):
            continue

        x = pd.to_numeric(
            dfc["Abscisse"],
            errors="coerce",
        ).to_numpy(dtype=float)

        # Toutes les colonnes STAT numériques deviennent
        # des courbes statistiques polynomisées.
        stat_cols = [
            col
            for col in dfc.columns
            if str(col).startswith("STAT_")
        ]

        for col in stat_cols:
            if str(col) in {"STAT_TOL_KIND", "STAT_MEAN_CI_CONF_TARGET"} or str(col).startswith("STAT_TOL_AUDIT_"):
                continue

            # 63F0: audit metadata are not physical curves.
            if str(col).startswith("STAT_TOL_NP_") and col not in {
                "STAT_TOL_NP_LOW", "STAT_TOL_NP_HIGH",
            }:
                continue

            y = pd.to_numeric(
                dfc[col],
                errors="coerce",
            ).to_numpy(dtype=float)

            # 64I1 : tolérances ISO polynomisées par segments de validité.
            # Une zone indisponible interrompt le segment ; jamais de fit à
            # travers elle. Les autres statistiques restent des courbes complètes.
            is_tol = str(col).startswith("STAT_TOL_") and str(col).endswith(("_LOW", "_HIGH"))

            if is_tol:
                segments = _finite_segments(x, y)
            else:
                finite_mask = np.isfinite(y)
                if not finite_mask.any():
                    continue
                segments = [(x[finite_mask], y[finite_mask])]

            for segment_index, (xs_seg, ys_seg) in enumerate(segments, start=1):
                if len(xs_seg) < 7:
                    continue

                res = fit_best_poly_mem(
                    xs_seg,
                    ys_seg,
                    r2_target=float(
                        cfg.get("r2_target", 0.999)
                    ),
                    max_deg=int(
                        cfg.get("max_deg", 6)
                    ),
                    min_points=7,
                )

                row = {
                    "Compute_Sheet": sheet,
                    "Type": sheet.replace(
                        "_COMPUTE_",
                        "_",
                    ),
                    "Stat": str(col).replace(
                        "STAT_",
                        "",
                    ),
                    "X_min": float(np.nanmin(xs_seg)),
                    "X_max": float(np.nanmax(xs_seg)),
                    "R2": res["r2"],
                    "Degree": res["degree"],
                    "N": res["n"],
                }

                if is_tol:
                    # Colonne technique S : identité du segment de validité,
                    # en bout de ligne. Absente = courbe complète (héritage).
                    row["S"] = segment_index

                for k, value in enumerate(
                    res["coeffs_0_to_6"]
                ):
                    row[f"coeff{k}"] = value

                rows.append(row)

    return pd.DataFrame(rows)
