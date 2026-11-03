from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArctaAnalysisConfig:
    thr_ratio: float = 0.05
    iso_tol_p_content: float = 0.90
    iso_tol_conf_level: float = 0.95
    iso_median_conf_level: float = 0.95
    normality_alpha: float = 0.05
    normality_min_n: int = 8
    mean_ci_conf_level: float = 0.95
    subtract_selflock: bool = False

    def __post_init__(self) -> None:
        if type(self.subtract_selflock) is not bool:
            raise ValueError("subtract_selflock doit être un booléen.")
        if not 0.0 < self.mean_ci_conf_level < 1.0:
            raise ValueError("mean_ci_conf_level doit être compris entre 0 et 1.")
        if not 0.0 <= self.thr_ratio < 1.0:
            raise ValueError("thr_ratio doit vérifier 0 <= thr_ratio < 1.")
        if not 0.0 < self.iso_tol_p_content < 1.0:
            raise ValueError("iso_tol_p_content doit être compris entre 0 et 1.")
        if not 0.0 < self.iso_tol_conf_level < 1.0:
            raise ValueError("iso_tol_conf_level doit être compris entre 0 et 1.")
        if not 0.0 < self.iso_median_conf_level < 1.0:
            raise ValueError("iso_median_conf_level doit être compris entre 0 et 1.")
        if not 0.0 < self.normality_alpha < 1.0:
            raise ValueError("normality_alpha doit être compris entre 0 et 1.")
        if self.normality_min_n < 3:
            raise ValueError("normality_min_n doit être >= 3.")


DEFAULT_ARCTA_ANALYSIS_CONFIG = ArctaAnalysisConfig()