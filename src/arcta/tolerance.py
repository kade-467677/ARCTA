"""63F0: bilateral distribution-free tolerance, fixed central order ranks.

Pointwise across independent trials from the same continuous population.
This is not a simultaneous confidence band for an entire curve.
References: NIST prc264; EnvStats tolIntNpar, equations (1)-(8).
"""
from functools import lru_cache
import math

import numpy as np
import pandas as pd
from scipy.stats import beta


def _probability(value):
    value = float(value)
    if not math.isfinite(value) or not 0 < value < 1:
        raise ValueError("Proportion et confiance doivent être dans ]0 ; 1[.")
    return value


def _confidence(n, p, rank=1):
    return float(beta.sf(p, n - 2 * rank + 1, 2 * rank))


@lru_cache(maxsize=256)
def minimum_sample_size(p, confidence):
    """Smallest n with P{coverage([min,max]) >= p} >= confidence."""
    p, confidence = _probability(p), _probability(confidence)
    low, high = 1, 2
    while _confidence(high, p) < confidence:
        low, high = high, high * 2
        if high > 2**53:
            raise ValueError("Objectif trop extrême pour la précision numérique.")
    while high - low > 1:
        middle = (low + high) // 2
        if _confidence(middle, p) >= confidence:
            high = middle
        else:
            low = middle
    return high


@lru_cache(maxsize=4096)
def _rank_plan(n, p, confidence):
    required = minimum_sample_size(p, confidence)
    maximum = _confidence(n, p) if n >= 2 else 0.0
    if n < required:
        return None, maximum, required
    # Fixed symmetric ranks, depending ONLY on n, p and confidence.
    # Selecting the shortest observed interval would invalidate this confidence.
    low, high = 1, n // 2 + 1
    while high - low > 1:
        middle = (low + high) // 2
        if _confidence(n, p, middle) >= confidence:
            low = middle
        else:
            high = middle
    return low, maximum, required


def nonparametric_tolerance_interval(values, p=0.90, confidence=0.95):
    p, confidence = _probability(p), _probability(confidence)
    x = np.asarray(values, dtype=float).reshape(-1)
    x = np.sort(x[np.isfinite(x)])
    n = len(x)
    rank, maximum, required = _rank_plan(n, p, confidence)
    result = dict(
        n=n, low=np.nan, high=np.nan, order_low=np.nan,
        order_high=np.nan, confidence_actual=np.nan,
        confidence_max=maximum, min_n_required=required,
        status="NO_DATA" if n == 0 else "INSUFFICIENT_N",
    )
    if rank is not None:
        result.update(
            low=float(x[rank - 1]), high=float(x[n - rank]),
            order_low=rank, order_high=n - rank + 1,
            confidence_actual=_confidence(n, p, rank), status="OK",
        )
    return result


def apply_nonparametric_tolerance(df, trial_columns, eligible, config):
    """Apply the contract to raw pointwise values, never to fitted bounds."""
    records = []
    for values, allowed in zip(df[trial_columns].to_numpy(dtype=float), eligible):
        result = nonparametric_tolerance_interval(
            values, config.iso_tol_p_content, config.iso_tol_conf_level,
        )
        if not allowed:
            result.update(low=np.nan, high=np.nan, order_low=np.nan,
                          order_high=np.nan, confidence_actual=np.nan,
                          status="INSUFFICIENT_VALID")
        records.append(result)
    fields = {
        "LOW": "low", "HIGH": "high", "STATUS": "status",
        "CONF_ACTUAL": "confidence_actual", "CONF_MAX": "confidence_max",
        "ORDER_LOW": "order_low", "ORDER_HIGH": "order_high",
        "MIN_N_REQUIRED": "min_n_required",
    }
    for suffix, key in fields.items():
        df["STAT_TOL_NP_" + suffix] = [row[key] for row in records]
    selected = df["STAT_TOL_KIND"].eq("nonparam")
    for suffix in ("LOW", "HIGH"):
        df.loc[selected, "STAT_TOL_" + suffix] = df.loc[
            selected, "STAT_TOL_NP_" + suffix
        ]
    df["STAT_TOL_STATUS"] = "NOT_EVALUATED"
    df.loc[df["STAT_TOL_KIND"].eq("param"), "STAT_TOL_STATUS"] = "PARAMETRIC"
    df.loc[selected, "STAT_TOL_STATUS"] = df.loc[selected, "STAT_TOL_NP_STATUS"]
    return df


def unavailable_nonparametric(df):
    if not {"STAT_TOL_KIND", "STAT_TOL_NP_STATUS"}.issubset(df.columns):
        return df.iloc[:0]
    return df.loc[df["STAT_TOL_KIND"].eq("nonparam")
                  & df["STAT_TOL_NP_STATUS"].ne("OK")]


def tolerance_notice(df):
    from .tolerance_explanations import tolerance_details
    details = tolerance_details({"graphe": df}, warnings_only=True)
    if details.empty:
        return ""
    return "Tolérance : objectif non atteint ou calcul indisponible — voir explication sous le graphe."


def tolerance_warnings(sheets):
    from .tolerance_explanations import tolerance_details
    return tolerance_details(sheets, warnings_only=True)
