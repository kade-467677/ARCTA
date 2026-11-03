"""64E3 : dossier DABCTA -> session ARCTA en brouillon, avec filiation."""
import csv
import io
import json
import shutil
from pathlib import Path

import DABCTA_64B_BASE as core
from cta_core.config_model.canonical import CanonicalCampaignConfig, CANONICAL_FIELD_SPEC_BY_ID
from . import analysis_settings
from .canonical_config_editor import canonical_to_legacy_config
from .dabcta_reanalysis import history, verify_packet
from .session_canonical_config import ArctaSessionCanonicalConfig, save_session_canonical_config, _atomic_write
from .session_config import save_session_config

PROFILE = 'DABCTA_REANALYSIS_V1'
CONFIG_NAME = 'DABCTA_REANALYSE.csv'
LINEAGE_NAME = 'arcta_reanalysis_lineage.json'
ACTION = 'OPEN_REANALYSIS_ARCTA'


def config_bytes(plan):
    ref = str(plan['settings_campaign'])
    rows = plan['snapshots'][ref]['run']['tables']['ARCTA_CONFIG_SYNTHESIS']
    config_rows = [r for r in rows if r.get('Section') == 'Configuration']
    if not config_rows:
        raise ValueError('Configuration canonique archivée absente du dossier')
    fields = {}
    for row in config_rows:
        key = row['Code']
        if key not in CANONICAL_FIELD_SPEC_BY_ID or key in fields:
            raise ValueError('Champ CONFIG inconnu ou dupliqué : ' + str(key))
        fields[key] = [row.get('Valeur'), row.get('Unité') or '',
                       'AMBIGUOUS' if row.get('Statut') == 'AMBIGUOUS' else 'EXTRACTED']
    if plan.get('operation') != 'REWORK':
        # Les métadonnées d'une campagne parente ne décrivent pas l'agrégat.
        for key in core.META - {'entity', 'program_id', 'configuration_id'}:
            if key in CANONICAL_FIELD_SPEC_BY_ID:
                fields[key] = [None, '', 'MISSING']
        for key in ('entity', 'program_id', 'configuration_id'):
            values = [c['metadata'].get(key) for c in plan['campaigns']]
            common = values[0] if values and all(v == values[0] for v in values) else None
            fields[key] = [common, '', 'EXTRACTED' if common is not None else 'MISSING']
        names = [str(c['metadata'].get('configuration_id') or '').strip() for c in plan['campaigns']]
        joined = '+'.join(names) if names and all(names) else None
        fields['configuration_id'] = [joined, '', 'EXTRACTED' if joined else 'MISSING']
        fields['report_number'] = [plan['title'], '', 'EXTRACTED']
    fields['sample_count'] = [len(plan['trials']), '', 'EXTRACTED']
    for key in CANONICAL_FIELD_SPEC_BY_ID:
        if key.startswith('selflock_'):
            fields[key] = [None, '', 'MISSING']
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([PROFILE])
    writer.writerow(['field_id', 'value_json', 'unit', 'status'])
    for key, (value, unit, status) in sorted(fields.items()):
        writer.writerow([key, core.dump(value), unit, status])
    return output.getvalue().encode('utf-8')


def read_config(session_id, content):
    reader = csv.reader(io.StringIO(content.decode('utf-8-sig'), newline=''))
    if next(reader, None) != [PROFILE] or next(reader, None) != ['field_id','value_json','unit','status']:
        raise ValueError('Source CONFIG de réanalyse invalide')
    config = CanonicalCampaignConfig(campaign_id=session_id, source_profile=PROFILE)
    seen = set()
    for row in reader:
        if len(row) != 4 or row[0] in seen:
            raise ValueError('Ligne CONFIG de réanalyse invalide ou dupliquée')
        key, value, unit, status = row
        seen.add(key)
        config.set_field(key, raw_value=json.loads(value), unit=unit, status=status,
                         source_file=CONFIG_NAME, transformation='Instantané DABCTA à revoir')
    return config


def extract_config(session, source):
    config = read_config(session.session_id, source.storage_path.read_bytes())
    state = ArctaSessionCanonicalConfig(
        source_id=source.source_id, source_original_name=source.original_name,
        source_sha256=source.sha256, status='EXTRACTED', source_profile=PROFILE,
        config=config, workflow_status='DRAFT',
        warnings=('Reprise DABCTA : revoir CONFIG, paramètres, mapping et décisions DIAG avant tout nouveau calcul.',))
    return save_session_canonical_config(session, state)


