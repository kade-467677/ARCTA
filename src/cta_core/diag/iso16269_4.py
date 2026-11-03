from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def _scalar_baseline(
    values: np.ndarray,
    min_n: int,
    iqr_warn_k: float,
    iqr_fail_k: float,
) -> dict:
    x = np.asarray(values, dtype=float)
    finite = x[np.isfinite(x)]
    n = int(len(finite))

    if n < min_n:
        return {
            "N": n, "Median": np.nan, "MAD": np.nan, "Q1": np.nan, "Q3": np.nan, "IQR": np.nan,
            "Lower_Fence_Warn": np.nan, "Upper_Fence_Warn": np.nan,
            "Lower_Fence_Fail": np.nan, "Upper_Fence_Fail": np.nan,
            "Method": "ISO16269-4_ROBUST_SCALAR", "Method_Status": "TOO_FEW_VALUES",
        }

    med = float(np.nanmedian(finite))
    q1 = float(np.nanpercentile(finite, 25))
    q3 = float(np.nanpercentile(finite, 75))
    iqr = q3 - q1
    mad = float(np.nanmedian(np.abs(finite - med)))

    return {
        "N": n, "Median": med, "MAD": mad, "Q1": q1, "Q3": q3, "IQR": iqr,
        "Lower_Fence_Warn": float(q1 - iqr_warn_k * iqr),
        "Upper_Fence_Warn": float(q3 + iqr_warn_k * iqr),
        "Lower_Fence_Fail": float(q1 - iqr_fail_k * iqr),
        "Upper_Fence_Fail": float(q3 + iqr_fail_k * iqr),
        "Method": "ISO16269-4_ROBUST_SCALAR", "Method_Status": "OK",
    }


