"""64H9B: contrôle des micro-reculs, sans modification des acquisitions."""
import math
import numpy as np
from ..config import DEFAULT_DIAG_NUMERICAL_CONFIG as DEFAULTS


def check_autofrein_rotation(angles, cfg):
    """Recul < limite, rattrapé au plus tard au point référence + N.

    La référence reste le maximum atteint avant l'excursion. Le délai compte
    les pas d'acquisition, y compris les plateaux. EPS ne traite que l'arrondi
    flottant, pas la résolution métrologique. Aucun tri ni lissage.
    """
    limit = float(cfg.get('autofrein_recoil_max_deg', DEFAULTS.autofrein_recoil_max_deg))
    raw_steps = cfg.get('autofrein_recovery_max_steps', DEFAULTS.autofrein_recovery_max_steps)
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError('autofrein_recoil_max_deg doit être fini et strictement positif')
    if (isinstance(raw_steps, bool) or not isinstance(raw_steps, (int, np.integer))
            or raw_steps < 1):
        raise ValueError('autofrein_recovery_max_steps doit être un entier positif')
    steps = int(raw_steps)
    out = dict(Autofrein_Rotation_Rule='MICRO_RECOIL_V1',
               Autofrein_Rotation_Recoil_Limit_deg=limit,
               Autofrein_Rotation_Recovery_Limit_Steps=steps,
               Autofrein_Rotation_Tolerated_Count=0,
               Autofrein_Rotation_Max_Recoil_deg=0.0,
               Autofrein_Rotation_Max_Recovery_Steps=0)

    def finish(status):
        reasons = {
            'OK': 'Aucun micro-recul angulaire détecté.',
            'RECOIL_LIMIT_EXCEEDED': f'Recul angulaire atteignant la limite de {limit:g}°.',
            'RECOVERY_TOO_LATE': f'Angle non rattrapé dans les {steps} pas d’acquisition autorisés.',
            'RECOVERY_NOT_OBSERVED': 'Fin de fenêtre avant le rattrapage du recul angulaire.',
            'NON_FINITE_ANGLE': 'Angle manquant ou non fini dans la fenêtre autofrein.',
            'INSUFFICIENT_ANGLE': 'Points insuffisants pour contrôler la rotation.',
        }
        count = out['Autofrein_Rotation_Tolerated_Count']
        if status == 'MICRO_RECOILS_TOLERATED':
            message = (f"{count} micro-recul(s) angulaire(s) toléré(s) ; "
                       f"amplitude maximale {out['Autofrein_Rotation_Max_Recoil_deg']:.3f}° ; "
                       f"rattrapage maximal {out['Autofrein_Rotation_Max_Recovery_Steps']} "
                       "pas d’acquisition depuis l’angle de référence.")
        else:
            message = reasons[status]
        out.update(Autofrein_Rotation_Status=status, Autofrein_Rotation_Message=message)
        return out

    values = np.asarray(angles, dtype=float)
    if values.ndim != 1 or len(values) < 2:
        return finish('INSUFFICIENT_ANGLE')
    if not np.isfinite(values).all():
        return finish('NON_FINITE_ANGLE')
    eps = 1e-9  # degré, tolérance d'arrondi seulement
    peak, reference, excursion = float(values[0]), 0, False
    for index, value in enumerate(values[1:], 1):
        elapsed = index - reference
        if value >= peak - eps:
            if excursion:
                if elapsed > steps:
                    return finish('RECOVERY_TOO_LATE')
                out['Autofrein_Rotation_Tolerated_Count'] += 1
                out['Autofrein_Rotation_Max_Recovery_Steps'] = max(
                    out['Autofrein_Rotation_Max_Recovery_Steps'], elapsed)
            peak, reference, excursion = max(peak, float(value)), index, False
            continue
        excursion = True
        recoil = float(peak - value)
        out['Autofrein_Rotation_Max_Recoil_deg'] = max(
            out['Autofrein_Rotation_Max_Recoil_deg'], recoil)
        if recoil >= limit or math.isclose(recoil, limit, rel_tol=0, abs_tol=eps):
            return finish('RECOIL_LIMIT_EXCEEDED')
        if elapsed >= steps:
            return finish('RECOVERY_TOO_LATE')
    if excursion:
        return finish('RECOVERY_NOT_OBSERVED')
    return finish('MICRO_RECOILS_TOLERATED' if out['Autofrein_Rotation_Tolerated_Count'] else 'OK')