def open_session(db, database, registry, body):
    if type(body.get('revision')) is not int:
        raise ValueError('Révision de base obligatoire')
    packet_id = body.get('request_id')
    packets = history(db) + history(db, 'PREPARE_REWORK')
    packet = next((p for p in packets if p['request_id'] == packet_id), None)
    if packet is None:
        raise ValueError('Dossier de réanalyse inconnu')
    action = 'OPEN_REWORK_ARCTA' if packet.get('operation') == 'REWORK' else ACTION
    verify_packet(packet)
    root = Path(packet['directory']).resolve()
    plan = json.loads((root/'REANALYSE.json').read_text(encoding='utf-8'))
    if plan.get('request_id') != packet_id or plan.get('kind') != 'ARCTA_REANALYSIS_PREPARATION':
        raise ValueError('Identité du dossier de réanalyse incohérente')
    for row in db.execute('SELECT detail FROM journal WHERE action=? ORDER BY revision DESC', (action,)):
        previous = json.loads(row[0])
        if previous['request_id'] == packet_id:
            try:
                session = registry.get_session(previous['session_id'])
            except KeyError:
                raise ValueError('Session ARCTA précédente absente ; restauration nécessaire')
            marker = json.loads((Path(session.storage_dir)/LINEAGE_NAME).read_text(encoding='utf-8'))
            if marker.get('request_id') != packet_id:
                raise ValueError('Filiation de la session ARCTA incohérente')
            return {'session_id': session.session_id, 'url': f'/sessions/{session.session_id}/config', 'reused': True}
    if db.execute('SELECT max(revision) FROM journal').fetchone()[0] != body['revision']:
        raise ValueError('La base a changé ; actualiser avant ouverture ARCTA')
    content = config_bytes(plan)
    read_config('preflight', content)
    values = analysis_settings.validate_settings(plan['analysis_settings'])
    session = registry.create_session()
    try:
        links, source_paths = [], {}
        for trial in plan['trials']:
            relative = trial['packet_path']
            path = (root/relative).resolve()
            if not path.is_relative_to(root) or relative not in packet['files_sha256']:
                raise ValueError('Chemin d’essai absent du dossier vérifié')
            data = path.read_bytes()
            if core.hashlib.sha256(data).hexdigest() != packet['files_sha256'][relative]:
                raise ValueError('Essai modifié pendant l’import ARCTA')
            source = registry.add_source_bytes(session.session_id, path.name, data, source_kind='TRIAL')
            source_paths[source.source_id] = str(path)
            links.append({**trial, 'arcta_source_id': source.source_id,
                          'arcta_source_name': source.original_name})
        source = registry.add_source_bytes(session.session_id, CONFIG_NAME, content, source_kind='CONFIG')
        state = extract_config(session, source)
        save_session_config(session, canonical_to_legacy_config(state.config), status='DRAFT',
                            template_source_id=source.source_id)
        analysis_settings._write(session, values, 'dabcta_reanalysis')
        lineage = {k: plan[k] for k in ('request_id','title','reason','campaigns','source_revision','settings_campaign','not_retained')}
        lineage.update(schema_version=1, operation=plan.get('operation', 'AGGREGATION'),
                       scope=plan.get('scope', 'retained'), database=str(Path(database).resolve()),
                       packet_directory=str(root), packet_sha256=packet['files_sha256']['REANALYSE.json'],
                       business_validation='NON_EXAMINE', trials=links)
        _atomic_write(Path(session.storage_dir)/LINEAGE_NAME, lineage)
        _atomic_write(Path(session.storage_dir)/'output_directory.json',
                      {'source_directory':str(root), 'origin_directory':str(root),
                       'destination_directory':str(root), 'source_paths':source_paths})
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT max(revision) FROM journal').fetchone()[0] != body['revision']:
                raise ValueError('La base a changé pendant l’import ARCTA ; recommencer')
            core.event(db, action, {'request_id':packet_id, 'session_id':session.session_id,
                                   'packet_sha256':lineage['packet_sha256'], 'reason':plan['reason']})
        return {'session_id':session.session_id, 'url':f'/sessions/{session.session_id}/config', 'reused':False}
    except Exception:
        with registry._lock:
            registry._sessions.pop(session.session_id, None)
        shutil.rmtree(session.storage_dir)
        raise


def lineage(session):
    path = Path(session.storage_dir)/LINEAGE_NAME
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def export_lineage(session, sheets):
    data = lineage(session)
    if data is None:
        return
    import pandas as pd
    identities = {r['Source_ID_Technical']:r['Trial_ID'] for r in
                  sheets['ARCTA_SOURCES'].to_dict(orient='records')}
    parents = {c['id']:c for c in data['campaigns']}
    sheets['ARCTA_LINEAGE'] = pd.DataFrame([
        {'Trial_ID':identities.get(t['arcta_source_id']), 'Source_Name':t['arcta_source_name'],
         'Parent_Campaign':t['campaign'], 'Parent_Variant':t['variant'],
         'Parent_Run':parents[t['campaign']]['run'], 'Parent_Trial':t['trial'],
         'Parent_Source_Name':t['name'], 'SHA256':t['sha256'], 'Preparation_ID':data['request_id']}
        for t in data['trials']])
