"""64H9C : repli explicite au RUN, sans modifier le DIAG mesuré."""
import json
import math
from statistics import median
import pandas as pd

WINDOW = 'A0_MINUS_3_TO_MINUS_1_TURNS_V1'
POLICY = 'MEDIAN_VALID_2OF3_V1'


def valid_number(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value)) and float(value) >= 0
    except (TypeError, ValueError, OverflowError):
        return False


def resolve_selflock(diag, ids):
    ids = [str(t) for t in ids]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Autofrein : liste des essais retenus vide ou dupliquée')
    frame = diag.get('DIAG_AUTOFREIN')
    if frame is None or frame.empty:
        frame = diag.get('DIAG_SUMMARY', pd.DataFrame())
    measured, reasons = {}, {}
    for tid in ids:
        rows = frame[frame.Trial_ID.astype(str) == tid] if 'Trial_ID' in frame else pd.DataFrame()
        if len(rows) != 1:
            raise ValueError('Autofrein absent/ambigu pour '+tid+' : relancer le DIAG')
        row = rows.iloc[0]
        if row.get('Autofrein_Window_Mode') != WINDOW:
            raise ValueError('Autofrein de méthode ancienne/inconnue pour '+tid+' : relancer le DIAG')
        status = str(row.get('Autofrein_Status', 'MISSING_STATUS'))
        value = row.get('Autofrein_Xg_preA0_med')
        if status == 'VALID' and valid_number(value):
            measured[tid] = float(value)
            reasons[tid] = 'VALID'
        else:
            reasons[tid] = status if status != 'VALID' else 'INVALID_VALUE'
    n, nv = len(ids), len(measured)
    required = (2*n + 2)//3
    if nv < required:
        raise ValueError(f'Autofrein : {nv}/{n} essais retenus mesurables ; au moins {required}/{n} requis (2/3). Relancer/vérifier le DIAG ou revoir les essais retenus.')
    middle = float(median(measured.values()))
    donors = json.dumps(sorted(measured), ensure_ascii=False, separators=(',', ':'))
    audit = pd.DataFrame([{
        'Trial_ID': tid, 'Autofrein_Nm': measured.get(tid, middle),
        'Method': WINDOW, 'Torque_Basis': 'EFFECTIVE',
        'Channels': 'T et T_th ; T_b inchangé', 'Policy': POLICY,
        'Origin': 'MEASURED' if tid in measured else 'IMPUTED_MEDIAN',
        'Diag_Status': reasons[tid], 'Measured_N': nv, 'Retained_N': n,
        'Reference_Median_Nm': middle, 'Donor_Trial_IDs': donors,
    } for tid in ids])
    return audit


def audit_message(audit):
    if audit.empty or 'Origin' not in audit:
        return ''
    nv = int((audit.Origin == 'MEASURED').sum())
    ni = len(audit) - nv
    message = f'Autofrein : {nv}/{len(audit)} mesurés ; {ni} attribué(s) par médiane'
    if ni:
        message += f' = {float(audit.iloc[0].Reference_Median_Nm):.2f} N.m'
    return message + '.'


def validate_audit(rows, policy):
    """Valide la provenance nouvelle ; les archives sans cette règle restent lisibles."""
    marked = any(r.get('Policy') or r.get('Origin') for r in rows)
    if not policy and not marked:
        return
    if policy != POLICY or not rows or any(r.get('Policy') != POLICY for r in rows):
        raise ValueError('Politique de repli autofrein absente ou inconnue')
    ids = [str(r['Trial_ID']) for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Autofrein : identifiants dupliqués')
    donors = sorted(str(r['Trial_ID']) for r in rows if r.get('Origin') == 'MEASURED')
    nv, n = len(donors), len(rows)
    if 3*nv < 2*n or not nv:
        raise ValueError('Autofrein : seuil des 2/3 non respecté')
    middle = float(median(float(r['Autofrein_Nm']) for r in rows if r.get('Origin') == 'MEASURED'))
    for row in rows:
        origin = row.get('Origin')
        if (origin not in {'MEASURED', 'IMPUTED_MEDIAN'} or not valid_number(row.get('Autofrein_Nm'))
                or row.get('Measured_N') != nv or row.get('Retained_N') != n):
            raise ValueError('Provenance autofrein incohérente')
        try:
            reference_ok = math.isclose(float(row['Reference_Median_Nm']), middle, rel_tol=1e-12, abs_tol=1e-12)
            donors_ok = sorted(json.loads(row['Donor_Trial_IDs'])) == donors
        except (KeyError, TypeError, ValueError):
            reference_ok = donors_ok = False
        if not reference_ok or not donors_ok:
            raise ValueError('Référence médiane autofrein incohérente')
        if origin == 'MEASURED' and row.get('Diag_Status') != 'VALID':
            raise ValueError('Autofrein attribué présenté comme mesuré')
        if origin == 'IMPUTED_MEDIAN' and (not row.get('Diag_Status') or row['Diag_Status'] == 'VALID'
                or not math.isclose(float(row['Autofrein_Nm']), middle, rel_tol=1e-12, abs_tol=1e-12)):
            raise ValueError('Valeur attribuée par médiane incohérente')
