from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DiagNumericalConfig:
    """
    Configuration numérique du diagnostic ARCTA.

    Cette classe contient uniquement des paramètres de calcul.
    Aucun paramètre Tkinter, graphe ou mise en page ne doit être ajouté ici.

    Elle est immuable afin qu'un run ne puisse pas modifier
    accidentellement la configuration d'un autre run.
    """

    # --------------------------------------------------------------
    # Pré-DIAG / A0 élastique
    # --------------------------------------------------------------
    fmax_torque_min_ratio: float = 0.5
    diag_end_force_ratio: float = 0.025
    prediag_unload_drop_ratio: float = 0.05
    prediag_unload_consecutive: int = 3
    prediag_keep_before_a0_deg: float = 1080.0

    a0_fit_windows: tuple[tuple[float, float], ...] = (
        (0.20, 0.50),
        (0.25, 0.55),
        (0.30, 0.60),
        (0.20, 0.60),
    )

    a0_min_points: int = 8
    a0_min_r2_warn: float = 0.995

    # --------------------------------------------------------------
    # Contact / snug
    # --------------------------------------------------------------
    contact_sigma_k: float = 5.0
    contact_threshold_mode: str = "hybrid_backward"
    contact_sigma_floor_k: float = 2.0
    contact_min_ratio_ymax: float = 0.005
    contact_min_abs_N: float = 0.0
    contact_min_consecutive: int = 4

    snug_slope_fraction: float = 0.25
    snug_y_min_ratio: float = 0.03
    contact_backward_from_a0: bool = True

    # --------------------------------------------------------------
    # Xg / autofrein
    # --------------------------------------------------------------
    xg_threshold_from_autofrein_factor: float = 1.2
    xg_a0_reject_positive_eff: bool = False
    xg_a0_min_points: int = 8

    autofrein_y_max_ratio: float = 0.03
    autofrein_min_points: int = 5
    # 64H9B: amplitude stricte et délai depuis le point précédant le recul.
    autofrein_recoil_max_deg: float = 0.1
    autofrein_recovery_max_steps: int = 10

    # --------------------------------------------------------------
    # Torque Balance Residual
    # --------------------------------------------------------------
    balance_rel_warn: float = 0.08
    balance_rel_fail: float = 0.15

    tbr_y_min_ratio: float = 0.05
    tbr_xg_min_abs_Nm: float = 1e-9
    tbr_y_min_abs_N: float = 1e-9
    tbr_min_points: int = 5

    # --------------------------------------------------------------
    # Desserrage
    # --------------------------------------------------------------
    unwind_xg_negative_threshold_Nm: float = 0.0
    unwind_xg_negative_consecutive: int = 3
    unwind_y_effective_drop_ratio: float = 0.005
    unwind_y_drop_consecutive: int = 3
    unwind_min_points: int = 3
    unwind_smooth_window: int = 7

    # 63E2 — inversion physique et torsion résiduelle. Les seuils combinent
    # une valeur absolue (bruit métrologique minimal) et une fraction du
    # couple global maximal de l'essai.
    dead_travel_xg_zero_abs_Nm: float = 0.25
    dead_travel_xg_zero_ratio: float = 0.02
    dead_travel_xg_zero_consecutive: int = 3
    reverse_pickup_xg_abs_Nm: float = 0.25
    reverse_pickup_xg_ratio: float = 0.02
    reverse_pickup_consecutive: int = 3
    torsion_release_xt_zero_Nm: float = 0.0
    torsion_release_consecutive: int = 3
    dead_travel_preload_drift_warn_ratio: float = 0.02
    dead_travel_balance_warn_ratio: float = 0.10

    def to_dict(self) -> dict[str, Any]:
        """
        Retourne une copie mutable compatible avec le code historique.
        """
        return asdict(self)


DEFAULT_DIAG_NUMERICAL_CONFIG = DiagNumericalConfig()
