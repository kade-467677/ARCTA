"""Maximum de force au serrage ; indices dans l'acquisition originale."""
import numpy as np
from cta_core.config import DEFAULT_DIAG_NUMERICAL_CONFIG


def tightening_peak(force, torque=None, angle=None, cfg=None):
    cfg = DEFAULT_DIAG_NUMERICAL_CONFIG.to_dict() if cfg is None else cfg
    ratio = float(cfg.get("fmax_torque_min_ratio", 0.5))
    if not np.isfinite(ratio) or not 0 < ratio <= 1:
        raise ValueError("fmax_torque_min_ratio doit appartenir à ]0 ; 1].")
    f = np.asarray(force, dtype=float)
    t = None if torque is None else np.asarray(torque, dtype=float)
    a = None if angle is None else np.asarray(angle, dtype=float)
    if f.ndim != 1 or any(v is not None and (v.ndim != 1 or len(v) != len(f)) for v in (t, a)):
        raise ValueError("F, T et angle doivent être alignés dans l'ordre d'acquisition.")
    valid = np.isfinite(f)
    if a is not None:
        valid &= np.isfinite(a)
    if not valid.any():
        raise ValueError("FMAX_NO_VALID_FORCE")
    # Première occurrence de l'angle maximal : borne avant rotation inverse.
    end = len(f) - 1
    if a is not None:
        if not np.isfinite(a).any():
            raise ValueError("FMAX_NO_VALID_ANGLE")
        end = int(np.nanargmax(a))
    eligible = valid & (np.arange(len(f)) <= end)
    tmax = float("nan")
    if t is not None:
        positive = eligible & np.isfinite(t) & (t > 0)
        if not positive.any():
            raise ValueError("FMAX_NO_POSITIVE_TORQUE")
        # Fin du pic/plateau positif avant inversion : exclut la décharge,
        # même quand son couple reste positif et sa force augmente.
        end = int(np.flatnonzero(positive & (t == np.max(t[positive])))[-1])
        tmax = float(t[end])
        eligible &= (np.arange(len(f)) <= end) & np.isfinite(t)
        eligible &= (t > 0) & (t >= ratio * tmax) & (t <= tmax)
    elif a is None:
        raise ValueError("FMAX_PHASE_UNAVAILABLE")
    if not eligible.any():
        raise ValueError("FMAX_NO_ADMISSIBLE_POINT")
    i = int(np.argmax(np.where(eligible, f, -np.inf)))
    if f[i] <= 0:
        raise ValueError("NO_POSITIVE_TENSION")
    return {
        "idx_ymax": i, "Ymax": float(f[i]),
        "T_at_Fmax_Nm": float(t[i]) if t is not None else float("nan"),
        "Fmax_cycle_N": float(np.max(f[np.isfinite(f)])),
        "Tmax_tightening_Nm": tmax, "Tightening_end_idx": end,
        "Fmax_torque_min_ratio": ratio,
        "Fmax_method": "TIGHTENING_TORQUE_WINDOW" if t is not None else "ANGLE_ONLY_NO_TORQUE",
    }
