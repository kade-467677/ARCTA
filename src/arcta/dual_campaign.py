"""64H9 : deux lectures mécaniques d'une même acquisition et d'un même run."""
from dataclasses import replace
import pandas as pd
from .analysis_config import DEFAULT_ARCTA_ANALYSIS_CONFIG
from .campaign import (ArctaCampaignResult, analyze_campaign, build_arcta_settings_sheet,
                       DIAG_AUDIT_SHEETS)
from .service import analyze_in_memory
from .run_mechanics import offsets, settings_rows, WINDOW
from .profiles import require_profile_config
from .tolerance import tolerance_warnings
from .tolerance_explanations import tolerance_details

MODES = ('TOTAL', 'EFFECTIVE')
CONTRACT = 'DUAL_SELFLOCK_64H9'


def for_mode(rows, basis):
    """Anciennes lignes sans convention = TOTAL ; BOTH = objet partagé exact."""
    if basis not in MODES:
        raise ValueError('Choisir TOTAL ou EFFECTIVE')
    return [r for r in rows if r.get('Torque_Basis', 'TOTAL') in (basis, 'BOTH')]


def paired_polynomials(total, effective):
    """Partage exact des objets invariants ; aucun arrondi ni réajustement."""
    def index(frame):
        result = {}
        for row in frame.to_dict('records'):
            row = {k: v for k, v in row.items() if k != 'Torque_Basis' and not pd.isna(v)}
            # 64I1B : l'identité inclut le segment de validité S des tolérances.
            key = tuple(row.get(k) for k in ('Compute_Sheet', 'Type', 'Stat', 'S'))
            if key in result:
                raise ValueError('Polynôme dupliqué avant association des modes')
            result[key] = row
        return result
    a, b = index(total), index(effective)
    rows = []
    for key in sorted(a.keys() | b.keys()):
        if key in a and key in b and a[key] == b[key]:
            rows.append({**a[key], 'Torque_Basis': 'BOTH'})
        else:
            for basis, data in (('TOTAL', a), ('EFFECTIVE', b)):
                if key in data:
                    rows.append({**data[key], 'Torque_Basis': basis})
    return pd.DataFrame(rows)


def analyze_dual_campaign(import_sheets, sel, diag, accepted, constants, profile,
                          analysis_config=DEFAULT_ARCTA_ANALYSIS_CONFIG,
                          progress=None, template_sheets=None):
    cfg = require_profile_config(profile)
    dual = bool(cfg.get('do_compute') or cfg.get('do_mu'))
    if dual:
        from .selflock_policy import resolve_selflock
        audit = resolve_selflock(diag, accepted)  # Décision commune aux deux modes.
    total = analyze_campaign(import_sheets, sel, diag, accepted, constants, profile,
        replace(analysis_config, subtract_selflock=False),
        (lambda p, msg: progress(p * .5, 'TOTAL — ' + msg)) if progress and dual else progress,
        template_sheets)
    if not dual:
        return total  # DIAG_CONCAT_ONLY ne produit aucune relation mécanique.
    total.result_sheets['ARCTA_SELFLOCK_CORRECTION'] = audit.copy(deep=True)
    effective_config = replace(analysis_config, subtract_selflock=True)
    # On réutilise exactement le découpage expérimental, sans redétecter Fmax/A0.
    sheets = {k: v.copy(deep=True) for k, v in total.result_sheets.items()
              if k in DIAG_AUDIT_SHEETS or k in ('CONCAT', 'CONCAT_CLEAN',
                  'ARCTA_COLUMN_MAP', 'DIAG_DEFINITIONS', 'TEMPLATESYNTH_CONSTANTS')
              or k in (template_sheets or {})}
    sheets.update(analyze_in_memory(total.result_sheets['CONCAT_CLEAN'].copy(deep=True),
        dict(constants), profile, diag=dict(diag), analysis_config=effective_config,
        progress=(lambda p, msg: progress(50 + p * .5, 'EFFECTIVE — ' + msg)) if progress else None))
    sheets['ARCTA_SETTINGS'] = pd.concat([build_arcta_settings_sheet(effective_config),
        settings_rows(constants, True)], ignore_index=True)
    for name in ('POLY_FITS', 'POLY_FITS_STATS'):
        if name in sheets:
            sheets[name]['Torque_Basis'] = 'EFFECTIVE'
            sheets[name]['KK_Model'] = constants.get('kk_model', 'LEGACY_0577')
    sheets['ARCTA_TOLERANCE_WARNINGS'] = tolerance_warnings(sheets)
    sheets['ARCTA_TOLERANCE_DETAILS'] = tolerance_details(sheets)
    effective = ArctaCampaignResult(total.profile, total.mode, dict(constants), sheets)
    return ArctaCampaignResult(total.profile, total.mode, dict(constants), total.result_sheets,
                               {'TOTAL': total, 'EFFECTIVE': effective})