def _robust_z_value(v: float, med: float, mad: float, ref_values: np.ndarray) -> float:
    if not np.isfinite(v) or not np.isfinite(med):
        return np.nan
    if np.isfinite(mad) and mad > 0:
        return float(0.6745 * (v - med) / mad)

    vals = np.asarray(ref_values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if len(vals) > 1:
        s = float(np.nanstd(vals, ddof=1))
        if np.isfinite(s) and s > 0:
            return float((v - med) / s)

    return 0.0 if np.isclose(v, med, equal_nan=False) else np.nan


def build_iso16269_4_outliers(
    diag: dict[str, pd.DataFrame],
    scalar_specs: Sequence[tuple[str, str, str, str]],
    *,
    min_n: int,
    iqr_warn_k: float,
    iqr_fail_k: float,
    robust_z_warn: float,
    robust_z_fail: float,
) -> dict[str, pd.DataFrame]:
    """
    Détection robuste des scalaires DIAG.

    Aucun rejet automatique et aucune localisation UI.
    Tous les seuils et la liste des scalaires sont explicites.
    """
    rows = []

    for sheet_name, variable, description, unit in scalar_specs:
        df = diag.get(sheet_name, pd.DataFrame())
        if df is None or df.empty or "Trial_ID" not in df.columns or variable not in df.columns:
            continue

        work = df[["Trial_ID", variable]].copy()
        work["Trial_ID"] = work["Trial_ID"].astype(str)
        vals = pd.to_numeric(work[variable], errors="coerce").to_numpy(dtype=float)
        trial_list = work["Trial_ID"].astype(str).tolist()

        baseline = _scalar_baseline(vals, min_n, iqr_warn_k, iqr_fail_k)
        finite_vals = vals[np.isfinite(vals)]

        for tid, v in zip(trial_list, vals):
            if not np.isfinite(v):
                continue

            rz = _robust_z_value(v, baseline["Median"], baseline["MAD"], finite_vals)

            iqr_level = "OK"
            if np.isfinite(baseline["Lower_Fence_Fail"]) and (
                v < baseline["Lower_Fence_Fail"] or v > baseline["Upper_Fence_Fail"]
            ):
                iqr_level = "FAIL"
            elif np.isfinite(baseline["Lower_Fence_Warn"]) and (
                v < baseline["Lower_Fence_Warn"] or v > baseline["Upper_Fence_Warn"]
            ):
                iqr_level = "WARNING"

            rz_level = "OK"
            if np.isfinite(rz):
                if abs(rz) >= robust_z_fail:
                    rz_level = "FAIL"
                elif abs(rz) >= robust_z_warn:
                    rz_level = "WARNING"

            if "FAIL" in (iqr_level, rz_level):
                level = "FAIL"
            elif "WARNING" in (iqr_level, rz_level):
                level = "WARNING"
            else:
                level = "OK"

            direction = "HIGH" if np.isfinite(baseline["Median"]) and v > baseline["Median"] else "LOW"
            comment = "RAS" if level == "OK" else (
                f"{variable} {direction.lower()} vs campagne "
                f"(robust_z={rz:.3g} ; médiane={baseline['Median']:.4g})"
            )

            rows.append({
                "Trial_ID": tid,
                "Source_Sheet": sheet_name,
                "Variable": variable,
                "Description_FR": description,
                "Unit": unit,
                "Value": float(v),
                "N": baseline["N"],
                "Method": baseline["Method"],
                "Method_Status": baseline["Method_Status"],
                "Outlier_Flag": bool(level != "OK"),
                "Outlier_Level": level,
                "Direction": direction,
                "Robust_Z": rz,
                "Median": baseline["Median"],
                "MAD": baseline["MAD"],
                "Q1": baseline["Q1"],
                "Q3": baseline["Q3"],
                "IQR": baseline["IQR"],
                "Lower_Fence_Warn": baseline["Lower_Fence_Warn"],
                "Upper_Fence_Warn": baseline["Upper_Fence_Warn"],
                "Lower_Fence_Fail": baseline["Lower_Fence_Fail"],
                "Upper_Fence_Fail": baseline["Upper_Fence_Fail"],
                "IQR_Level": iqr_level,
                "Robust_Z_Level": rz_level,
                "Comment_FR": comment,
            })

    df_out = pd.DataFrame(rows)

    if df_out.empty:
        df_sum = pd.DataFrame(columns=[
            "Trial_ID", "ISO16269_4_Outlier_Count", "ISO16269_4_Warning_Count",
            "ISO16269_4_Fail_Count", "ISO16269_4_Max_Severity",
            "ISO16269_4_Main_Variables", "ISO16269_4_Comments_FR",
        ])
    else:
        rank = {"OK": 0, "WARNING": 1, "FAIL": 2}
        summary_rows = []

        for tid, group in df_out.groupby("Trial_ID", sort=False):
            flagged = group[group["Outlier_Level"].isin(["WARNING", "FAIL"])].copy()
            warn_count = int((flagged["Outlier_Level"] == "WARNING").sum())
            fail_count = int((flagged["Outlier_Level"] == "FAIL").sum())

            if flagged.empty:
                max_sev, main_vars, comments = "OK", "", "RAS"
            else:
                flagged["_rank"] = flagged["Outlier_Level"].map(rank).fillna(0)
                flagged = flagged.sort_values(["_rank", "Variable"], ascending=[False, True])
                max_sev = str(flagged.iloc[0]["Outlier_Level"])
                main_vars = "; ".join(flagged["Variable"].astype(str).head(6).tolist())
                comments = "; ".join(flagged["Comment_FR"].astype(str).head(4).tolist())

            summary_rows.append({
                "Trial_ID": str(tid),
                "ISO16269_4_Outlier_Count": int(len(flagged)),
                "ISO16269_4_Warning_Count": warn_count,
                "ISO16269_4_Fail_Count": fail_count,
                "ISO16269_4_Max_Severity": max_sev,
                "ISO16269_4_Main_Variables": main_vars,
                "ISO16269_4_Comments_FR": comments,
            })

        df_sum = pd.DataFrame(summary_rows)

    summary = diag.get("DIAG_SUMMARY", pd.DataFrame()).copy()

    if not summary.empty and "Trial_ID" in summary.columns and not df_sum.empty:
        summary["Trial_ID"] = summary["Trial_ID"].astype(str)
        df_sum["Trial_ID"] = df_sum["Trial_ID"].astype(str)
        summary = summary.merge(df_sum, on="Trial_ID", how="left")

        for col in ("ISO16269_4_Outlier_Count", "ISO16269_4_Warning_Count", "ISO16269_4_Fail_Count"):
            if col in summary.columns:
                summary[col] = pd.to_numeric(summary[col], errors="coerce").fillna(0).astype(int)

        for col in ("ISO16269_4_Max_Severity", "ISO16269_4_Main_Variables", "ISO16269_4_Comments_FR"):
            if col in summary.columns:
                summary[col] = summary[col].fillna("")

        if "Main_Flags" in summary.columns:
            mask = summary["ISO16269_4_Outlier_Count"].astype(int) > 0
            summary.loc[mask, "Main_Flags"] = summary.loc[mask, "Main_Flags"].astype(str).apply(
                lambda s: (s + ";ISO16269_4_OUTLIER").strip(";")
                if "ISO16269_4_OUTLIER" not in s else s
            )

        diag["DIAG_SUMMARY"] = summary

    diag["DIAG_ISO16269_4_OUTLIERS"] = df_out
    diag["DIAG_ISO16269_4_SUMMARY"] = df_sum
    return diag