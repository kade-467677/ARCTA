"""64E2 : dossier de réanalyse vérifié, sans calcul ni capitalisation."""
import json
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import DABCTA_64B_BASE as core
from .analysis_settings import validate_settings
from .dabcta_grouping import preflight

ACTION = 'PREPARE_REANALYSIS'
SETTING_KEYS = dict(zip(
    ('THR_RATIO_DEFAULT', 'ISO_TOL_P_CONTENT', 'ISO_TOL_CONF_LEVEL',
     'ISO_MEDIAN_CONF_LEVEL', 'NORMALITY_ALPHA', 'NORMALITY_MIN_N'),
    ('thr_ratio', 'iso_tol_p_content', 'iso_tol_conf_level',
     'iso_median_conf_level', 'normality_alpha', 'normality_min_n')))


def history(db, action=ACTION):
    return [{**json.loads(r['detail']), 'revision': r['revision'],
             'utc': r['utc'], 'actor': r['actor']}
            for r in db.execute('SELECT * FROM journal WHERE action=? ORDER BY revision DESC', (action,))]


def verify_packet(packet):
    root = Path(packet['directory']).resolve()
    for name, digest in packet['files_sha256'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or core.sha256(path) != digest:
            raise ValueError('Dossier préparé absent ou modifié : ' + name)


def prepare(db, database, body, *, rework=False):
    request_id = str(uuid.UUID(str(body.get('request_id', ''))))
    title = body.get('title')
    reason = body.get('reason')
    reference = body.get('settings_campaign')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        raise ValueError('Nom du dossier requis, de 1 à 120 caractères')
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
        raise ValueError('Motif du regroupement requis, de 1 à 2000 caractères')
    if not rework and body.get('independent') is not True:
        raise ValueError('Confirmer explicitement des acquisitions indépendantes')
    if type(reference) is not int:
        raise ValueError('Choisir la campagne portant les paramètres statistiques communs')
    request = {k: body.get(k) for k in ('campaigns', 'revision', 'settings_campaign',
                                       'title', 'reason', 'independent')}
    if rework:
        request.update(operation='REWORK', variant=body.get('variant'), scope=body.get('scope'))
    action = 'PREPARE_REWORK' if rework else ACTION
    request_hash = core.fingerprint(request)
    for previous in history(db, action):
        if previous['request_id'] == request_id:
            if previous['request_hash'] != request_hash:
                raise ValueError('Identifiant de demande déjà utilisé pour un autre choix')
            verify_packet(previous)
            return {**previous, 'reused': True}

    if rework:
        from .dabcta_rework import preflight_rework
        report = preflight_rework(db, body)
    else:
        report = preflight(db, body.get('campaigns'), body.get('revision'))
    if report['blockers']:
        raise ValueError('Regroupement refusé : ' + ' ; '.join(report['blockers']))
    if reference not in [c['id'] for c in report['campaigns']]:
        raise ValueError('La référence statistique doit appartenir aux campagnes choisies')
    snapshots = {}
    for campaign in report['campaigns']:
        row = db.execute('SELECT payload FROM variants WHERE id=?', (campaign['variant'],)).fetchone()
        snapshots[str(campaign['id'])] = json.loads(row[0])
    settings = snapshots[str(reference)]['inputs']['settings']
    if not set(SETTING_KEYS) <= settings.keys():
        raise ValueError('Les six paramètres statistiques archivés sont nécessaires')
    values = {v: settings[k] for k, v in SETTING_KEYS.items()}
    values['mean_ci_conf_level'] = settings.get('MEAN_CI_CONF_LEVEL', .95)
    values['subtract_selflock'] = settings.get('TORQUE_BASIS', 'TOTAL') == 'EFFECTIVE'
    checked = validate_settings(values)
    stamp = datetime.now(timezone.utc)
    base = Path(database).resolve().parent / ('RETRAITEMENTS' if rework else 'REANALYSES')
    base.mkdir(parents=True, exist_ok=True)
    label = re.sub(r'[^A-Za-z0-9_-]+', '_', title.strip()).strip('_')[:40] or 'campagnes'
    target = base / (stamp.strftime('%Y%m%d-%H%M') + '_' + label + '_' + request_id[:8])
    if target.exists():
        raise ValueError('Dossier cible déjà présent ; aucun écrasement autorisé')
    staging = Path(tempfile.mkdtemp(prefix='.preparation_', dir=base))
    owned_target = False
    try:
        files, trials = {}, []
        retained = sorted((s for s in report['sources'] if s['accepted']),
                          key=lambda s: (s['campaign'], str(s['name']).casefold(), str(s['trial'])))
        for index, source in enumerate(retained, 1):
            basename = re.split(r'[/\\]', str(source['name']))[-1]
            basename = re.sub(r'[^A-Za-z0-9._-]+', '_', basename)
            suffix = Path(basename).suffix.lower()
            if suffix not in {'.xlsx', '.xls', '.csv', '.txt'}:
                raise ValueError('Format source non pris en charge : ' + basename)
            name = f"essais/C{source['campaign']:06d}_{index:06d}_{Path(basename).stem[:65]}{suffix}"
            path = staging / name
            path.parent.mkdir(exist_ok=True)
            shutil.copyfile(source['path'], path)
            digest = core.sha256(path)
            if digest.lower() != source['sha256'].lower():
                raise ValueError('Source modifiée pendant la copie : ' + str(source['name']))
            files[name] = digest
            trials.append({**source, 'packet_path': name})
        plan = {'schema_version': 1, 'kind': 'ARCTA_REANALYSIS_PREPARATION',
                'status': 'A_REANALYSER', 'business_validation': 'NON_EXAMINE',
                'request_id': request_id, 'title': title.strip(), 'reason': reason.strip(),
                'created_at': stamp.isoformat(), 'database': str(Path(database).resolve()),
                'source_revision': report['revision'], 'campaigns': report['campaigns'],
                'settings_campaign': reference, 'analysis_settings': checked,
                'independence_declared': not rework, 'trials': trials,
                'operation': 'REWORK' if rework else 'AGGREGATION',
                'scope': body.get('scope') if rework else 'retained',
                'not_retained': [s for s in report['sources'] if not s['accepted']],
                'preflight': report, 'snapshots': snapshots}
        (staging / 'REANALYSE.json').write_text(core.dump(plan) + '\n', encoding='utf-8')
        (staging / 'LIRE_MOI.txt').write_text(
            'Dossier de préparation, pas un résultat ARCTA ni une validation métier.\n'
            'REANALYSE.json conserve les configurations, paramètres, décisions et filiations.\n'
            'essais/ contient les acquisitions du périmètre choisi, copiées sans transformation.\n'
            'Ouvrir ce dossier dans ARCTA depuis DABCTA pour reprendre le traitement.\n'
            'CONFIG, unités, mapping commun et nouvelle revue DIAG restent à vérifier.\n'
            'Ne pas additionner les résultats de ce regroupement à ceux de ses campagnes parentes.\n',
            encoding='utf-8')
        for name in ('REANALYSE.json', 'LIRE_MOI.txt'):
            files[name] = core.sha256(staging / name)
        packet = {'request_id': request_id, 'request_hash': request_hash,
                  'title': title.strip(), 'reason': reason.strip(), 'directory': str(target),
                  'campaigns': [c['id'] for c in report['campaigns']],
                  'variants': [c['variant'] for c in report['campaigns']],
                  'source_revision': report['revision'], 'settings_campaign': reference,
                  'trial_count': len(trials), 'files_sha256': files,
                  'operation': plan['operation'], 'scope': plan['scope']}
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT max(revision) FROM journal').fetchone()[0] != report['revision']:
                raise ValueError('La base a changé pendant la préparation ; recommencer')
            core.event(db, action, packet)
            new_revision = db.execute('SELECT max(revision) FROM journal').fetchone()[0]
            for attempt in range(7):
                try:
                    staging.rename(target)
                    break
                except PermissionError as exc:
                    if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 6:
                        raise
                    time.sleep(0.05 * (2 ** attempt))
            owned_target = True
        return {**packet, 'revision': new_revision, 'reused': False}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if owned_target and target.exists():
            shutil.rmtree(target)
        raise
