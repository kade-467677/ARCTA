"""64G3 : comparaison descriptive réévaluée sur les essais non rejetés."""
from dataclasses import replace
import hashlib
import json
import math
from collections import defaultdict
import numpy as np
from cta_core.diag.iso16269_4 import _scalar_baseline, _robust_z_value
from arcta.diag_summary import (
    DIAG_ISO16269_4_MIN_N, DIAG_ISO16269_4_IQR_WARN_K,
    DIAG_ISO16269_4_IQR_FAIL_K, DIAG_ISO16269_4_ROBUST_Z_WARN,
    DIAG_ISO16269_4_ROBUST_Z_FAIL,
)

# Liste positive : seuls les indicateurs décisionnels affichés participent.
FAMILIES = {
    'Ymax': 'Niveaux', 'Xgmax': 'Niveaux',
    'A_contact_Y_eff': 'Cinématique', 'A_snug_eff': 'Cinématique',
    'Aeff_Ymax': 'Cinématique', 'Aeff_min': 'Cinématique',
    'DeadTravel_DeltaA_deg': 'Cinématique', 'Reverse_Pickup_Aeff_deg': 'Cinématique',
    'K_YA_20_50': 'Réponse mécanique',
    'A0_elastic_from_Xg_eff': 'Réponse mécanique',
    'A0_shift_Xg_vs_Y': 'Réponse mécanique', 'Xg_threshold_Nm': 'Réponse mécanique',
    'A_cross_Xh_Xt_eff': 'Répartition des couples',
    'Y_cross_Xh_Xt': 'Répartition des couples',
    'Xg_cross_Xh_Xt': 'Répartition des couples',
    'Xh_cross_Xh_Xt': 'Répartition des couples',
    'Xt_cross_Xh_Xt': 'Répartition des couples',
    'Residual_Thread_Torque_Median_Nm': 'Torsion résiduelle',
    'Residual_Torsional_Stress_Nominal_MPa': 'Torsion résiduelle',
    'Autofrein_Xg_preA0_med': 'Autofrein', 'Autofrein_Xg_preA0_mean': 'Autofrein',
    'Autofrein_Xg_preA0_std': 'Autofrein', 'Autofrein_Xg_preA0_MAD': 'Autofrein',
    'Autofrein_Xt_preA0_med': 'Autofrein',
}

RULES = {
    'version': '64G3-1',
    'min_n': DIAG_ISO16269_4_MIN_N,
    'distance_free': 0.75,      # Distance sans pénalité, en IQR
    'distance_full': 4.0,       # Distance donnant 100 % de pénalité
    'mean_weight': 0.7,         # Poids de la moyenne des familles
    'worst_weight': 0.3,        # Poids du pire indicateur
    'min_indicators': 3,
    'min_families': 2,
    'min_coverage': 0.5,
    'iqr_relative_epsilon': 1e-12,
}


