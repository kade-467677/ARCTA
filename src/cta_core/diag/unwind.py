from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .primitives import first_consecutive, rolling_median


def _dead_travel_defaults() -> dict[str, Any]:
    return {
        "Reverse_Amax_Aeff_deg": np.nan,
        "Reverse_Amax_idx": np.nan,
        "DeadTravel_Found": False,
        "DeadTravel_End_Trigger": "NA",
        "DeadTravel_Start_Aeff_deg": np.nan,
        "DeadTravel_Start_idx": np.nan,
        "DeadTravel_End_Aeff_deg": np.nan,
        "DeadTravel_End_idx": np.nan,
        "DeadTravel_DeltaA_deg": np.nan,
        "DeadTravel_N_points": 0,
        "Reverse_Pickup_Aeff_deg": np.nan,
        "Reverse_Pickup_idx": np.nan,
        "Effective_Loosening_Aeff_deg": np.nan,
        "Effective_Loosening_idx": np.nan,
        "Torsion_Release_Xt_Zero_Aeff_deg": np.nan,
        "Torsion_Release_Xt_Zero_idx": np.nan,
        "Residual_Thread_Torque_Mean_Nm": np.nan,
        "Residual_Thread_Torque_Median_Nm": np.nan,
        "Residual_Thread_Torque_Std_Nm": np.nan,
        "Residual_Torsion_Torque_Abs_Nm": np.nan,
        "Residual_Thread_Torque_Evaluable": False,
        "DeadTravel_Xg_RMS_Nm": np.nan,
        "DeadTravel_Balance_RMS_Nm": np.nan,
        "DeadTravel_Balance_Rel": np.nan,
        "DeadTravel_Preload_Delta_Rel": np.nan,
        "Residual_Torsion_Diameter_mm": np.nan,
        "Residual_Torsion_Diameter_Source": "",
        "Residual_Torsional_Stress_Nominal_MPa": np.nan,
        "Residual_Torsional_Stress_Evaluable": False,
        "DeadTravel_Quality_Flag": "NOT_FOUND",
    }


def _first_stable_index(mask: np.ndarray, start: int, consecutive: int) -> int | None:
    if start >= len(mask):
        return None
    relative = first_consecutive(mask[start:], max(1, int(consecutive)))
    return None if relative is None else int(start + relative)


def _event_angle(values: np.ndarray, index: int | None) -> float:
    if index is None or index < 0 or index >= len(values):
        return np.nan
    return float(values[index]) if np.isfinite(values[index]) else np.nan


