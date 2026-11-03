from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from cta_core.parsing import coerce_numeric_series

from .columns import group_concat_columns_by_trial, pick_first


def _r2_linear(
    x: np.ndarray,
    y: np.ndarray,
    a: float,
    b: float,
) -> float:
    m = np.isfinite(x) & np.isfinite(y)

    if (
        int(np.sum(m)) < 2
        or not np.isfinite(a)
        or not np.isfinite(b)
    ):
        return np.nan

    yy = y[m]
    yhat = a * x[m] + b

    ss_res = float(
        np.sum((yy - yhat) ** 2)
    )

    ss_tot = float(
        np.sum(
            (yy - np.mean(yy)) ** 2
        )
    )

    return (
        1.0 - ss_res / ss_tot
        if ss_tot > 0
        else np.nan
    )


def linear_refit_autofrein_from_clean_df(
    df_clean: pd.DataFrame,
    y_low_ratio: float = 0.05,
    y_high_ratio: float = 0.10,
    min_points: int = 7,
) -> pd.DataFrame:
    """
    Refit autofrein :
        Xg = a * Y + b

    sur le segment initial de montée en tension.

    b = Xg extrapolé à Y=0, utilisé comme estimation
    du couple résiduel / autofrein.
    """
    rows = []
    groups = group_concat_columns_by_trial(
        df_clean
    )

    for trial_id, cols in groups.items():
        xg_col = pick_first(
            cols,
            "Xg_",
        )
        y_col = pick_first(
            cols,
            "Y_",
        )
        a_col = pick_first(
            cols,
            "A_",
        )

        if not (
            xg_col
            and y_col
        ):
            continue

        xg = coerce_numeric_series(
            df_clean[xg_col]
        ).to_numpy(dtype=float)

        y = coerce_numeric_series(
            df_clean[y_col]
        ).to_numpy(dtype=float)

        aeff = (
            coerce_numeric_series(
                df_clean[a_col]
            ).to_numpy(dtype=float)
            if a_col
            else np.full(
                len(y),
                np.nan,
            )
        )

        n = min(
            len(xg),
            len(y),
            len(aeff),
        )

        xg = xg[:n]
        y = y[:n]
        aeff = aeff[:n]

        m0 = (
            np.isfinite(xg)
            & np.isfinite(y)
            & (y >= 0)
        )

        if int(np.sum(m0)) < min_points:
            rows.append({
                "Trial_ID": trial_id,
                "Autofrein_Refit_Status":
                    "TOO_FEW_POINTS",
                "Autofrein_b_refit_Nm":
                    np.nan,
                "Autofrein_a_refit_Nm_per_N":
                    np.nan,
                "Autofrein_refit_R2":
                    np.nan,
                "N_refit":
                    int(np.sum(m0)),
            })
            continue

        ymax = float(
            np.nanmax(y[m0])
        )

        if (
            not np.isfinite(ymax)
            or ymax <= 0
        ):
            rows.append({
                "Trial_ID": trial_id,
                "Autofrein_Refit_Status":
                    "NO_POSITIVE_TENSION",
                "Autofrein_b_refit_Nm":
                    np.nan,
                "Autofrein_a_refit_Nm_per_N":
                    np.nan,
                "Autofrein_refit_R2":
                    np.nan,
                "N_refit": 0,
            })
            continue

        # Fenêtre nominale [5 % ; 10 %] Ymax.
        m = (
            m0
            & (
                y
                >= y_low_ratio
                * ymax
            )
            & (
                y
                <= y_high_ratio
                * ymax
            )
        )

        window_kind = (
            "nominal_5_10pct"
        )

        # Fallback historique [3 % ; 15 %].
        if int(np.sum(m)) < min_points:
            m = (
                m0
                & (y >= 0.03 * ymax)
                & (y <= 0.15 * ymax)
            )
            window_kind = (
                "fallback_3_15pct"
            )

        if int(np.sum(m)) < min_points:
            rows.append({
                "Trial_ID":
                    trial_id,
                "Autofrein_Refit_Status":
                    "TOO_FEW_POINTS_IN_WINDOW",
                "Autofrein_Window_Kind":
                    window_kind,
                "Ymax_N":
                    ymax,
                "Autofrein_b_refit_Nm":
                    np.nan,
                "Autofrein_a_refit_Nm_per_N":
                    np.nan,
                "Autofrein_refit_R2":
                    np.nan,
                "N_refit":
                    int(np.sum(m)),
            })
            continue

        xx = y[m]
        yy = xg[m]

        try:
            a_fit, b_fit = np.polyfit(
                xx,
                yy,
                deg=1,
            )

            r2 = _r2_linear(
                xx,
                yy,
                a_fit,
                b_fit,
            )

        except Exception:
            a_fit = np.nan
            b_fit = np.nan
            r2 = np.nan

        rows.append({
            "Trial_ID":
                trial_id,
            "Autofrein_Refit_Status":
                (
                    "OK"
                    if np.isfinite(b_fit)
                    else "FIT_FAILED"
                ),
            "Autofrein_Window_Kind":
                window_kind,
            "Ymax_N":
                ymax,
            "Y_low_refit_N":
                float(
                    y_low_ratio
                    * ymax
                ),
            "Y_high_refit_N":
                float(
                    y_high_ratio
                    * ymax
                ),
            "Aeff_refit_start_deg":
                (
                    float(
                        np.nanmin(aeff[m])
                    )
                    if np.isfinite(
                        aeff[m]
                    ).any()
                    else np.nan
                ),
            "Aeff_refit_end_deg":
                (
                    float(
                        np.nanmax(aeff[m])
                    )
                    if np.isfinite(
                        aeff[m]
                    ).any()
                    else np.nan
                ),
            "Autofrein_a_refit_Nm_per_N":
                (
                    float(a_fit)
                    if np.isfinite(a_fit)
                    else np.nan
                ),
            "Autofrein_b_refit_Nm":
                (
                    float(b_fit)
                    if np.isfinite(b_fit)
                    else np.nan
                ),
            "Autofrein_refit_R2":
                (
                    float(r2)
                    if np.isfinite(r2)
                    else np.nan
                ),
            "N_refit":
                int(np.sum(m)),
            "Xg_mean_window_Nm":
                float(
                    np.nanmean(yy)
                ),
            "Xg_median_window_Nm":
                float(
                    np.nanmedian(yy)
                ),
        })

    return pd.DataFrame(rows)


