from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

from .analysis_config import ArctaAnalysisConfig, DEFAULT_ARCTA_ANALYSIS_CONFIG
from .tolerance import apply_nonparametric_tolerance


@lru_cache(maxsize=4096)
def iso16269_k_bilateral_parametric(
    n: int,
    p: float,
    conf: float,
    m: int = 1,
    n_gl: int = 24,
) -> float:
    if n < 2:
        return float("nan")
    f = m * (n - 1)
    z_p = stats.norm.ppf((1.0 + p) / 2.0)
    x, w = special.roots_legendre(n_gl)
    t = 0.5 * (x + 1.0)
    w = 0.5 * w
    chi2 = stats.chi2(df=f)
    u_nodes = chi2.ppf(t)
    B_nodes = np.sqrt(u_nodes / f)
    inv_sqrt_n = 1.0 / math.sqrt(n)

    def zmax_for(B: float, k: float) -> float:
        if (2.0 * stats.norm.cdf(k * B) - 1.0) < p:
            return 0.0

        def g(z):
            return (
                stats.norm.cdf(z * inv_sqrt_n + k * B)
                - stats.norm.cdf(z * inv_sqrt_n - k * B)
                - p
            )

        hi = 6.0
        while g(hi) > 0.0 and hi < 1e4:
            hi *= 2.0
        try:
            return float(optimize.brentq(g, 0.0, hi, maxiter=60))
        except Exception:
            return hi

    def confidence_of_k(k: float) -> float:
        return float(sum(
            wi * (2.0 * stats.norm.cdf(zmax_for(float(B), k)) - 1.0)
            for wi, B in zip(w, B_nodes)
        ))

    lo = z_p
    hi = max(z_p * 6.0, 2.5)
    while confidence_of_k(hi) < conf and hi < 200:
        hi *= 1.4
    if confidence_of_k(lo) >= conf:
        return float(lo)
    return float(
        optimize.brentq(
            lambda kk: confidence_of_k(kk) - conf,
            lo,
            hi,
            maxiter=60,
        )
    )


def iso16269_7_median_ci(
    vals: np.ndarray,
    conf: float | None = None,
) -> dict:
    """
    Intervalle de confiance non paramétrique de la médiane selon une
    approche par statistiques d'ordre / inversion du test des signes.
    """
    if conf is None:
        conf = DEFAULT_ARCTA_ANALYSIS_CONFIG.iso_median_conf_level

    x = np.asarray(vals, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)

    if n == 0:
        return {
            "low": np.nan,
            "high": np.nan,
            "conf_target": float(conf),
            "conf_actual": np.nan,
            "order_low": np.nan,
            "order_high": np.nan,
            "status": "NO_DATA",
            "method": "ISO16269-7_order_stats_exact",
        }

    xs = np.sort(x)
    candidates = []
    max_k = (n + 1) // 2

    for k in range(1, max_k + 1):
        low_idx = k - 1
        high_idx = n - k
        if low_idx > high_idx:
            continue

        cov = 1.0 - 2.0 * float(stats.binom.cdf(k - 1, n, 0.5))
        width = float(xs[high_idx] - xs[low_idx])

        candidates.append({
            "k": k,
            "low": float(xs[low_idx]),
            "high": float(xs[high_idx]),
            "conf_actual": cov,
            "order_low": int(k),
            "order_high": int(n - k + 1),
            "width": width,
        })

    if not candidates:
        return {
            "low": np.nan,
            "high": np.nan,
            "conf_target": float(conf),
            "conf_actual": np.nan,
            "order_low": np.nan,
            "order_high": np.nan,
            "status": "NO_INTERVAL",
            "method": "ISO16269-7_order_stats_exact",
        }

    feasible = [
        c
        for c in candidates
        if np.isfinite(c["conf_actual"]) and c["conf_actual"] >= conf
    ]

    if feasible:
        chosen = min(feasible, key=lambda c: (c["width"], -c["k"]))
        status = "OK"
    else:
        chosen = max(
            candidates,
            key=lambda c: (c["conf_actual"], -c["width"]),
        )
        status = "UNDER_TARGET"

    return {
        "low": chosen["low"],
        "high": chosen["high"],
        "conf_target": float(conf),
        "conf_actual": float(chosen["conf_actual"]),
        "order_low": int(chosen["order_low"]),
        "order_high": int(chosen["order_high"]),
        "status": status,
        "method": "ISO16269-7_order_stats_exact",
    }


