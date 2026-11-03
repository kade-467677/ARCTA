"""64H1: invariance des polynômes archivés lors d'un changement d'intervalle.
Aucune écriture SQL. Ne certifie pas l'identité de courbes non archivées ici.
"""
import math
import DABCTA_64B_BASE as core
from DABCTA_64A_INVENTAIRE import validate_polynomial

DEPENDENCIES = {
    'MEAN_CI_CONF_LEVEL': {'MEAN_CI_LOW', 'MEAN_CI_HIGH'},
    'ISO_MEDIAN_CONF_LEVEL': {'MEDIAN_CI_LOW', 'MEDIAN_CI_HIGH',
        'MEDIAN_CI_CONF_TARGET', 'MEDIAN_CI_CONF_ACTUAL',
        'MEDIAN_CI_ORDER_LOW', 'MEDIAN_CI_ORDER_HIGH'},
    'ISO_TOL_P_CONTENT': {'TOL_PARAM_LOW', 'TOL_PARAM_HIGH', 'TOL_NP_LOW',
        'TOL_NP_HIGH', 'TOL_LOW', 'TOL_HIGH', 'TOL_P'},
    'ISO_TOL_CONF_LEVEL': {'TOL_PARAM_LOW', 'TOL_PARAM_HIGH', 'TOL_NP_LOW',
        'TOL_NP_HIGH', 'TOL_LOW', 'TOL_HIGH', 'TOL_CONF'},
}
ALIASES = {'CI95_LOW': 'MEAN_CI_LOW', 'CI95_HIGH': 'MEAN_CI_HIGH'}
RTOL, ATOL = 1e-10, 1e-12


