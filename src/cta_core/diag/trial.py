from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from ..models import ColumnSelection
from ..parsing import coerce_numeric_series
from .contact import detect_contact_and_snug
from .pre_a0_autofrein import compute_pre_a0_autofrein
from .preprocessing import preclean_and_fit_a0
from .torque_balance import torque_balance
from .unwind import compute_unwind_plateau_indicators
from .xg_indicators import compute_xg_based_a0_indicators
from .xh_xt_crossing import detect_xh_xt_crossing


def _early_result(trial_id: str, flag: str, pre: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "summary": {
            "Trial_ID": trial_id,
            "Status": "MANUAL_REVIEW",
            "Quality_Score": 0,
            "Main_Flags": flag,
        },
        "pre": pre or {},
        "balance": {},
        "_flags": [flag],
        "_plot_ready": False,
        "_error_message": None,
    }


def analyze_diag_trial(
    trial_id: str,
    df: pd.DataFrame,
    sel: ColumnSelection,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Orchestrateur scientifique DIAG unitaire, sans UI ni génération graphique.

    Le résultat public reprend les structures historiques DIAG.
    Les clés préfixées par "_" sont internes à l'adaptateur Desktop/Web.
    """
    flags: list[str] = []

    try:
        a_col, y_col = sel.roles.get("A"), sel.roles.get("Y")
        if not a_col or a_col not in df.columns:
            return _early_result(trial_id, "NO_ANGLE")
        if not y_col or y_col not in df.columns:
            return _early_result(trial_id, "NO_POSITIVE_TENSION")

        a = coerce_numeric_series(df[a_col]).to_numpy(dtype=float)
        y = coerce_numeric_series(df[y_col]).to_numpy(dtype=float)
        t_col = sel.roles.get("Xg")
        torque = coerce_numeric_series(df[t_col]).to_numpy(dtype=float) if t_col and t_col in df.columns else None
        pre = preclean_and_fit_a0(a, y, cfg, torque_raw=torque)

        if "error" in pre:
            flag = str(pre["error"])
            return _early_result(trial_id, flag, pre=pre)

        if pre.get("unload_5pct_detected"):
            flags.append("END_UNLOADING_DETECTED")

        fw = pre.get("A0_fit_window")
        if isinstance(fw, tuple) and fw[-1] == "fallback":
            flags.append("A0_FALLBACK_WINDOW")

        r2_a0 = pre.get("R2_A0_fit", np.nan)
        if np.isfinite(r2_a0) and r2_a0 < float(cfg["a0_min_r2_warn"]):
            flags.append("LOW_A0_LINEARITY")

        seg = detect_contact_and_snug(pre["Aeff_clean"], pre["Y_clean"], pre, cfg)
        a_contact_eff = seg.get("A_contact_Y_eff", np.nan)
        a_snug_eff = seg.get("A_snug_eff", np.nan)

        if not np.isfinite(a_contact_eff):
            flags.append("CONTACT_NOT_FOUND")
        if not np.isfinite(a_snug_eff):
            flags.append("SNUG_NOT_FOUND")
        if np.isfinite(a_contact_eff) and np.isfinite(a_snug_eff) and a_contact_eff >= a_snug_eff:
            flags.append("CONTACT_AFTER_SNUG")
        if np.isfinite(a_snug_eff) and a_snug_eff >= 0:
            flags.append("SNUG_AFTER_A0")
        if np.isfinite(a_contact_eff) and a_contact_eff >= 0:
            flags.append("CONTACT_AFTER_A0")
        if any(f in flags for f in ("CONTACT_AFTER_SNUG", "SNUG_AFTER_A0", "CONTACT_AFTER_A0")):
            flags.append("A0_ORDER_INCOHERENT")

        i0, i1 = int(pre["idx_start"]), int(pre["idx_stop"])
        signals: dict[str, Any] = {}
        for role in ("Xg", "Xh", "Xt"):
            col = sel.roles.get(role)
            signals[role] = (
                coerce_numeric_series(df[col]).to_numpy(dtype=float)[i0:i1 + 1]
                if col and col in df.columns else None
            )

        autofrein = compute_pre_a0_autofrein(
            a[:pre["idx_ymax"]+1] - pre["A0_elastic_Y"],
            y[:pre["idx_ymax"]+1],
            {role: coerce_numeric_series(df[sel.roles[role]]).to_numpy(dtype=float)[:pre["idx_ymax"]+1]
             for role in ("Xg", "Xt") if sel.roles.get(role) in df.columns},
            pre["Ymax"], cfg, a_contact_eff=a_contact_eff,
        )
        seg.update(autofrein)

        xg_a0 = compute_xg_based_a0_indicators(
            pre["Aeff_clean"], pre["Y_clean"], signals, pre, cfg,
            a_contact_eff=a_contact_eff, autofrein_payload=autofrein,
        )
        seg.update(xg_a0)

        cross = detect_xh_xt_crossing(
            pre["Aeff_clean"], pre["Y_clean"], signals,
            a_contact_eff=a_contact_eff,
        )
        seg.update(cross)

        balance = torque_balance(
            signals.get("Xg"), signals.get("Xh"), signals.get("Xt"),
            pre["Y_clean"], pre["Ymax"], cfg, aeff=pre.get("Aeff_clean"),
        )
        seg.update(balance)

        # Fenêtre DIAG : A0 - 1080° jusqu'au premier critère de fin.
        diag_angle = a - pre["A0_elastic_Y"]
        before_peak = np.arange(len(a)) <= pre["idx_ymax"]
        starts = np.flatnonzero(
            before_peak & np.isfinite(diag_angle)
            & (diag_angle >= -float(cfg["prediag_keep_before_a0_deg"]))
        )
        start = int(starts[0]) if len(starts) else 0
        reverse = int(np.nanargmax(a))
        after_reverse = np.arange(len(a)) > reverse
        end = len(a) - 1
        end_reason = "END_OF_ACQUISITION"
        force_ratio = float(cfg.get("diag_end_force_ratio", 0.025))
        if not np.isfinite(force_ratio) or not 0 < force_ratio < 1:
            raise ValueError("diag_end_force_ratio doit appartenir à ]0 ; 1[.")

        # Couple minimal négatif après inversion.
        if torque is not None:
            negative = np.flatnonzero(
                after_reverse & np.isfinite(torque) & (torque < 0)
            )
            if len(negative):
                end = int(negative[np.argmin(torque[negative])])
                end_reason = "MINIMUM_TORQUE"

        # Arrêt plus tôt si la force atteint 2,5 % de Fmax au serrage.
        force_end = np.flatnonzero(
            after_reverse & np.isfinite(y)
            & (y <= force_ratio * pre["Ymax"])
        )
        if len(force_end) and int(force_end[0]) <= end:
            end = int(force_end[0])
            end_reason = "FORCE_THRESHOLD"

        window = slice(start, end + 1)
        diag_angle = diag_angle[window]
        diag_force = y[window]
        diag_signals = {}
        for role in ("Xg", "Xh", "Xt"):
            col = sel.roles.get(role)
            diag_signals[role] = (
                coerce_numeric_series(df[col]).to_numpy(dtype=float)[window]
                if col and col in df.columns else None
            )

        pre.update({
            "Diag_window_start_idx": start,
            "Diag_window_end_idx": end,
            "Diag_window_end_reason": end_reason,
            "Diag_end_force_ratio": force_ratio,
        })
        unwind = compute_unwind_plateau_indicators(
            diag_angle, diag_force, diag_signals, pre, cfg,
        )
        seg.update(unwind)

        penalty = {
            "A0_FALLBACK_WINDOW": 5,
            "LOW_A0_LINEARITY": 15,
            "CONTACT_NOT_FOUND": 10,
            "SNUG_NOT_FOUND": 10,
            "CONTACT_AFTER_SNUG": 15,
            "SNUG_AFTER_A0": 10,
            "CONTACT_AFTER_A0": 10,
            "A0_ORDER_INCOHERENT": 10,
        }
        score = max(0.0, 100.0 - sum(penalty.get(f, 0) for f in set(flags)))
        critical = {"NO_ANGLE", "A0_NOT_FOUND", "TOO_FEW_POINTS", "NO_POSITIVE_TENSION"}
        active_flags = [f for f in flags if f != "END_UNLOADING_DETECTED"]
        status = (
            "MANUAL_REVIEW" if any(f in critical for f in flags)
            else ("WARNING" if active_flags else "OK")
        )

        order_txt = (
            f"A_contact={a_contact_eff:.1f}° ; A_snug={a_snug_eff:.1f}° ; A0=0.0°"
            if np.isfinite(a_contact_eff) and np.isfinite(a_snug_eff)
            else f"A_contact={a_contact_eff} ; A_snug={a_snug_eff} ; A0=0.0"
        )
        fw_txt = f"{fw[0]:.2f}-{fw[1]:.2f} Ymax / {fw[2]}" if isinstance(fw, tuple) else ""

        summary = {
            "Trial_ID": trial_id,
            "Status": status,
            "Quality_Score": score,  # alias historique conservé
            "Score_Comportement_Global": score,
            "Xgmax": (float(np.nanmax(signals["Xg"]))
                      if signals.get("Xg") is not None and np.isfinite(signals["Xg"]).any() else np.nan),
            "Use_For_ARCTA": "YES" if status == "OK" else ("YES_WITH_FLAG" if status == "WARNING" else "MANUAL_REVIEW"),
            "Main_Flags": ";".join(flags) if flags else "OK",
            "A0_elastic_Y": pre.get("A0_elastic_Y", np.nan),
            "A_contact_Y_eff": a_contact_eff,
            "A_snug_eff": a_snug_eff,
            "A0_snug_from_Xg_threshold": seg.get("A0_snug_from_Xg_threshold", np.nan),
            "A0_snug_from_Xg_threshold_eff": seg.get("A0_snug_from_Xg_threshold_eff", np.nan),
            "A0_snug_from_Xg_threshold_method": seg.get("A0_snug_from_Xg_threshold_method", ""),
            "A0_elastic_from_Xg": seg.get("A0_elastic_from_Xg", np.nan),
            "A0_elastic_from_Xg_eff": seg.get("A0_elastic_from_Xg_eff", np.nan),
            "A0_shift_Xg_vs_Y": seg.get("A0_shift_Xg_vs_Y", np.nan),
            "TBR_N_valid": balance.get("TBR_N_valid", 0),
            "TBR_Mean_Nm": balance.get("TBR_Mean_Nm", np.nan),
            "TBR_RMS_Nm": balance.get("TBR_RMS_Nm", np.nan),
            "TBR_MaxAbs_Nm": balance.get("TBR_MaxAbs_Nm", np.nan),
            "TBR_MeanAbsRel_Xg": balance.get("TBR_MeanAbsRel_Xg", np.nan),
            "TBR_MaxAbsRel_Xg": balance.get("TBR_MaxAbsRel_Xg", np.nan),
            "TBR_MeanAbs_per_Y_Nm_per_N": balance.get("TBR_MeanAbs_per_Y_Nm_per_N", np.nan),
            "TBR_Energy_J": balance.get("TBR_Energy_J", np.nan),
            "TBR_AbsEnergy_J": balance.get("TBR_AbsEnergy_J", np.nan),
            "Torque_Balance_Flag": balance.get("Balance_Flag", "NA"),
            "K_XgA_20_50": seg.get("K_XgA_20_50", np.nan),
            "R2_XgA_20_50": seg.get("R2_XgA_20_50", np.nan),
            "Xg_baseline_preA0_Nm": seg.get("Xg_baseline_preA0_Nm", np.nan),
            "Xg_threshold_Nm": seg.get("Xg_threshold_Nm", np.nan),
            "A0_elastic_from_Xg_method": seg.get("A0_elastic_from_Xg_method", ""),
            "K_XgA_baseline": seg.get("K_XgA_baseline", np.nan),
            "Intercept_XgA_baseline": seg.get("Intercept_XgA_baseline", np.nan),
            "R2_XgA_baseline": seg.get("R2_XgA_baseline", np.nan),
            "N_XgA_baseline_fit": seg.get("N_XgA_baseline_fit", np.nan),
            "Xg_autofrein_used_Nm": seg.get("Xg_autofrein_used_Nm", np.nan),
            "Xg_autofrein_source": seg.get("Xg_autofrein_source", ""),
            "Xg_threshold_factor": seg.get("Xg_threshold_factor", np.nan),
            "Xg_threshold_method": seg.get("Xg_threshold_method", ""),
            "A0_elastic_from_Xg_eff_raw": seg.get("A0_elastic_from_Xg_eff_raw", np.nan),
            "Aeff_Ymax": pre.get("Aeff_Ymax", np.nan),
            "Ymax": pre.get("Ymax", np.nan),
            "T_at_Fmax_Nm": pre["T_at_Fmax_Nm"],
            "Fmax_cycle_N": pre["Fmax_cycle_N"],
            "Fmax_torque_min_ratio": pre["Fmax_torque_min_ratio"],
            "Fmax_method": pre["Fmax_method"],
            "R2_A0_fit": pre.get("R2_A0_fit", np.nan),
            "K_YA_20_50": pre.get("K_YA_20_50", np.nan),
            "A0_fit_window": fw_txt,
            "A_elastic_start_eff": pre.get("A_elastic_start_eff", np.nan),
            "A_elastic_end_eff": pre.get("A_elastic_end_eff", np.nan),
            "Diagnostic_Order": order_txt,
            "Order_OK_expected_contact_lt_snug_lt_A0": bool(
                np.isfinite(a_contact_eff)
                and np.isfinite(a_snug_eff)
                and a_contact_eff < a_snug_eff < 0
            ),
            "A_cross_Xh_Xt_eff": cross.get("A_cross_Xh_Xt_eff", np.nan),
            "Y_cross_Xh_Xt": cross.get("Y_cross_Xh_Xt", np.nan),
            "Xh_Xt_cross_found": cross.get("Xh_Xt_cross_found", False),
            "Autofrein_Xg_preA0_med": autofrein.get("Autofrein_Xg_preA0_med", np.nan),
            "Autofrein_Xt_preA0_med": autofrein.get("Autofrein_Xt_preA0_med", np.nan),
            "Autofrein_Xg_minus_Xt_preA0_med": autofrein.get("Autofrein_Xg_minus_Xt_preA0_med", np.nan),
            "Unwind_Plateau_Found": unwind.get("Unwind_Plateau_Found", False),
            "Unwind_End_Trigger": unwind.get("Unwind_End_Trigger", "NA"),
            "Unwind_Amax_eff": unwind.get("Unwind_Amax_eff", np.nan),
            "Unwind_Xg_negative_Aeff": unwind.get("Unwind_Xg_negative_Aeff", np.nan),
            "Unwind_Y_drop_Aeff": unwind.get("Unwind_Y_drop_Aeff", np.nan),
            "Unwind_Plateau_A_start_eff": unwind.get("Unwind_Plateau_A_start_eff", np.nan),
            "Unwind_Plateau_A_end_eff": unwind.get("Unwind_Plateau_A_end_eff", np.nan),
            "Unwind_Plateau_DeltaA_deg": unwind.get("Unwind_Plateau_DeltaA_deg", np.nan),
            "Unwind_Plateau_Xt_mean_Nm": unwind.get("Unwind_Plateau_Xt_mean_Nm", np.nan),
            "Unwind_Plateau_Xt_median_Nm": unwind.get("Unwind_Plateau_Xt_median_Nm", np.nan),
            "Unwind_Plateau_N_points": unwind.get("Unwind_Plateau_N_points", 0),
            "Unwind_Plateau_Y_delta_rel": unwind.get("Unwind_Plateau_Y_delta_rel", np.nan),
        }

        summary.update(autofrein)  # 64H7 : fenêtre et validité suivent la revue persistée.

        # 63E2 : indicateurs physiques de l'inversion. Les anciens champs
        # Unwind_* restent exportés pour compatibilité, tandis que ces noms
        # explicites alimentent désormais l'interface et le rapport.
        for key in (
            "Reverse_Amax_Aeff_deg",
            "DeadTravel_Found",
            "DeadTravel_End_Trigger",
            "DeadTravel_Start_Aeff_deg",
            "DeadTravel_End_Aeff_deg",
            "DeadTravel_DeltaA_deg",
            "DeadTravel_N_points",
            "Reverse_Pickup_Aeff_deg",
            "Effective_Loosening_Aeff_deg",
            "Torsion_Release_Xt_Zero_Aeff_deg",
            "Residual_Thread_Torque_Mean_Nm",
            "Residual_Thread_Torque_Median_Nm",
            "Residual_Thread_Torque_Std_Nm",
            "Residual_Torsion_Torque_Abs_Nm",
            "Residual_Thread_Torque_Evaluable",
            "DeadTravel_Xg_RMS_Nm",
            "DeadTravel_Balance_RMS_Nm",
            "DeadTravel_Balance_Rel",
            "DeadTravel_Preload_Delta_Rel",
            "Residual_Torsion_Diameter_mm",
            "Residual_Torsion_Diameter_Source",
            "Residual_Torsional_Stress_Nominal_MPa",
            "Residual_Torsional_Stress_Evaluable",
            "DeadTravel_Quality_Flag",
        ):
            summary[key] = unwind.get(key, np.nan)

        pre_export = {k: v for k, v in pre.items() if not isinstance(v, np.ndarray)}
        fw_export = pre_export.pop("A0_fit_window", None)
        if isinstance(fw_export, tuple) and len(fw_export) >= 3:
            pre_export["A0_fit_window_low_ratio"] = fw_export[0]
            pre_export["A0_fit_window_high_ratio"] = fw_export[1]
            pre_export["A0_fit_window_kind"] = fw_export[2]
            pre_export["A0_fit_window"] = f"{fw_export[0]:.2f}-{fw_export[1]:.2f} Ymax / {fw_export[2]}"
        elif fw_export is not None:
            pre_export["A0_fit_window"] = str(fw_export)

        return {
            "summary": summary,
            "pre": {"Trial_ID": trial_id, **pre_export},
            "balance": {"Trial_ID": trial_id, **balance},
            "cross": {"Trial_ID": trial_id, **cross},
            "autofrein": {"Trial_ID": trial_id, **autofrein},
            "unwind": {"Trial_ID": trial_id, **unwind},
            "_aeff_clean": diag_angle,
            "_y_clean": diag_force,
            "_signals": diag_signals,
            "_seg": seg,
            "_flags": flags,
            "_pre_raw": pre,
            "_plot_ready": True,
            "_error_message": None,
        }

    except Exception as exc:
        return {
            "summary": {
                "Trial_ID": trial_id,
                "Status": "MANUAL_REVIEW",
                "Quality_Score": 0,
                "Main_Flags": "DIAG_EXCEPTION",
            },
            "pre": {},
            "balance": {},
            "cross": {},
            "autofrein": {},
            "unwind": {},
            "_flags": ["DIAG_EXCEPTION"],
            "_plot_ready": False,
            "_error_message": str(exc),
        }
