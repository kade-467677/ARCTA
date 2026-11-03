from __future__ import annotations

from typing import Any

DEFAULT_ARCTA_RUN_PROFILE = "FULL_REPORT"

ARCTA_RUN_PROFILES: dict[str, dict[str, Any]] = {
    "DIAG_CONCAT_ONLY": {
        "do_mu": False,
        "do_polyfits": False,
        "do_compute": False,
        "do_polyfits_stats": False,
        "do_autofrein": False,
        "do_plots": False,
        "do_pdf": False,
        "compute_n_points": 0,
        "max_deg": 4,
        "r2_target": 0.995,
    },
    "FAST_REVIEW": {
        "do_mu": True,
        "do_polyfits": True,
        "do_compute": True,
        "do_polyfits_stats": False,
        "do_autofrein": False,
        "do_plots": False,
        "do_pdf": False,
        "compute_n_points": 200,
        "max_deg": 4,
        "r2_target": 0.995,
    },
    "FULL_ANALYSIS_NO_REPORT": {
        "do_mu": True,
        "do_polyfits": True,
        "do_compute": True,
        "do_polyfits_stats": True,
        "do_autofrein": True,
        "do_plots": True,
        "do_pdf": False,
        "compute_n_points": 200,
        "max_deg": 6,
        "r2_target": 0.999,
    },
    "FULL_REPORT": {
        "do_mu": True,
        "do_polyfits": True,
        "do_compute": True,
        "do_polyfits_stats": True,
        "do_autofrein": True,
        "do_plots": True,
        "do_pdf": True,
        "compute_n_points": 200,
        "max_deg": 6,
        "r2_target": 0.999,
    },
}

ARCTA_RUN_PROFILE_LABELS = {
    "DIAG_CONCAT_ONLY": "DIAG + CONCAT seulement",
    "FAST_REVIEW": "Rapide : µ + polyfits + compute, sans stats lourdes / graphes / PDF",
    "FULL_ANALYSIS_NO_REPORT": "Analyse complète sans rapport PDF",
    "FULL_REPORT": "Analyse complète avec graphes + rapport PDF",
}


def get_profile_config(profile: str) -> dict[str, Any]:
    """Compatibilité V5 : un profil inconnu retombe sur DIAG_CONCAT_ONLY."""
    cfg = ARCTA_RUN_PROFILES.get(profile, ARCTA_RUN_PROFILES["DIAG_CONCAT_ONLY"])
    return dict(cfg)


def require_profile_config(profile: str) -> dict[str, Any]:
    """Version stricte destinée aux services/API : profil inconnu = erreur."""
    if profile not in ARCTA_RUN_PROFILES:
        raise ValueError(f"Profil ARCTA inconnu : {profile}")
    return dict(ARCTA_RUN_PROFILES[profile])