def number_or_none(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    import math
    return result if math.isfinite(result) else None



def same(a, b, key=''):
    if isinstance(a, (float, int)) and not isinstance(a, bool) and isinstance(b, (float, int)) and not isinstance(b, bool):
        if not (math.isfinite(a) and math.isfinite(b)):
            return False
        return a == b if key in {'Degree', 'N'} else math.isclose(a, b, rel_tol=RTOL, abs_tol=ATOL)
    return core.normalized(a) == core.normalized(b)


def polynomial_index(candidate):
    indexed = {}
    for raw in candidate['run']['tables'].get('POLY_FITS_STATS', []):
        row = {k: v for k, v in raw.items() if k != 'DABCTA_category' and v is not None}
        row['Stat'] = ALIASES.get(row.get('Stat'), row.get('Stat'))
        validate_polynomial(row)
        # 64I1 : l'identité inclut le segment de validité S des tolérances.
        key = tuple(str(row[k]).strip() for k in ('Compute_Sheet', 'Type', 'Stat')
                    ) + (str(row.get('S', '')),)
        basis = row.get('Torque_Basis', 'TOTAL')
        modes = ('TOTAL', 'EFFECTIVE') if basis == 'BOTH' else (basis,)
        for mode in modes:
            identity = (mode + ' :: ' + key[0], *key[1:])
            if identity in indexed:
                raise ValueError('Identité polynomiale dupliquée, éventuellement après conversion CI95.')
            indexed[identity] = {**row, 'Torque_Basis': mode}
    if not indexed:
        raise ValueError('Polynômes absents : invariance non vérifiable.')
    return indexed


def check(old, new, settings):
    report = {'status': 'UNVERIFIABLE', 'scope': 'POLY_FITS_STATS',
              'checked': 0, 'differences': [], 'affected': [],
              'parameters': [{'key': k, 'before': old['inputs']['settings'].get(k),
                              'after': new['inputs']['settings'].get(k)} for k in settings],
              'rtol': RTOL, 'atol': ATOL}
    for parameter in report['parameters']:
        for value in (parameter['before'], parameter['after']):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
                report['message'] = 'Paramètre d’intervalle absent ou invalide : ' + parameter['key']
                return report
    try:
        left, right = polynomial_index(old), polynomial_index(new)
    except (ValueError, KeyError, TypeError) as exc:
        report['message'] = str(exc)
        return report
    permitted = set().union(*(DEPENDENCIES[k] for k in settings))
    # 64I1B : familles = (mode, Compute_Sheet) ; S est la 4e composante.
    families = {k[:2] for k in left} | {k[:2] for k in right}
    # At least one common physical central curve per family is indispensable.
    def mean_of(index, family):
        matches = [v for k, v in index.items() if k[:2] == family and k[2] == 'MEAN']
        if len(matches) > 1:
            raise ValueError('Polynôme MEAN dupliqué pour contrôler la famille : ' + ' / '.join(family))
        return matches[0] if matches else None
    for family in sorted(families):
        if mean_of(left, family) is None or mean_of(right, family) is None:
            report['message'] = 'Polynôme MEAN manquant pour contrôler la famille : ' + ' / '.join(family)
            return report
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key), right.get(key)
        # 64I1C : S est une métadonnée de segmentation, hors comparaison d'invariance.
        columns = sorted(k for k in set(a or {}) | set(b or {}) - {'S'}
                         if k != 'S' and not same((a or {}).get(k), (b or {}).get(k), k))
        change = 'ajouté' if a is None else 'absent du nouveau run' if b is None else 'modifié'
        identity = {'sheet': key[0], 'type': key[1], 'stat': key[2]}
        if key[2] in permitted:
            if columns:
                report['affected'].append({**identity, 'change': change})
            # Changing confidence cannot change the domain or sample grid.
            for row, source in ((a, left), (b, right)):
                if row is None:
                    continue
                mean = mean_of(source, key[:2])
                if mean is None:
                    report['differences'].append({**identity, 'columns': ['MEAN'],
                                                  'reason': 'Polynôme MEAN de référence absent de la famille'})
                    continue
                bad = [c for c in ('X_min', 'X_max', 'N') if not same(row.get(c), mean.get(c), c)]
                # 64I1D : contrôle de domaine vs MEAN.
                # Polynôme complet (sans S) : égalité stricte du domaine et de
                # la grille — un changement de confiance ne peut pas les altérer.
                # Segment de tolérance (avec S) : le domaine est structurellement
                # plus étroit ; on exige l'inclusion dans le domaine du MEAN
                # (jamais de débordement ni d'inversion), l'effectif pouvant
                # être réduit à celui du segment.
                segment = str(row.get('S', '') or '')
                if segment:
                    low_a, high_a = number_or_none(row.get('X_min')), number_or_none(row.get('X_max'))
                    low_m, high_m = number_or_none(mean.get('X_min')), number_or_none(mean.get('X_max'))
                    if (low_a is None or high_a is None or low_m is None or high_m is None
                            or low_a < low_m - 1e-9 * max(1.0, abs(low_m))
                            or high_a > high_m + 1e-9 * max(1.0, abs(high_m))
                            or low_a >= high_a):
                        report['differences'].append({**identity, 'columns': ['X_min', 'X_max'],
                                                      'reason': 'Segment de tolérance hors du domaine du polynôme MEAN'})
                else:
                    bad = [c for c in ('X_min', 'X_max', 'N') if not same(row.get(c), mean.get(c), c)]
                    if bad:
                        report['differences'].append({**identity, 'columns': bad, 'reason': 'Domaine/effectif différent du polynôme MEAN'})
            if a is not None and b is not None:
                bad = [c for c in ('X_min', 'X_max', 'N') if c in columns]
                if bad:
                    report['differences'].append({**identity, 'columns': bad, 'reason': 'Domaine/effectif modifié'})
        else:
            report['checked'] += 1
            if columns or a is None or b is None:
                report['differences'].append({**identity, 'columns': columns, 'reason': change})
    report['status'] = 'CONFLICT' if report['differences'] else 'PASSED'
    report['message'] = ('Des polynômes ou domaines supposés invariants diffèrent.' if report['differences'] else
                         'Invariance des polynômes non concernés vérifiée. Aucun contrôle des courbes non présentes dans cet export.')
    return report