def build_autofrein_comparison(
    df_autofrein_refit: pd.DataFrame,
    df_poly: Optional[pd.DataFrame] = None,
    diag: Optional[
        Dict[str, pd.DataFrame]
    ] = None,
    tol_abs_nm: float = 0.50,
    tol_rel: float = 0.15,
) -> pd.DataFrame:
    """
    Compare l'autofrein issu du refit linéaire avec
    la mesure DIAG pré-A0.

    df_poly est conservé dans la signature pour
    compatibilité avec l'API V5 actuelle.
    """
    _ = df_poly

    if (
        df_autofrein_refit is None
        or df_autofrein_refit.empty
    ):
        return pd.DataFrame()

    comp = (
        df_autofrein_refit.copy()
    )

    if (
        diag is not None
        and isinstance(
            diag.get(
                "DIAG_AUTOFREIN"
            ),
            pd.DataFrame,
        )
    ):
        d = diag[
            "DIAG_AUTOFREIN"
        ].copy()

        keep = [
            col
            for col in [
                "Trial_ID",
                "Autofrein_Xg_preA0_med",
                "Autofrein_Xg_preA0_mean",
                "Autofrein_Xt_preA0_med",
                "Autofrein_Xg_minus_Xt_preA0_med",
                "N_points_autofrein_preA0",
                "Aeff_autofrein_start",
                "Aeff_autofrein_end",
                "Autofrein_Window_Mode",
            ]
            if col in d.columns
        ]

        if keep:
            comp = comp.merge(
                d[keep],
                on="Trial_ID",
                how="left",
            )

    def _delta(a, b):
        a = pd.to_numeric(
            a,
            errors="coerce",
        )
        b = pd.to_numeric(
            b,
            errors="coerce",
        )
        return a - b

    if (
        "Autofrein_Xg_preA0_med"
        in comp.columns
    ):
        comp[
            "Delta_refit_minus_DIAG_preA0_Nm"
        ] = _delta(
            comp[
                "Autofrein_b_refit_Nm"
            ],
            comp[
                "Autofrein_Xg_preA0_med"
            ],
        )

        denom = np.maximum(
            np.abs(
                pd.to_numeric(
                    comp[
                        "Autofrein_b_refit_Nm"
                    ],
                    errors="coerce",
                )
            ),
            np.abs(
                pd.to_numeric(
                    comp[
                        "Autofrein_Xg_preA0_med"
                    ],
                    errors="coerce",
                )
            ),
        )

        comp[
            "Delta_refit_minus_DIAG_preA0_rel"
        ] = (
            comp[
                "Delta_refit_minus_DIAG_preA0_Nm"
            ]
            / denom.replace(
                0,
                np.nan,
            )
        )

    flags = []

    for _, row in comp.iterrows():
        refit = row.get(
            "Autofrein_b_refit_Nm",
            np.nan,
        )

        diag_value = row.get(
            "Autofrein_Xg_preA0_med",
            np.nan,
        )

        if not (
            np.isfinite(refit)
            and np.isfinite(diag_value)
        ):
            flags.append(
                "NO_DIAG_COMPARISON"
            )
            continue

        delta = abs(
            float(refit)
            - float(diag_value)
        )

        tolerance = max(
            float(tol_abs_nm),
            float(tol_rel)
            * max(
                abs(float(refit)),
                abs(float(diag_value)),
            ),
        )

        flags.append(
            "OK"
            if delta <= tolerance
            else "WARNING"
        )

    comp[
        "Autofrein_Compatibility_Flag"
    ] = flags

    comp[
        "Autofrein_Compatibility_Tol_abs_Nm"
    ] = float(tol_abs_nm)

    comp[
        "Autofrein_Compatibility_Tol_rel"
    ] = float(tol_rel)

    return comp


def build_autofrein_sheets_in_memory(
    df_clean: pd.DataFrame,
    df_poly: Optional[
        pd.DataFrame
    ] = None,
    diag: Optional[
        Dict[str, pd.DataFrame]
    ] = None,
) -> Dict[str, pd.DataFrame]:
    df_refit = (
        linear_refit_autofrein_from_clean_df(
            df_clean
        )
    )

    df_comp = (
        build_autofrein_comparison(
            df_refit,
            df_poly=df_poly,
            diag=diag,
        )
    )

    return {
        "SELF_LOCK_REFIT":
            df_refit,
        "AUTOFREIN_COMPARISON":
            df_comp,
    }