def _compute_dead_travel_indicators(
    A: np.ndarray,
    Y: np.ndarray,
    signals: Mapping[str, Any],
    pre: Mapping[str, Any],
    cfg: Mapping[str, Any],
    *,
    idx_amax: int,
) -> dict[str, Any]:
    """Caractérise la course morte réelle après inversion (jalon 63E2)."""
    out = _dead_travel_defaults()
    out["Reverse_Amax_Aeff_deg"] = _event_angle(A, idx_amax)
    out["Reverse_Amax_idx"] = int(idx_amax)

    Xg_raw = signals.get("Xg")
    Xt_raw = signals.get("Xt")
    Xh_raw = signals.get("Xh")
    if Xg_raw is None:
        out["DeadTravel_Quality_Flag"] = "MISSING_XG"
        return out

    Xg = np.asarray(Xg_raw, dtype=float)
    Xt = np.asarray(Xt_raw, dtype=float) if Xt_raw is not None else None
    Xh = np.asarray(Xh_raw, dtype=float) if Xh_raw is not None else None
    n = min(len(A), len(Y), len(Xg))
    if Xt is not None:
        n = min(n, len(Xt))
    if Xh is not None:
        n = min(n, len(Xh))
    min_points = max(1, int(cfg.get("unwind_min_points", 3)))
    if n <= idx_amax + min_points:
        return out

    A = A[:n]
    Y = Y[:n]
    Xg = Xg[:n]
    if Xt is not None:
        Xt = Xt[:n]
    if Xh is not None:
        Xh = Xh[:n]

    window = int(cfg.get("unwind_smooth_window", 7))
    Xg_s = rolling_median(Xg, window)
    Y_s = rolling_median(Y, window)
    Xt_s = rolling_median(Xt, window) if Xt is not None else None

    pre_peak = np.abs(Xg_s[:idx_amax + 1])
    pre_peak = pre_peak[np.isfinite(pre_peak)]
    xg_peak = float(np.max(pre_peak)) if len(pre_peak) else 0.0
    zero_tol = max(
        float(cfg.get("dead_travel_xg_zero_abs_Nm", 0.25)),
        float(cfg.get("dead_travel_xg_zero_ratio", 0.02)) * xg_peak,
    )
    reverse_threshold = max(
        float(cfg.get("reverse_pickup_xg_abs_Nm", 0.25)),
        float(cfg.get("reverse_pickup_xg_ratio", 0.02)) * xg_peak,
    )

    zero_mask = np.isfinite(Xg_s) & (np.abs(Xg_s) <= zero_tol)
    idx_start = _first_stable_index(
        zero_mask,
        idx_amax + 1,
        int(cfg.get("dead_travel_xg_zero_consecutive", 3)),
    )
    if idx_start is None:
        out["DeadTravel_Quality_Flag"] = "ZERO_TORQUE_NOT_FOUND"
        return out

    reverse_mask = np.isfinite(Xg_s) & (Xg_s <= -reverse_threshold)
    idx_reverse = _first_stable_index(
        reverse_mask,
        idx_start + min_points,
        int(cfg.get("reverse_pickup_consecutive", 3)),
    )
    if idx_reverse is not None:
        out["Reverse_Pickup_idx"] = idx_reverse
        out["Reverse_Pickup_Aeff_deg"] = _event_angle(A, idx_reverse)

    ymax = float(pre.get("Ymax", np.nan))
    if not np.isfinite(ymax) or ymax <= 0:
        finite_y = Y_s[np.isfinite(Y_s)]
        ymax = float(np.max(finite_y)) if len(finite_y) else np.nan
    idx_y_drop = None
    if np.isfinite(ymax) and ymax > 0:
        y_threshold = (
            1.0 - float(cfg.get("unwind_y_effective_drop_ratio", 0.005))
        ) * ymax
        y_mask = np.isfinite(Y_s) & (Y_s <= y_threshold)
        idx_y_drop = _first_stable_index(
            y_mask,
            idx_amax + 1,
            int(cfg.get("unwind_y_drop_consecutive", 3)),
        )
        if idx_y_drop is not None:
            out["Effective_Loosening_idx"] = idx_y_drop
            out["Effective_Loosening_Aeff_deg"] = _event_angle(A, idx_y_drop)

    idx_xt_zero = None
    if Xt_s is not None:
        xt_mask = (
            np.isfinite(Xt_s)
            & (Xt_s <= float(cfg.get("torsion_release_xt_zero_Nm", 0.0)))
        )
        idx_xt_zero = _first_stable_index(
            xt_mask,
            idx_start + min_points,
            int(cfg.get("torsion_release_consecutive", 3)),
        )
        if idx_xt_zero is not None:
            out["Torsion_Release_Xt_Zero_idx"] = idx_xt_zero
            out["Torsion_Release_Xt_Zero_Aeff_deg"] = _event_angle(A, idx_xt_zero)

    if idx_reverse is not None:
        idx_end = idx_reverse
        end_trigger = "REVERSE_XG_PICKUP"
    elif idx_y_drop is not None and idx_y_drop >= idx_start + min_points:
        idx_end = idx_y_drop
        end_trigger = "Y_EFFECTIVE_DROP_FALLBACK"
    else:
        out["DeadTravel_Quality_Flag"] = "END_NOT_FOUND"
        return out

    # Le point de reprise inverse est une transition et n'appartient pas au
    # plateau sur lequel Xt résiduel doit être estimé.
    plateau = slice(idx_start, idx_end)
    count = int(idx_end - idx_start)
    if count < min_points:
        out["DeadTravel_Quality_Flag"] = "TOO_FEW_PLATEAU_POINTS"
        return out

    out.update({
        "DeadTravel_Found": True,
        "DeadTravel_End_Trigger": end_trigger,
        "DeadTravel_Start_Aeff_deg": _event_angle(A, idx_start),
        "DeadTravel_Start_idx": idx_start,
        "DeadTravel_End_Aeff_deg": _event_angle(A, idx_end),
        "DeadTravel_End_idx": idx_end,
        "DeadTravel_DeltaA_deg": abs(
            _event_angle(A, idx_start) - _event_angle(A, idx_end)
        ),
        "DeadTravel_N_points": count,
    })

    xg_values = Xg[plateau]
    xg_values = xg_values[np.isfinite(xg_values)]
    if len(xg_values):
        out["DeadTravel_Xg_RMS_Nm"] = float(
            np.sqrt(np.mean(np.square(xg_values)))
        )

    y_values = Y[plateau]
    y_values = y_values[np.isfinite(y_values)]
    if len(y_values) >= 2 and abs(float(y_values[0])) > 1e-12:
        out["DeadTravel_Preload_Delta_Rel"] = float(
            (y_values[-1] - y_values[0]) / y_values[0]
        )

    quality: list[str] = []
    if end_trigger.endswith("FALLBACK"):
        quality.append("END_FALLBACK_Y_DROP")

    if Xt is None:
        quality.append("MISSING_XT")
    else:
        xt_values = Xt[plateau]
        xt_values = xt_values[np.isfinite(xt_values)]
        if len(xt_values) >= min_points:
            median = float(np.median(xt_values))
            out.update({
                "Residual_Thread_Torque_Mean_Nm": float(np.mean(xt_values)),
                "Residual_Thread_Torque_Median_Nm": median,
                "Residual_Thread_Torque_Std_Nm": float(np.std(xt_values)),
                "Residual_Torsion_Torque_Abs_Nm": abs(median),
                "Residual_Thread_Torque_Evaluable": True,
            })
        else:
            quality.append("MISSING_XT")

    if Xh is None or Xt is None:
        quality.append("MISSING_XH" if Xh is None else "")
    else:
        residual = Xg[plateau] - (Xh[plateau] + Xt[plateau])
        residual = residual[np.isfinite(residual)]
        if len(residual):
            balance_rms = float(np.sqrt(np.mean(np.square(residual))))
            out["DeadTravel_Balance_RMS_Nm"] = balance_rms
            xt_scale_values = np.abs(Xt[plateau])
            xt_scale_values = xt_scale_values[np.isfinite(xt_scale_values)]
            xt_scale = float(np.median(xt_scale_values)) if len(xt_scale_values) else np.nan
            if np.isfinite(xt_scale) and xt_scale > 1e-12:
                out["DeadTravel_Balance_Rel"] = balance_rms / xt_scale
                if out["DeadTravel_Balance_Rel"] > float(
                    cfg.get("dead_travel_balance_warn_ratio", 0.10)
                ):
                    quality.append("BALANCE_WARNING")

    preload_drift = out["DeadTravel_Preload_Delta_Rel"]
    if np.isfinite(preload_drift) and abs(preload_drift) > float(
        cfg.get("dead_travel_preload_drift_warn_ratio", 0.02)
    ):
        quality.append("PRELOAD_DRIFT")

    try:
        diameter = float(cfg.get("screw_torsion_diameter_mm", np.nan))
    except (TypeError, ValueError):
        diameter = np.nan
    if np.isfinite(diameter) and diameter > 0:
        out["Residual_Torsion_Diameter_mm"] = diameter
        out["Residual_Torsion_Diameter_Source"] = str(
            cfg.get("screw_torsion_diameter_source", "CONFIG_CANONICAL")
        )
        torque = out["Residual_Torsion_Torque_Abs_Nm"]
        if np.isfinite(torque):
            out["Residual_Torsional_Stress_Nominal_MPa"] = float(
                16000.0 * torque / (np.pi * diameter ** 3)
            )
            out["Residual_Torsional_Stress_Evaluable"] = True

    out["DeadTravel_Quality_Flag"] = ";".join(
        item for item in quality if item
    ) or "OK"
    return out


