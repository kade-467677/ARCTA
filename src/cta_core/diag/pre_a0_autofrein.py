from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .angular_continuity import check_autofrein_rotation


def compute_pre_a0_autofrein(aeff, y, signals, ymax, cfg, a_contact_eff=np.nan):
    """Autofrein au vissage dans [-1080,-360] degrés, sans fenêtre de repli.
    Le seuil force est une règle ARCTA, pas une prescription NASA.
    L'engagement complet du frein doit être confirmé par le protocole d'essai.
    """
    A, F = np.asarray(aeff, float), np.asarray(y, float)
    raw_t = signals.get('Xg')
    T = np.asarray([] if raw_t is None else raw_t, float)
    n = min(len(A), len(F), len(T)); A,F,T = A[:n],F[:n],T[:n]
    out = {'Autofrein_Window_Mode': 'A0_MINUS_3_TO_MINUS_1_TURNS_V1',
           'Autofrein_Status': 'INSUFFICIENT_DATA', 'N_points_autofrein_preA0': 0,
           'Aeff_autofrein_start': np.nan, 'Aeff_autofrein_end': np.nan,
           'Autofrein_Force_Limit_N': np.nan}
    for key in ('Xg_preA0_med','Xg_preA0_mean','Xg_preA0_std','Xg_preA0_MAD',
                'Xt_preA0_med','Xt_preA0_mean','Xg_minus_Xt_preA0_med','Xg_over_Xt_preA0_med'):
        out['Autofrein_'+key] = np.nan
    if n < 5 or not np.isfinite(A).any():
        return out
    # Only the first tightening passage, never the return through the same angles.
    reach = np.flatnonzero(np.isfinite(A) & (A >= -360))
    if not len(reach):
        out['Autofrein_Status'] = 'INCOMPLETE_WINDOW'; return out
    stop = int(reach[0])+1
    A,F,T = A[:stop],F[:stop],T[:stop]
    finite_a = A[np.isfinite(A)]
    if not len(finite_a) or finite_a.min() > -1080:
        out['Autofrein_Status'] = 'INCOMPLETE_WINDOW'; return out
    mask = np.isfinite(A) & (A>=-1080) & (A<=-360)
    idx = np.flatnonzero(mask)
    out['N_points_autofrein_preA0'] = len(idx)
    if len(idx) < max(5,int(cfg.get('autofrein_min_points',5))):
        return out
    out['Aeff_autofrein_start'],out['Aeff_autofrein_end'] = float(A[idx[0]]),float(A[idx[-1]])
    # Segment contigu : ne pas masquer un recul ressortant par la borne basse.
    # Le premier point atteignant -360 permet de constater le rattrapage final.
    rotation = check_autofrein_rotation(A[idx[0]:stop], cfg)
    out.update(rotation)
    if rotation['Autofrein_Rotation_Status'] not in ('OK', 'MICRO_RECOILS_TOLERATED'):
        out['Autofrein_Status'] = ('NON_FINITE_MEASUREMENTS'
            if rotation['Autofrein_Rotation_Status'] == 'NON_FINITE_ANGLE'
            else 'ROTATION_NOT_CONTINUOUS')
        return out
    if A[idx[-1]]-A[idx[0]] < .90*720:
        out['Autofrein_Status'] = 'INCOMPLETE_WINDOW'; return out
    if not np.isfinite(F[idx]).all() or not np.isfinite(T[idx]).all():
        out['Autofrein_Status'] = 'NON_FINITE_MEASUREMENTS'; return out
    # Threshold configurable in DIAG cfg: no silent removal of loaded samples.
    limit = max(float(cfg.get('autofrein_zero_force_abs_N',0)),
                float(cfg.get('autofrein_zero_force_ratio',.01))*float(ymax))
    if not np.isfinite(limit) or limit <= 0:
        out['Autofrein_Status'] = 'FORCE_ZERO_NOT_CHECKABLE'; return out
    out['Autofrein_Force_Limit_N'] = limit
    if np.max(np.abs(F[idx])) > limit:
        out['Autofrein_Status'] = 'FORCE_NOT_ZERO'; return out
    if np.isfinite(a_contact_eff) and a_contact_eff <= -360:
        out['Autofrein_Status'] = 'CONTACT_IN_OR_BEFORE_WINDOW'; return out
    values = T[idx]; median = float(np.median(values))
    if median < 0:
        out['Autofrein_Status'] = 'NEGATIVE_TORQUE'; return out
    out.update(Autofrein_Status='VALID', Autofrein_Xg_preA0_med=median,
               Autofrein_Xg_preA0_mean=float(np.mean(values)),
               Autofrein_Xg_preA0_std=float(np.std(values)),
               Autofrein_Xg_preA0_MAD=float(np.median(np.abs(values-median))))
    xt = signals.get('Xt')
    if xt is not None and len(xt)>idx[-1]:
        xt = np.asarray(xt,float)[idx]
        if np.isfinite(xt).all():
            out['Autofrein_Xt_preA0_med'] = float(np.median(xt))
            out['Autofrein_Xt_preA0_mean'] = float(np.mean(xt))
            out['Autofrein_Xg_minus_Xt_preA0_med'] = float(np.median(values-xt))
            valid = np.abs(xt)>1e-12
            if valid.any(): out['Autofrein_Xg_over_Xt_preA0_med'] = float(np.median(values[valid]/xt[valid]))
    return out