def append_stats_columns(
    df_compute: pd.DataFrame,
    essai_cols: list[str],
    analysis_config: ArctaAnalysisConfig = DEFAULT_ARCTA_ANALYSIS_CONFIG,
) -> pd.DataFrame:
    df = df_compute.copy()
    if not essai_cols:
        return df

    V = df[essai_cols].to_numpy(dtype=float)
    M = np.isfinite(V)
    Vn = np.where(M, V, np.nan)
    n_valid = M.sum(axis=1).astype(int)
    n_essais = len(essai_cols)
    min_required = max(1, int(np.ceil(0.5 * n_essais)))
    eligible = n_valid >= min_required

    df[""] = np.nan
    df["STAT_N"] = n_valid
    df["STAT_MEAN"] = np.nanmean(Vn, axis=1)
    df["STAT_MEDIAN"] = np.nanmedian(Vn, axis=1)
    df["STAT_MIN"] = np.nanmin(Vn, axis=1)
    df["STAT_MAX"] = np.nanmax(Vn, axis=1)

    std_values = np.full(len(df), np.nan)
    std_mask = n_valid >= 2
    if np.any(std_mask):
        std_values[std_mask] = np.nanstd(
            Vn[std_mask],
            axis=1,
            ddof=1,
        )
    df["STAT_STD"] = std_values

    q1 = np.nanpercentile(Vn, 25, axis=1)
    q3 = np.nanpercentile(Vn, 75, axis=1)
    df["STAT_Q1"] = q1
    df["STAT_Q3"] = q3
    df["STAT_IQR"] = q3 - q1
    df["STAT_MAD"] = np.nanmedian(
        np.abs(Vn - df["STAT_MEDIAN"].to_numpy()[:, None]),
        axis=1,
    )
    df["STAT_MEAN_PLUS_2S"] = df["STAT_MEAN"] + 2.0 * df["STAT_STD"]
    df["STAT_MEAN_MINUS_2S"] = df["STAT_MEAN"] - 2.0 * df["STAT_STD"]

    ci_low = np.full(len(df), np.nan)
    ci_high = np.full(len(df), np.nan)
    median_ci_low = np.full(len(df), np.nan)
    median_ci_high = np.full(len(df), np.nan)
    median_ci_conf_actual = np.full(len(df), np.nan)
    median_ci_order_low = np.full(len(df), np.nan)
    median_ci_order_high = np.full(len(df), np.nan)
    median_ci_status = np.full(len(df), "", dtype=object)
    median_ci_method = np.full(len(df), "", dtype=object)
    tol_kind = np.full(len(df), "", dtype=object)
    tol_low = np.full(len(df), np.nan)
    tol_high = np.full(len(df), np.nan)
    tol_param_low = np.full(len(df), np.nan)
    tol_param_high = np.full(len(df), np.nan)
    tol_np_low = np.full(len(df), np.nan)
    tol_np_high = np.full(len(df), np.nan)
    shapiro_p = np.full(len(df), np.nan)

    for i in np.flatnonzero(eligible):
        vals = Vn[i, :]
        vals = vals[np.isfinite(vals)]
        n = len(vals)

        if n < 2:
            continue

        s = float(np.nanstd(vals, ddof=1))
        mean = float(np.nanmean(vals))

        if np.isfinite(s) and s > 0:
            tcrit = float(stats.t.ppf((1.0 + analysis_config.mean_ci_conf_level) / 2.0, df=n - 1))
            half = tcrit * s / math.sqrt(n)
            ci_low[i] = mean - half
            ci_high[i] = mean + half

            try:
                k = iso16269_k_bilateral_parametric(
                    n,
                    analysis_config.iso_tol_p_content,
                    analysis_config.iso_tol_conf_level,
                )
                tol_param_low[i] = mean - k * s
                tol_param_high[i] = mean + k * s
            except Exception:
                pass

        try:
            med_ci = iso16269_7_median_ci(
                vals,
                conf=analysis_config.iso_median_conf_level,
            )
            median_ci_low[i] = med_ci["low"]
            median_ci_high[i] = med_ci["high"]
            median_ci_conf_actual[i] = med_ci["conf_actual"]
            median_ci_order_low[i] = med_ci["order_low"]
            median_ci_order_high[i] = med_ci["order_high"]
            median_ci_status[i] = med_ci["status"]
            median_ci_method[i] = med_ci["method"]
        except Exception:
            pass

        try:
            if n >= analysis_config.normality_min_n:
                shapiro_p[i] = float(stats.shapiro(vals[:5000])[1])
        except Exception:
            pass

        use_param = (
            np.isfinite(shapiro_p[i])
            and shapiro_p[i] >= analysis_config.normality_alpha
            and np.isfinite(tol_param_low[i])
        )

        if use_param:
            tol_kind[i] = "param"
            tol_low[i] = tol_param_low[i]
            tol_high[i] = tol_param_high[i]
        else:
            tol_kind[i] = "nonparam"
            tol_low[i] = tol_np_low[i]
            tol_high[i] = tol_np_high[i]

    # CI95 est un identifiant historique ; le niveau effectif est archivé.
    df["STAT_MEAN_CI_CONF_TARGET"] = analysis_config.mean_ci_conf_level
    df["STAT_MEAN_CI_LOW"] = ci_low
    df["STAT_MEAN_CI_HIGH"] = ci_high
    df["STAT_MEDIAN_CI_LOW"] = median_ci_low
    df["STAT_MEDIAN_CI_HIGH"] = median_ci_high
    df["STAT_MEDIAN_CI_CONF_TARGET"] = analysis_config.iso_median_conf_level
    df["STAT_MEDIAN_CI_CONF_ACTUAL"] = median_ci_conf_actual
    df["STAT_MEDIAN_CI_ORDER_LOW"] = median_ci_order_low
    df["STAT_MEDIAN_CI_ORDER_HIGH"] = median_ci_order_high
    df["STAT_MEDIAN_CI_STATUS"] = median_ci_status
    df["STAT_MEDIAN_CI_METHOD"] = median_ci_method
    df["STAT_SHAPIRO_P"] = shapiro_p
    df["STAT_TOL_KIND"] = tol_kind
    df["STAT_TOL_LOW"] = tol_low
    df["STAT_TOL_HIGH"] = tol_high
    df["STAT_TOL_PARAM_LOW"] = tol_param_low
    df["STAT_TOL_PARAM_HIGH"] = tol_param_high
    df["STAT_TOL_NP_LOW"] = tol_np_low
    df["STAT_TOL_NP_HIGH"] = tol_np_high
    df["STAT_TOL_P"] = analysis_config.iso_tol_p_content
    df["STAT_TOL_CONF"] = analysis_config.iso_tol_conf_level
    from .tolerance_explanations import annotate_tolerance
    df = apply_nonparametric_tolerance(df, essai_cols, eligible, analysis_config)
    return annotate_tolerance(df, analysis_config, n_essais, eligible)

# 64G3A_MEAN_CI_NAMES