def compute_unwind_plateau_indicators(
    aeff,
    y,
    signals: Mapping[str, Any],
    pre: Mapping[str, Any],
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Indicateurs de desserrage / palier de dévrillage.

    Début du palier : Amax, début de rotation inverse.
    Fin nominale : premier Xg sous seuil après Amax.
    Fallback : première chute effective de tension après Amax.

    Toute la configuration est fournie explicitement via cfg.
    """
    out = {
        "Unwind_Plateau_Found": False,
        "Unwind_End_Trigger": "NA",
        "Unwind_Amax_eff": np.nan,
        "Unwind_Amax_idx": np.nan,
        "Unwind_Xg_negative_Aeff": np.nan,
        "Unwind_Xg_negative_idx": np.nan,
        "Unwind_Y_drop_Aeff": np.nan,
        "Unwind_Y_drop_idx": np.nan,
        "Unwind_Plateau_A_start_eff": np.nan,
        "Unwind_Plateau_A_end_eff": np.nan,
        "Unwind_Plateau_DeltaA_deg": np.nan,
        "Unwind_Plateau_Xt_mean_Nm": np.nan,
        "Unwind_Plateau_Xt_median_Nm": np.nan,
        "Unwind_Plateau_Xt_std_Nm": np.nan,
        "Unwind_Plateau_N_points": 0,
        "Unwind_Plateau_Y_start_N": np.nan,
        "Unwind_Plateau_Y_end_N": np.nan,
        "Unwind_Plateau_Y_delta_rel": np.nan,
        "Unwind_Plateau_Xg_start_Nm": np.nan,
        "Unwind_Plateau_Xg_end_Nm": np.nan,
        "Unwind_Plateau_Xt_start_Nm": np.nan,
        "Unwind_Plateau_Xt_end_Nm": np.nan,
    }
    out.update(_dead_travel_defaults())

    A = np.asarray(aeff, dtype=float)
    Y = np.asarray(y, dtype=float)

    Xg = signals.get("Xg")
    Xt = signals.get("Xt")
    Xg = np.asarray(Xg, dtype=float) if Xg is not None else None
    Xt = np.asarray(Xt, dtype=float) if Xt is not None else None

    n = min(len(A), len(Y))
    if Xg is not None:
        n = min(n, len(Xg))
    if Xt is not None:
        n = min(n, len(Xt))

    min_points = int(cfg.get("unwind_min_points", 3))
    if n < min_points:
        return out

    A, Y = A[:n], Y[:n]
    if Xg is not None:
        Xg = Xg[:n]
    if Xt is not None:
        Xt = Xt[:n]

    finite_A = np.isfinite(A)
    finite_Y = np.isfinite(Y)
    if int(np.sum(finite_A & finite_Y)) < min_points:
        return out

    # 1) Début de rotation inverse = Amax
    try:
        idx_amax = int(np.nanargmax(np.where(finite_A, A, np.nan)))
    except Exception:
        return out

    amax_eff = float(A[idx_amax])
    out["Unwind_Amax_eff"] = amax_eff
    out["Unwind_Amax_idx"] = idx_amax
    out["Unwind_Plateau_A_start_eff"] = amax_eff

    out.update(_compute_dead_travel_indicators(
        A,
        Y,
        signals,
        pre,
        cfg,
        idx_amax=idx_amax,
    ))

    # 2) Fin nominale : Xg sous seuil de manière stable après Amax
    idx_xg_neg = None
    if Xg is not None:
        win = int(cfg.get("unwind_smooth_window", 7))
        Xg_s = rolling_median(Xg, win)
        thr_xg = float(cfg.get("unwind_xg_negative_threshold_Nm", 0.0))

        post_mask = np.zeros(n, dtype=bool)
        post_mask[idx_amax + 1:] = (
            np.isfinite(Xg_s[idx_amax + 1:])
            & (Xg_s[idx_amax + 1:] < thr_xg)
        )

        j = first_consecutive(
            post_mask[idx_amax + 1:],
            int(cfg.get("unwind_xg_negative_consecutive", 3)),
        )
        if j is not None:
            idx_xg_neg = int(idx_amax + 1 + j)
            out["Unwind_Xg_negative_idx"] = idx_xg_neg
            out["Unwind_Xg_negative_Aeff"] = (
                float(A[idx_xg_neg]) if np.isfinite(A[idx_xg_neg]) else np.nan
            )

    # 3) Fallback : chute effective de tension
    idx_y_drop = None
    win = int(cfg.get("unwind_smooth_window", 7))
    Y_s = rolling_median(Y, win)

    ymax = float(pre.get("Ymax", np.nan))
    if not np.isfinite(ymax) or ymax <= 0:
        finite_y = Y_s[np.isfinite(Y_s)]
        ymax = float(np.nanmax(finite_y)) if len(finite_y) else np.nan

    if np.isfinite(ymax) and ymax > 0:
        y_drop_ratio = float(cfg.get("unwind_y_effective_drop_ratio", 0.005))
        y_thr = (1.0 - y_drop_ratio) * ymax

        post_y = np.zeros(n, dtype=bool)
        post_y[idx_amax + 1:] = (
            np.isfinite(Y_s[idx_amax + 1:])
            & (Y_s[idx_amax + 1:] <= y_thr)
        )

        j = first_consecutive(
            post_y[idx_amax + 1:],
            int(cfg.get("unwind_y_drop_consecutive", 3)),
        )
        if j is not None:
            idx_y_drop = int(idx_amax + 1 + j)
            out["Unwind_Y_drop_idx"] = idx_y_drop
            out["Unwind_Y_drop_Aeff"] = (
                float(A[idx_y_drop]) if np.isfinite(A[idx_y_drop]) else np.nan
            )

    # 4) Choix de la fin du palier
    if idx_xg_neg is not None:
        idx_end = idx_xg_neg
        out["Unwind_End_Trigger"] = "XG_NEGATIVE"
    elif idx_y_drop is not None:
        idx_end = idx_y_drop
        out["Unwind_End_Trigger"] = "Y_EFFECTIVE_DROP_FALLBACK"
    else:
        return out

    if idx_end <= idx_amax:
        return out

    idx0, idx1 = int(idx_amax), int(idx_end)
    out["Unwind_Plateau_A_end_eff"] = (
        float(A[idx1]) if np.isfinite(A[idx1]) else np.nan
    )

    if (
        np.isfinite(out["Unwind_Plateau_A_start_eff"])
        and np.isfinite(out["Unwind_Plateau_A_end_eff"])
    ):
        out["Unwind_Plateau_DeltaA_deg"] = float(
            out["Unwind_Plateau_A_start_eff"]
            - out["Unwind_Plateau_A_end_eff"]
        )

    # 5) Statistiques Xt sur le palier
    sl = slice(idx0, idx1 + 1)
    if Xt is not None:
        xt_vals = np.asarray(Xt[sl], dtype=float)
        xt_vals = xt_vals[np.isfinite(xt_vals)]

        if len(xt_vals) >= min_points:
            out["Unwind_Plateau_Found"] = True
            out["Unwind_Plateau_N_points"] = int(len(xt_vals))
            out["Unwind_Plateau_Xt_mean_Nm"] = float(np.nanmean(xt_vals))
            out["Unwind_Plateau_Xt_median_Nm"] = float(np.nanmedian(xt_vals))
            out["Unwind_Plateau_Xt_std_Nm"] = float(np.nanstd(xt_vals))

    # 6) Valeurs de contrôle
    if np.isfinite(Y[idx0]):
        out["Unwind_Plateau_Y_start_N"] = float(Y[idx0])
    if np.isfinite(Y[idx1]):
        out["Unwind_Plateau_Y_end_N"] = float(Y[idx1])

    if (
        np.isfinite(out["Unwind_Plateau_Y_start_N"])
        and abs(out["Unwind_Plateau_Y_start_N"]) > 1e-12
    ):
        out["Unwind_Plateau_Y_delta_rel"] = float(
            (out["Unwind_Plateau_Y_end_N"] - out["Unwind_Plateau_Y_start_N"])
            / out["Unwind_Plateau_Y_start_N"]
        )

    if Xg is not None:
        if np.isfinite(Xg[idx0]):
            out["Unwind_Plateau_Xg_start_Nm"] = float(Xg[idx0])
        if np.isfinite(Xg[idx1]):
            out["Unwind_Plateau_Xg_end_Nm"] = float(Xg[idx1])

    if Xt is not None:
        if np.isfinite(Xt[idx0]):
            out["Unwind_Plateau_Xt_start_Nm"] = float(Xt[idx0])
        if np.isfinite(Xt[idx1]):
            out["Unwind_Plateau_Xt_end_Nm"] = float(Xt[idx1])

    return out
