"""64H7 : modèle linéarisé K&K géométrique et couple effectif par essai.
Unités : force N, longueurs mm, couples N.m. Aucune mutation des mesures.
"""
import math
import numpy as np
import pandas as pd
from .columns import group_concat_columns_by_trial, pick_first

MODEL = 'KK_GEOMETRY_1'
WINDOW = 'A0_MINUS_3_TO_MINUS_1_TURNS_V1'
GEOMETRY_FIELDS = ('thread_half_angle_deg', 'thread_lead_mm',
                   'bearing_geometry', 'bearing_cone_half_angle_deg')


def finite(value, name):
    if isinstance(value, bool):
        raise ValueError(name + ' : nombre requis')
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(name + ' : nombre requis') from exc
    if not math.isfinite(n):
        raise ValueError(name + ' : nombre fini requis')
    return n


def geometry(constants):
    p, d, db = (finite(constants.get(k), k) for k in ('p', 'd2', 'Db'))
    if min(p, d, db) <= 0:
        raise ValueError('p, d2 et Db doivent être strictement positifs')
    if constants.get('kk_model', 'LEGACY_0577') == 'LEGACY_0577':
        return p, .577*d, db/2
    if constants.get('kk_model') != MODEL:
        raise ValueError('Modèle K&K inconnu')
    alpha = finite(constants.get('thread_half_angle_deg'), 'Demi-angle du flanc chargé')
    lead = finite(constants.get('thread_lead_mm', p), 'Avance par tour')
    if not 0 <= alpha < 90 or lead <= 0:
        raise ValueError('Demi-angle attendu dans [0,90[ ; avance strictement positive')
    starts = lead/p
    if starts < 1 or not math.isclose(starts, round(starts), abs_tol=1e-8):
        raise ValueError('Avance / pas doit être un nombre entier positif de filets')
    bearing = str(constants.get('bearing_geometry', 'plate')).strip().lower()
    if bearing == 'plate':
        theta = 90.
    elif bearing == 'conique':
        theta = finite(constants.get('bearing_cone_half_angle_deg'), 'Demi-angle du cône depuis l’axe')
        if not 0 < theta < 90:
            raise ValueError('Appui conique : demi-angle depuis l’axe dans ]0,90[')
    else:
        raise ValueError('K&K : appui plate ou conique requis ; appui sphérique non modélisé')
    gt = d/2 * math.sqrt(1 + math.tan(math.radians(alpha))**2 / (1+(lead/(math.pi*d))**2))
    gh = db/2 / math.sin(math.radians(theta))
    return lead, gt, gh


def offsets(diag, ids):
    from .selflock_policy import resolve_selflock
    audit = resolve_selflock(diag, ids)
    return dict(zip(audit.Trial_ID, audit.Autofrein_Nm))

def corrected(df, diag, enabled):
    result = df.copy(deep=True)
    if not enabled:
        return result, pd.DataFrame()
    groups = group_concat_columns_by_trial(df)
    from .selflock_policy import resolve_selflock
    audit = resolve_selflock(diag, groups)
    values = dict(zip(audit.Trial_ID, audit.Autofrein_Nm))
    for tid, columns in groups.items():
        val = values[str(tid)]
        for role in ('Xg_', 'Xt_'):
            col = pick_first(columns, role)
            if col:
                result[col] = pd.to_numeric(df[col], errors='coerce') - val
    return result, audit


def settings_rows(constants, enabled):
    from .selflock_policy import POLICY
    model = constants.get('kk_model', 'LEGACY_0577')
    return pd.DataFrame([
        {'Parameter': 'SELFLOCK_POLICY', 'Value': POLICY, 'Meaning': 'Repli médian au RUN si au moins 2/3 des essais retenus ont une mesure valide'},
        {'Parameter': 'TORQUE_BASIS', 'Value': 'EFFECTIVE' if enabled else 'TOTAL', 'Meaning': 'Convention des polynômes ; EFFECTIVE = autofrein par essai déduit'},
        {'Parameter': 'KK_MODEL', 'Value': model, 'Meaning': 'Modèle linéarisé avec géométrie ou historique 0.577'},
        {'Parameter': 'SELFLOCK_METHOD', 'Value': WINDOW if enabled else 'NOT_APPLIED', 'Meaning': 'Méthode de soustraction du couple autofrein'},
    ])


def caption(sheets):
    frame = sheets.get('ARCTA_SETTINGS', pd.DataFrame())
    values = dict(zip(frame.get('Parameter', []), frame.get('Value', [])))
    if 'TORQUE_BASIS' not in values:
        return ''
    return ('Couple effectif — autofrein déduit ; aucune consigne outil directe'
            if values['TORQUE_BASIS'] == 'EFFECTIVE' else 'Couple total mesuré')