def index_sheets(campaign):
    """Classeur racine de capitalisation ; les classeurs complets restent par mode."""
    total, effective = [campaign.mechanical_results[k].result_sheets for k in MODES]
    common = ('ARCTA_COLUMN_MAP', 'ARCTA_SELF_LOCK_STATS', 'DIAG_REVIEW')
    sheets = {k: total[k].copy(deep=True) for k in common if k in total}
    settings = total['ARCTA_SETTINGS'].copy(deep=True)
    settings.loc[settings.Parameter == 'TORQUE_BASIS', 'Value'] = 'DUAL'
    settings.loc[settings.Parameter == 'SELFLOCK_METHOD', 'Value'] = WINDOW
    sheets['ARCTA_SETTINGS'] = settings
    sheets['ARCTA_SELFLOCK_CORRECTION'] = effective['ARCTA_SELFLOCK_CORRECTION'].copy(deep=True)
    empty = pd.DataFrame()
    sheets['POLY_FITS_STATS'] = paired_polynomials(total.get('POLY_FITS_STATS', empty),
                                                   effective.get('POLY_FITS_STATS', empty))
    for name in ('ARCTA_TOLERANCE_DETAILS', 'ARCTA_TOLERANCE_WARNINGS'):
        frames = [s[name].assign(Torque_Basis=b) for b, s in zip(MODES, (total, effective))
                  if name in s and not s[name].empty]
        if frames:
            sheets[name] = pd.concat(frames, ignore_index=True)
    sheets['ARCTA_MECHANICAL_MODES'] = pd.DataFrame([
        {'Torque_Basis': b, 'Workbook': b + '/result.xlsx', 'Status': 'COMPLETE',
         'Contract': CONTRACT, 'Correction': 'T et T_th' if b == 'EFFECTIVE' else 'Aucune'}
        for b in MODES])
    return sheets


def validate_dual_export(tables, root, manifest):
    """Vérifie la paire de classeurs scellée dans l'index et le manifeste."""
    import hashlib
    rows = tables.get('ARCTA_MECHANICAL_MODES', [])
    if len(rows) != 2 or {r.get('Torque_Basis') for r in rows} != set(MODES):
        raise ValueError('Paire TOTAL/EFFECTIVE incomplète')
    for row in rows:
        basis = row['Torque_Basis']
        relative = basis + '/result.xlsx'
        if (row.get('Status') != 'COMPLETE' or row.get('Contract') != CONTRACT
                or row.get('Workbook') != relative):
            raise ValueError('Contrat des modes mécaniques invalide')
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or (root / basis).is_symlink():
            raise ValueError('Classeur mécanique hors dossier attendu')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != row.get('Workbook_SHA256') or digest != manifest.get('files_sha256', {}).get(relative):
            raise ValueError('Classeur ' + basis + ' différent du manifeste/index')
        if not any(r.get('Type') == 'TEST_YfXg' and r.get('Stat') == 'MEAN'
                   for r in for_mode(tables['POLY_FITS_STATS'], basis)):
            raise ValueError('Polynôme moyen couple–tension absent : ' + basis)