def finite(value):
    try:
        return value is not None and not isinstance(value, bool) and math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def recalculate(state):
    rows = [dict(r) for r in state.diag_boxplots]
    trials = {t.source_id: t for t in state.review.trials}
    active = sorted(t.source_id for t in trials.values() if t.decision != 'REJECTED')
    raw = sorted((str(r.get('Trial_ID')), str(r.get('Source_Sheet')), str(r.get('Variable')),
                  float(r['Value']) if finite(r.get('Value')) else None) for r in rows)
    key = hashlib.sha256(json.dumps([RULES, FAMILIES, active, raw], ensure_ascii=False).encode()).hexdigest()
    if state.population.get('reference') == key:
        return state
    grouped = defaultdict(list)
    for row in rows:
        grouped[(str(row.get('Source_Sheet')), str(row.get('Variable')))].append(row)
    details = defaultdict(list)
    comparable = set()
    for (sheet, variable), group in grouped.items():
        ids = [str(r.get('Trial_ID')) for r in group]
        if len(ids) != len(set(ids)):
            raise ValueError('DIAG : doublon essai/indicateur : ' + variable)
        values = np.array([float(r['Value']) for r in group
                           if str(r.get('Trial_ID')) in active and finite(r.get('Value'))])
        base = _scalar_baseline(values, RULES['min_n'],
                                DIAG_ISO16269_4_IQR_WARN_K, DIAG_ISO16269_4_IQR_FAIL_K)
        usable = base['Method_Status'] == 'OK' and base['IQR'] > max(1., abs(base['Median'])) * RULES['iqr_relative_epsilon']
        eligible = variable in FAMILIES and sheet != 'DIAG_BALANCE'
        if usable and eligible:
            comparable.add(variable)
        for row in group:
            tid = str(row.get('Trial_ID')); included = tid in active
            row.update({k: float(v) if isinstance(v, (float, np.floating)) and math.isfinite(v)
                        else None if isinstance(v, (float, np.floating)) else v for k, v in base.items()})
            row['Population_Included'] = included
            row['Population_Reference'] = key
            value = float(row['Value']) if finite(row.get('Value')) else None
            z = _robust_z_value(value, base['Median'], base['MAD'], values) if value is not None else float('nan')
            level = 'NOT_EVALUATED'
            if included and value is not None and base['Method_Status'] == 'OK':
                level = 'OK'
                if value < base['Lower_Fence_Fail'] or value > base['Upper_Fence_Fail'] or (finite(z) and abs(z) >= DIAG_ISO16269_4_ROBUST_Z_FAIL):
                    level = 'FAIL'
                elif value < base['Lower_Fence_Warn'] or value > base['Upper_Fence_Warn'] or (finite(z) and abs(z) >= DIAG_ISO16269_4_ROBUST_Z_WARN):
                    level = 'WARNING'
            row.update(Outlier_Level=level if included else 'EXCLUDED',
                       Outlier_Flag=level in ('FAIL', 'WARNING') and included,
                       Robust_Z=float(z) if finite(z) else None,
                       Direction=('HIGH' if value is not None and finite(base['Median']) and value > base['Median'] else 'LOW'),
                       Comment_FR=('Hors population de référence' if not included else
                                   'Réévalué sur les essais non rejetés : ' + level))
            if eligible:
                distance = abs(value - base['Median']) / base['IQR'] if usable and value is not None else None
                penalty = (
                    min(1., max(0.,
                                (distance - RULES['distance_free'])
                                / (RULES['distance_full'] - RULES['distance_free'])
                                ))
                    if distance is not None else None
                )
                details[tid].append({'Variable': variable, 'Description': row.get('Description_FR', variable),
                    'Family': FAMILIES[variable], 'Value': value, 'Median': row['Median'], 'IQR': row['IQR'],
                    'N': len(values), 'Distance': distance, 'Penalty': penalty,
                    'Status': 'OK' if penalty is not None else ('TOO_FEW_VALUES' if len(values) < RULES['min_n'] else 'NON_DISCRIMINANT_OR_MISSING')})
    scores = {}
    for tid, trial in trials.items():
        valid = [d for d in details[tid] if d['Penalty'] is not None]
        groups = defaultdict(list)
        for d in valid:
            groups[d['Family']].append(d['Penalty'])
        coverage = len(valid) / len(comparable) if comparable else 0.
        sufficient = len(valid) >= RULES['min_indicators'] and len(groups) >= RULES['min_families'] and coverage >= RULES['min_coverage']
        score = None
        if sufficient and tid in active:
            mean = np.mean([np.mean(v) for v in groups.values()])
            score = float(100 * (
                    1
                    - RULES['mean_weight'] * mean
                    - RULES['worst_weight'] * max(d['Penalty'] for d in valid)
            ))
        previous = state.population.get('scores', {}).get(tid, {}).get('score')
        scores[tid] = {'score': score, 'previous': previous, 'count': len(valid),
                       'available': len(comparable), 'coverage': coverage,
                       'status': 'EXCLUDED' if tid not in active else 'OK' if sufficient else 'INSUFFICIENT_DATA',
                       'details': sorted(details[tid], key=lambda d: -(d['Penalty'] or 0.))}
    summaries = []
    for original in state.review_summary:
        row = dict(original); tid = str(row.get('Trial_ID')); trial = trials.get(tid)
        row['Score_Comportement_Global'] = trial.quality_score if trial else row.get('Quality_Score')
        row['Score_Comparatif_Population'] = scores.get(tid, {}).get('score')
        row['Population_Reference'] = key
        visible = [r for r in rows if str(r.get('Trial_ID')) == tid and r.get('Variable') in FAMILIES
                   and r.get('Source_Sheet') != 'DIAG_BALANCE' and r.get('Population_Included')]
        levels = [r['Outlier_Level'] for r in visible]
        row['ISO16269_4_Warning_Count'] = levels.count('WARNING')
        row['ISO16269_4_Fail_Count'] = levels.count('FAIL')
        row['ISO16269_4_Outlier_Count'] = levels.count('WARNING') + levels.count('FAIL')
        row['ISO16269_4_Max_Severity'] = ('FAIL' if 'FAIL' in levels else 'WARNING' if 'WARNING' in levels
                                           else 'OK' if 'OK' in levels else 'NOT_EVALUATED')
        summaries.append(row)
    return replace(state, diag_boxplots=tuple(rows), review_summary=tuple(summaries),
                   population={'reference': key, 'members': active, 'rules': RULES,
                               'families': FAMILIES, 'scores': scores})


def review_payload(state):
    payload = state.review.to_dict()
    for trial in payload['trials']:
        trial['Score_Comportement_Global'] = trial['quality_score']
        trial['population'] = state.population.get('scores', {}).get(trial['source_id'])
        trial['main_flags'] = [f for f in trial.get('main_flags', []) if f != 'ISO16269_4_OUTLIER']
    return payload
