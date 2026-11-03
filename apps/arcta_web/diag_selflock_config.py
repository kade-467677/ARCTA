"""64G5 — rapprochement explicite CONFIG / autofrein DIAG retenu."""
import copy
import getpass
import hashlib
import json
import math
import statistics
from dataclasses import replace
from datetime import datetime, timezone

from .session_canonical_config import load_session_canonical_config, save_session_canonical_config

METRIC = 'Autofrein_Xg_preA0_med'
FIELDS = ('mean_nm', 'median_nm', 'std_nm', 'min_nm', 'max_nm', 'valid_count')
THRESHOLD = 0.05


def number(value):
    try:
        return float(value) if not isinstance(value, bool) and math.isfinite(float(value)) else None
    except (TypeError, ValueError):
        return None


def proposal(session, state):
    config = load_session_canonical_config(session)
    accepted = sorted(t.source_id for t in state.review.trials if t.decision == 'ACCEPTED')
    values = {}
    for row in state.diag_boxplots:
        tid = str(row.get('Trial_ID'))
        if row.get('Variable') != METRIC or tid not in accepted:
            continue
        if tid in values:
            raise ValueError('Autofrein DIAG : plusieurs valeurs pour un même essai.')
        values[tid] = number(row.get('Value'))
    valid = [v for v in values.values() if v is not None]
    stats = [None] * 5 + [len(valid)]
    if valid:
        stats = [statistics.mean(valid), statistics.median(valid),
                 statistics.stdev(valid) if len(valid) > 1 else None,
                 min(valid), max(valid), len(valid)]
    rows = []
    if config and config.config:
        for suffix, new in zip(FIELDS, stats):
            field = config.config.get_field('selflock_' + suffix)
            old = number(field.value)
            delta = abs(new - old) / abs(old) if old not in (None, 0) and new is not None else None
            changed = (new is not None and (old is None or
                       (new != old if suffix == 'valid_count' or old == 0 else delta > THRESHOLD + 1e-12)))
            rows.append({'field': field.field_id, 'label': field.to_dict()['label'],
                         'old': field.value, 'new': new, 'delta_percent': delta * 100 if delta is not None else None,
                         'change': changed, 'unavailable': new is None})
    data = {'method': METRIC, 'threshold_percent': 5, 'accepted': accepted,
            'valid_count': len(valid), 'missing_count': len(accepted) - len(valid), 'rows': rows}
    # Includes the complete review and CONFIG: stale confirmations cannot be reused.
    signature = [data, state.to_dict(), config.to_dict() if config else None]
    data['token'] = hashlib.sha256(json.dumps(signature, sort_keys=True, ensure_ascii=False,
                                              default=str).encode('utf-8')).hexdigest()
    data['requires_confirmation'] = any(r['change'] for r in rows)
    return data


def apply_proposal(session, state, token=None):
    data = proposal(session, state)
    if not data['requires_confirmation']:
        if token is not None and token != data['token']:
            raise ValueError('La revue ou la CONFIG a changé : vérifier à nouveau les valeurs.')
        return
    if token != data['token']:
        raise ValueError('Confirmer la mise à jour des autofreins CONFIG depuis le DIAG avant validation.')
    stored = load_session_canonical_config(session)
    config = copy.deepcopy(stored.config)
    timestamp = datetime.now(timezone.utc).isoformat()
    changes = []
    for row in data['rows']:
        if not row['change']:
            continue
        previous = config.get_field(row['field']).to_dict()
        config.set_field(row['field'], raw_value=row['new'], status='CONFIRMED',
                         unit='entier' if row['field'].endswith('count') else 'Nm',
                         source_file='DIAG', source_sheet='DIAG_AUTOFREIN', source_cell=METRIC,
                         transformation='Statistique inter-essais retenus ; écart-type échantillon (n-1)',
                         message=f"Confirmé le {timestamp} ; ancienne valeur : {row['old']} ; n={data['valid_count']}")
        changes.append({'previous': previous, 'new': row['new']})
    event = {'utc': timestamp, 'actor': getpass.getuser(), 'confirmation': 'EXPLICIT_USER',
             'proposal': data, 'changes': changes}
    # CONFIG and its audit history are committed together by one atomic replacement.
    save_session_canonical_config(session, replace(stored, config=config, updated_at=timestamp,
        selflock_history=stored.selflock_history + (event,)))
