"""Capitalisation transactionnelle des réanalyses, sans double comptage des parents."""
import json
from pathlib import Path
import DABCTA_64B_BASE as core
from DABCTA_64A_INVENTAIRE import read_run


def links(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reanalysis_links'").fetchone():
        return []
    return [dict(r) for r in db.execute('SELECT * FROM reanalysis_links ORDER BY parent_id')]


def protected(db, campaign_id):
    from DABCTA_64F1_QUALIFICATION import enabled
    from DABCTA_64F4_EXPLOITATION import eligible
    return any(campaign_id==r['aggregate_id'] or
               (campaign_id==r['parent_id'] and (not enabled(db) or eligible(db,r['aggregate_id'])))
               for r in links(db))


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS reanalysis_links(
        parent_id INTEGER PRIMARY KEY REFERENCES campaigns(id),
        parent_variant INTEGER NOT NULL REFERENCES variants(id),
        aggregate_id INTEGER NOT NULL REFERENCES campaigns(id),
        aggregate_variant INTEGER NOT NULL REFERENCES variants(id),
        request_id TEXT NOT NULL, CHECK(parent_id != aggregate_id))''')
    from DABCTA_64F1_QUALIFICATION import enabled
    predicate=" AND EXISTS(SELECT 1 FROM active a WHERE a.campaign_id=aggregate_id AND a.variant_id IN (SELECT id FROM qualified_variants))" if enabled(db) else ''
    for op in ('INSERT', 'UPDATE'):
        db.execute('DROP TRIGGER IF EXISTS reanalysis_guard_'+op.lower())
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS reanalysis_guard_{op.lower()}
            BEFORE {op} ON active WHEN
            EXISTS(SELECT 1 FROM reanalysis_links WHERE parent_id=NEW.campaign_id{predicate})
            OR EXISTS(SELECT 1 FROM reanalysis_links WHERE aggregate_id=NEW.campaign_id
                      AND aggregate_variant != NEW.variant_id)
            BEGIN SELECT RAISE(ABORT,'Filiation : campagne protegee par un regroupement'); END''')


def inspect(db, candidate):
    lineage = candidate['run']['manifest'].get('arcta_reanalysis')
    if not isinstance(lineage, dict) or lineage.get('schema_version') != 1:
        raise ValueError('Filiation de réanalyse absente ou non prise en charge')
    request_id = lineage.get('request_id')
    preparations = [json.loads(r[0]) for r in db.execute(
        "SELECT detail FROM journal WHERE action='PREPARE_REANALYSIS'")]
    packet = next((p for p in preparations if p['request_id'] == request_id), None)
    if packet is None:
        raise ValueError('Préparation de réanalyse inconnue dans cette base')
    if lineage.get('packet_sha256') != packet['files_sha256']['REANALYSE.json']:
        raise ValueError('Empreintes de préparation différentes du journal')
    if not any(json.loads(r[0]).get('request_id') == request_id and
               json.loads(r[0]).get('packet_sha256') == packet['files_sha256']['REANALYSE.json']
               for r in db.execute("SELECT detail FROM journal WHERE action='OPEN_REANALYSIS_ARCTA'")):
        raise ValueError('Ouverture ARCTA de cette préparation non tracée')
    plan_path = Path(packet['directory']) / 'REANALYSE.json'
    if core.sha256(plan_path) != packet['files_sha256']['REANALYSE.json']:
        raise ValueError('Plan de préparation absent ou modifié')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if lineage.get('campaigns') != plan['campaigns']:
        raise ValueError('Campagnes parentes différentes de la préparation')
    expected = {(s['campaign'], str(s['trial']), s['sha256'].lower()) for s in plan['trials']}
    inherited = lineage.get('trials', [])
    actual = {(s['campaign'], str(s['trial']), s['sha256'].lower()) for s in inherited}
    if actual != expected or len(inherited) != len(expected):
        raise ValueError('Essais de filiation différents de la préparation')
    by_id = {s['arcta_source_id']: s for s in inherited}
    if len(by_id) != len(inherited):
        raise ValueError('Identifiants sources de filiation dupliqués')
    sources = candidate['run']['tables']['ARCTA_SOURCES']
    if len(sources) != len(by_id) or {s.get('Source_ID_Technical') for s in sources} != set(by_id):
        raise ValueError('Sources du résultat différentes du dossier de réanalyse')
    retained = set()
    for source in sources:
        parent = by_id[source['Source_ID_Technical']]
        if source['SHA256'].lower() != parent['sha256'].lower():
            raise ValueError('Empreinte source différente de sa filiation')
        if source.get('Accepted_For_ARCTA') is True:
            retained.add(parent['campaign'])
    parent_ids = packet['campaigns']
    if retained != set(parent_ids):
        raise ValueError('Au moins un essai retenu de chaque campagne parente est nécessaire')
    parents = []
    for cid, vid in zip(parent_ids, packet['variants']):
        row = db.execute('SELECT c.*,a.variant_id FROM campaigns c LEFT JOIN active a ON a.campaign_id=c.id WHERE c.id=?', (cid,)).fetchone()
        if row is None or row['variant_id'] != vid or protected(db, cid):
            raise ValueError('Campagne parente modifiée ou déjà regroupée : ' + str(cid))
        if row['config_id'] != candidate['config_key']:
            raise ValueError('Configuration physique différente de la campagne parente : ' + str(cid))
        payload = json.loads(db.execute('SELECT payload FROM variants WHERE id=?', (vid,)).fetchone()[0])
        from DABCTA_64F1_QUALIFICATION import require
        require(db, payload)
        selected = {s['SHA256'].lower() for s in payload['run']['tables']['ARCTA_SOURCES'] if s.get('Accepted_For_ARCTA') is True}
        planned = {s['sha256'].lower() for s in plan['trials'] if s['campaign'] == cid}
        if selected != planned:
            raise ValueError('Acquisitions parentes différentes de la préparation')
        parents.append({'id': cid, 'variant': vid, 'label': row['label']})
    if len(parents) < 2 or len(set(parent_ids)) != len(parents):
        raise ValueError('Au moins deux parents distincts sont nécessaires')
    # Un autre résultat courant ne doit pas exploiter ces mêmes acquisitions.
    occupied = {s['SHA256'].lower() for s in sources if s.get('Accepted_For_ARCTA') is True}
    for row in db.execute('SELECT a.campaign_id,v.payload FROM active a JOIN variants v ON v.id=a.variant_id'):
        from DABCTA_64F4_EXPLOITATION import eligible
        if row['campaign_id'] not in parent_ids and eligible(db,row['campaign_id']):
            other = json.loads(row['payload'])
            hashes = {s['SHA256'].lower() for s in other['run']['tables']['ARCTA_SOURCES'] if s.get('Accepted_For_ARCTA') is True}
            if occupied & hashes:
                raise ValueError('Acquisitions déjà exploitées par la campagne ' + str(row['campaign_id']))
    return {'request_id': request_id, 'parents': parents, 'retained_count': candidate['run']['accepted_count'],
            'excluded_count': len(sources) - candidate['run']['accepted_count']}


