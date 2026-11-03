"""64H7 : paramètres géométriques de CONFIG, choix mécanique du RUN."""
from arcta.run_mechanics import MODEL, GEOMETRY_FIELDS, geometry, offsets
from .session_canonical_config import load_session_canonical_config
import pandas as pd


def geometry_snapshot(session):
    state = load_session_canonical_config(session)
    if state is None or state.config is None:
        return {}  # Compatibilité avec les sessions API historiques.
    return {k: state.config.get_field(k).value for k in GEOMETRY_FIELDS}


def complete_constants(session, constants):
    result = dict(constants)
    values = geometry_snapshot(session)
    # Hypothèses historiques explicitement archivées si CONFIG canonique absente.
    result.update({k:v for k,v in values.items() if v is not None and v != ''})
    if 'thread_half_angle_deg' not in result:
        if values: raise ValueError('Demi-angle du flanc chargé manquant dans CONFIG')
        result['thread_half_angle_deg'] = 30.
    result.setdefault('bearing_geometry', 'plate')
    result.setdefault('thread_lead_mm', result.get('p'))
    result['kk_model'] = MODEL
    geometry(result)
    return result


def check_autofrein(review, accepted):
    offsets({'DIAG_SUMMARY':pd.DataFrame(review.review_summary)}, accepted)
