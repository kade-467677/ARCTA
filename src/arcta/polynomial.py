from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _clean_xy_np(x, y):
    x = pd.to_numeric(pd.Series(x), errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(pd.Series(y), errors="coerce").to_numpy(dtype=float)
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    m = np.isfinite(x) & np.isfinite(y)
    return x[m], y[m]


def fit_best_poly_mem(
    x,
    y,
    r2_target: float = 0.999,
    max_deg: int = 6,
    min_points: int = 7,
) -> dict[str, Any]:
    x, y = _clean_xy_np(x, y)
    n = len(x)

    if n < max(min_points, 2):
        return {
            "degree": np.nan,
            "r2": np.nan,
            "n": n,
            "coeffs_0_to_6": [np.nan] * 7,
            "mae": np.nan,
            "medae": np.nan,
        }

    best = None

    with np.errstate(all="ignore"):
        for deg in range(0, max_deg + 1):
            if n < deg + 1:
                break

            try:
                pcoef = np.polyfit(x, y, deg=deg)
                yhat = np.polyval(pcoef, x)

                ss_res = float(np.sum((y - yhat) ** 2))
                ss_tot = float(np.sum((y - np.mean(y)) ** 2))
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

                resid = y - yhat
                coeffs = [np.nan] * 7

                # np.polyfit renvoie degré descendant ;
                # coeff0 attendu = terme constant.
                asc = list(pcoef[::-1])

                for i, v in enumerate(asc[:7]):
                    coeffs[i] = float(v)

                cand = {
                    "degree": deg,
                    "r2": r2,
                    "n": n,
                    "coeffs_0_to_6": coeffs,
                    "mae": float(np.nanmean(np.abs(resid))),
                    "medae": float(np.nanmedian(np.abs(resid))),
                }

                if (
                    best is None
                    or (
                        np.isfinite(r2)
                        and r2 > best.get("r2", -np.inf)
                    )
                ):
                    best = cand

                if np.isfinite(r2) and r2 >= r2_target:
                    best = cand
                    break

            except Exception:
                continue

    if best is None:
        return {
            "degree": np.nan,
            "r2": np.nan,
            "n": n,
            "coeffs_0_to_6": [np.nan] * 7,
            "mae": np.nan,
            "medae": np.nan,
        }

    return best


def poly_eval_from_coeffs(x, coeffs_0_to_6) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.zeros_like(x, dtype=float)

    for k, c in enumerate(coeffs_0_to_6):
        if np.isfinite(c):
            y += float(c) * (x ** k)

    return y


def compute_sheet_name_from_type(type_name: str) -> str:
    """
    Nommage compatible V4 pour les feuilles COMPUTE.

    Exemples :
      Y=f(Xg)  -> TEST_COMPUTE_YfXg
      Xg=f(Y)  -> TEST_COMPUTE_XgfY
      µg=f(Xg) -> µg_COMPUTE_fXg
      µh=f(Xh) -> µh_COMPUTE_fXh
      Y=f(A)   -> TEST_COMPUTE_YfA
    """
    out, inn = type_name.split("=f(")
    inn = inn.rstrip(")")

    if str(out).startswith("µ"):
        return f"{out}_COMPUTE_f{inn}"[:31]

    prefix = (
        "TEST"
        if out in ("Y", "Xg", "A", "Xh", "Xt")
        else out
    )

    return f"{prefix}_COMPUTE_{out}f{inn}"[:31]