def preview(db, candidate):
    try:
        return {**inspect(db, candidate), 'ready': True, 'error': ''}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {'ready': False, 'error': str(exc), 'parents': []}


def capitalize(db, candidate, body):
    if type(body.get('revision')) is not int or body.get('confirm_parents') is not True:
        raise ValueError('Révision et confirmation du remplacement des parents obligatoires')
    reason, label = body.get('reason'), body.get('label')
    if not isinstance(reason, str) or not reason.strip() or not isinstance(label, str) or not label.strip():
        raise ValueError('Nom du regroupement et motif obligatoires')
    # Relire le manifeste ET le classeur : le candidat affiché peut être devenu obsolète.
    fresh_run = read_run(Path(candidate['run']['copies'][0]) / 'ARCTA_RUN_MANIFEST.json')
    if (fresh_run['run_id'], fresh_run['xlsx_sha256'], fresh_run['manifest']) != (
        candidate['run']['run_id'], candidate['run']['xlsx_sha256'], candidate['run']['manifest']):
        raise ValueError('Export modifié depuis son inventaire')
    fresh = core.prepare(fresh_run, allow_reanalysis=True)
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT max(revision) FROM journal').fetchone()[0] != body['revision']:
            raise ValueError('La base a changé : actualiser avant de capitaliser')
        known = core.known(db, fresh)
        if known:
            return
        from DABCTA_64F1_QUALIFICATION import require
        require(db, fresh, check_files=True)
        detail = inspect(db, fresh)
        ensure_schema(db)
        cid = db.execute('INSERT INTO campaigns(config_id,label,metadata) VALUES(?,?,?)',
                         (fresh['config_key'], label.strip(), core.dump(fresh['campaign_metadata']))).lastrowid
        vid = db.execute('INSERT INTO variants(campaign_id,input_key,result_key,payload) VALUES(?,?,?,?)',
                         (cid, fresh['input_key'], fresh['result_key'], core.dump(fresh))).lastrowid
        db.executemany('INSERT INTO polynomials VALUES(?,?,?,?,?)',
                       [(vid,p['Type'],p['Stat'],p['DABCTA_category'],core.dump(p)) for p in fresh_run['tables']['POLY_FITS_STATS']])
        for parent in detail['parents']:
            db.execute('DELETE FROM active WHERE campaign_id=?', (parent['id'],))
            db.execute('INSERT INTO reanalysis_links VALUES(?,?,?,?,?)',
                       (parent['id'], parent['variant'], cid, vid, detail['request_id']))
        db.execute('INSERT INTO active VALUES(?,?)', (cid, vid))
        db.execute('INSERT INTO origins VALUES(?,?,?,?,?)',
                   (fresh_run['run_id'],fresh_run['xlsx_sha256'],vid,'CAPITALIZE_REANALYSIS',core.dump(fresh)))
        core.event(db, 'CAPITALIZE_REANALYSIS', {**detail, 'campaign':cid, 'candidate':vid,
                   'run':fresh_run['run_id'], 'reason':reason.strip(), 'business_validation':__import__('DABCTA_64F1_QUALIFICATION').state(db,fresh)['status']})


def guard_record(db, candidate, campaign_id):
    if candidate['run'].get('manifest', {}).get('arcta_reanalysis'):
        raise ValueError('Réanalyse : utiliser la capitalisation avec remplacement des parents')
    if protected(db, campaign_id):
        raise ValueError('Campagne protégée par un regroupement ; arbitrage individuel interdit')
    selected = {s['SHA256'].lower() for s in candidate['run']['tables']['ARCTA_SOURCES'] if s.get('Accepted_For_ARCTA') is True}
    from DABCTA_64F4_EXPLOITATION import eligible
    for link in links(db):
        if not eligible(db,link['aggregate_id']):continue
        payload = json.loads(db.execute('SELECT payload FROM variants WHERE id=?', (link['parent_variant'],)).fetchone()[0])
        parent = {s['SHA256'].lower() for s in payload['run']['tables']['ARCTA_SOURCES'] if s.get('Accepted_For_ARCTA') is True}
        if selected & parent:
            raise ValueError('Acquisitions déjà couvertes par le regroupement ' + str(link['aggregate_id']))
