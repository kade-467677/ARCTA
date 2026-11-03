"""64C : interface locale DABCTA ; base et schéma 64B conservés."""
import json
import os
import secrets
import sqlite3
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
import DABCTA_64B_BASE as core

router = APIRouter()
LOCK = RLock()
CONTEXTS = {}


def guard(request):
    if request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
        raise HTTPException(403, 'DABCTA est réservé à un accès local pour ce jalon')
    if request.headers.get('x-arcta-local') != '1':
        raise HTTPException(403, 'Requête locale requise')
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, 'Origine refusée')


def revision(db):
    return db.execute('SELECT max(revision) FROM journal').fetchone()[0]


def brief(candidate, variant_id=None):
    run = candidate['run']
    labels = {r['Code']: r['Libellé'] for r in run['tables']['ARCTA_CONFIG_SYNTHESIS']}
    return {'id': variant_id, 'run': run['run_id'], 'identity': run['identity'],
            'date': run['manifest'].get('created_at', ''), 'count': run['accepted_count'],
            'metadata': candidate['campaign_metadata'], 'settings': candidate['inputs']['settings'],
            'labels': labels, 'path': run['copies'][0], 'families': run['families'],
            'polynomials': run['polynomial_categories']}


def differences(old, new):
    changes = []
    labels = brief(new)['labels']
    for group in ('physical', 'settings', 'constants', 'campaign_metadata'):
        a, b = (old[group], new[group]) if group == 'campaign_metadata' else (old['inputs'][group], new['inputs'][group])
        for key in sorted(set(a) | set(b)):
            if core.normalized(a.get(key)) != core.normalized(b.get(key)):
                changes.append({'key': key, 'label': labels.get(key, key), 'before': a.get(key), 'after': b.get(key)})
    def trials(c):
        return {r['SHA256']: r['Source_Name'] for r in c['run']['tables']['ARCTA_SOURCES']
                if r.get('Accepted_For_ARCTA') is True}
    a, b = trials(old), trials(new)
    def mappings(c):
        return {sha: core.dump(sorted(core.normalized(roles)))
                for sha, roles in c['inputs']['selected_mapping']}
    ma, mb = mappings(old), mappings(new)
    mapping_changed = (any(ma[k] != mb[k] for k in ma.keys() & mb.keys())
                       or set(ma.values()) != set(mb.values()))
    return {'fields': changes, 'removed': [a[k] for k in a.keys() - b.keys()],
            'added': [b[k] for k in b.keys() - a.keys()],
            'mapping_changed': mapping_changed,
            'result_conflict': old['input_key'] == new['input_key'] and old['result_key'] != new['result_key']}


def snapshot(db, context):
    import DABCTA_64F1_QUALIFICATION as business
    from .dabcta_reconciliation import matches, classify
    variants = list(db.execute('SELECT * FROM variants ORDER BY id'))
    payloads = {v['id']: json.loads(v['payload']) for v in variants}
    statistical_ids = {r[0] for r in db.execute('SELECT variant_id FROM exploitable_statistical_runs')}
    from DABCTA_64E4_FILIATION import links, preview
    family_links = links(db)
    campaigns = []
    for row in db.execute('SELECT c.*,a.variant_id FROM campaigns c LEFT JOIN active a ON a.campaign_id=c.id ORDER BY c.id'):
        campaigns.append({'id': row['id'], 'label': row['label'], 'config_key': row['config_id'],
                          'active': row['variant_id'], 'metadata': json.loads(row['metadata']),
                          'replaced_by': next((r['aggregate_id'] for r in family_links if r['parent_id']==row['id']), None) if row['variant_id'] is None else None,
                          'parents': [r['parent_id'] for r in family_links if r['aggregate_id']==row['id']],
                          'eligible': row['variant_id'] is not None and business.state(db,payloads[row['variant_id']])['eligible'],
                          'variants': [{**brief(payloads[v['id']], v['id']), 'statistical_exploitable':v['id'] in statistical_ids,
                                        'statistical_shareable':row['variant_id'] is not None and v['id'] != row['variant_id'] and v['id'] not in statistical_ids and business.state(db,payloads[v['id']])['eligible'] and classify(payloads[row['variant_id']],payloads[v['id']])['kind']=='STATISTICAL_VARIANT',
                                        'statistical_settings':payloads[v['id']]['inputs']['settings'], 'business':business.state(db,payloads[v['id']]),
                                        'comparison': differences(payloads[row['variant_id']], payloads[v['id']])
                                        if row['variant_id'] is not None else None}
                                       for v in variants if v['campaign_id'] == row['id']]})
    resolved = [json.loads(r[0]) for r in db.execute("SELECT provenance FROM origins WHERE variant_id IS NOT NULL AND status!='REOPENED'")]
    candidates = []
    ignored = [json.loads(r[0]) for r in db.execute("SELECT provenance FROM origins WHERE status='IGNORED'")]
    for key, c in context['candidates'].items():
        status = 'À examiner'
        try:
            stored = core.known(db, c)
            if stored:
                status = 'Exclu' if stored['status'] == 'IGNORED' else 'Déjà traité'
            elif any(core.same_export_context(c, x) for x in ignored):
                status = 'Exclusion déjà décidée'
            elif any(core.same_export_context(c, x) for x in [*payloads.values(), *resolved]):
                status = 'Variante déjà arbitrée'
        except ValueError:
            status = 'Conflit d’identité du run'
        compatible = [x for x in campaigns if x['config_key'] == c['config_key'] and not x['replaced_by'] and not x['parents']]
        reanalysis = None
        if c['run']['manifest'].get('arcta_reanalysis'):
            reanalysis = preview(db, c) if status == 'À examiner' else {'ready': False, 'error': 'Décision déjà enregistrée', 'parents': []}
        all_matches=matches(db,c,include_history=True)
        from DABCTA_64F4_EXPLOITATION import historical_targets
        candidates.append({**brief(c), 'key': key, 'status': status, 'reanalysis': reanalysis, 'reconciliation':matches(db,c),
                           'historical_matches':[r for r in all_matches if r['active'] is None or not r['existing_qualified']],
                           'historical_targets':[{'campaign':r['campaign'],'label':r['label']} for r in historical_targets(db,c,all_matches)],
                           'qualification_config':c['run']['tables']['ARCTA_CONFIG_SYNTHESIS'], 'business':business.state(db,c),
                           'compatible': [x['id'] for x in compatible],
                           'qualification': {str(x['id']): core.campaign_changes(x['metadata'], c['campaign_metadata']) for x in compatible},
                           'comparisons': {str(x['id']): differences(payloads[x['active']], c)
                                           for x in compatible if x['active'] is not None}})
    journal = [{**dict(r), 'detail': json.loads(r['detail'])} for r in db.execute('SELECT * FROM journal ORDER BY revision DESC')]
    excluded = [dict(r) for r in db.execute("SELECT run_id FROM origins WHERE status='IGNORED'")]
    return {'database': context['database'], 'root': context['root'], 'revision': revision(db),
            'campaigns': campaigns, 'candidates': candidates, 'errors': context['errors'], 'business_gate':business.enabled(db),
            'journal': journal, 'excluded': excluded}


@router.get('/dabcta/consulter')
@router.get('/dabcta/base')
@router.get('/dabcta/ajouter')
@router.get('/dabcta/reconcilier')
@router.get('/dabcta/retraiter')
@router.get('/dabcta/sas')
@router.get('/dabcta/journal')
@router.get('/dabcta')
def page():
    return FileResponse(Path(__file__).parent / 'templates' / 'dabcta.html', media_type='text/html')


@router.get('/dabcta/arcta')
def arcta_entry(request: Request):
    return RedirectResponse(getattr(request.app.state, 'arcta_base_url', '') + '/', status_code=303)


@router.get('/dabcta/run_presentation.js')
def run_presentation_script():
    return FileResponse(Path(__file__).parent / 'templates' / 'dabcta_run_presentation.js', media_type='text/javascript')


@router.get('/dabcta/consultation.js')
def consultation_script():
    return FileResponse(Path(__file__).parent / 'templates' / 'dabcta_consultation.js', media_type='text/javascript')


@router.get('/dabcta/catalogue.js')
def catalogue_script():
    return FileResponse(Path(__file__).parent / 'templates' / 'dabcta_catalogue.js', media_type='text/javascript')


@router.get('/dabcta/grouping.js')
def grouping_script():
    return FileResponse(Path(__file__).parent / 'templates' / 'dabcta_grouping.js', media_type='text/javascript')


@router.get('/dabcta/reanalysis.js')
def reanalysis_script():
    return FileResponse(Path(__file__).parent / 'templates' / 'dabcta_reanalysis.js', media_type='text/javascript')


@router.get('/dabcta/capitalization.js')
def capitalization_script():
    return FileResponse(Path(__file__).parent / 'templates' / 'dabcta_capitalization.js', media_type='text/javascript')


@router.get('/dabcta/qualification.js')
def qualification_script():
    return FileResponse(Path(__file__).parent/'templates'/'dabcta_qualification.js',media_type='text/javascript')


@router.get('/dabcta/workflow.js')
def workflow_script():
    return FileResponse(Path(__file__).parent/'templates'/'dabcta_workflow.js',media_type='text/javascript')


@router.get('/dabcta/reconciliation.js')
def reconciliation_script():
    return FileResponse(Path(__file__).parent/'templates'/'dabcta_reconciliation.js',media_type='text/javascript')


@router.get('/dabcta/rework.js')
def rework_script():
    return FileResponse(Path(__file__).parent/'templates'/'dabcta_rework.js',media_type='text/javascript')


@router.get('/api/dabcta/defaults')
def defaults():
    home = Path.home() / 'Documents'
    return {'database': str(home / 'DABCTA' / 'DABCTA.sqlite'),
            'root': os.environ.get('ARCTA_OUTPUTS_DIR') or str(home / 'ARCTA_OUTPUTS')}


@router.post('/api/dabcta/{operation}')
def api(operation: str, body: dict, request: Request):
    guard(request)
    with LOCK:
        db = None
        try:
            if operation == 'open':
                path = Path(body['database']).expanduser().resolve()
                context = {'database': str(path), 'root': str(Path(body['root']).expanduser().resolve()) if body.get('root') else '',
                           'candidates': {}, 'errors': []}
                db = core.connect(path)
                token = secrets.token_urlsafe(24)
                if len(CONTEXTS) >= 64:
                    CONTEXTS.pop(next(iter(CONTEXTS)))
                CONTEXTS[token] = context
                return {'token': token, **snapshot(db, context)}
            context = CONTEXTS.get(body.get('token'))
            if not context:
                raise ValueError('Session expirée : ouvrir à nouveau la base')
            if not Path(context['database']).is_file():
                raise ValueError('Base déplacée ou supprimée ; ouvrir à nouveau')
            db = core.connect(context['database'])
            if operation in {'admit-qualified','arbitrate-candidate'}:
                from .dabcta_reconciliation import admit,arbitrate
                candidate=context['candidates'][body['candidate']]
                (admit if operation=='admit-qualified' else arbitrate)(db,candidate,body)
                return snapshot(db,context)
            if operation == 'share-stored-statistics':
                vid=body.get('variant')
                if type(vid) is not int:raise ValueError('Run conservé invalide')
                row=db.execute('SELECT payload,campaign_id FROM variants WHERE id=?',(vid,)).fetchone()
                if row is None:raise ValueError('Run conservé inconnu')
                from .dabcta_reconciliation import arbitrate
                arbitrate(db,json.loads(row['payload']),{**body,'campaign':row['campaign_id'],'choice':'share'})
                return snapshot(db,context)
            if operation == 'inventory-sources':
                from .dabcta_workflow import inventory_sources
                inventory_sources(db, context, body)
                return snapshot(db, context)
            if operation in {'rework-preview', 'prepare-rework', 'reworks'}:
                from .dabcta_rework import preflight_rework, prepare_rework
                from .dabcta_reanalysis import history
                if operation == 'reworks':
                    return {'packets': history(db, 'PREPARE_REWORK')}
                if operation == 'rework-preview':
                    return preflight_rework(db, body)
                return prepare_rework(db, context['database'], body)
            if operation == 'open-reanalysis':
                from .dabcta_arcta_bridge import open_session
                result = open_session(db, context['database'], request.app.state.session_registry, body)
                return {**result, 'url': getattr(request.app.state, 'arcta_base_url', '') + result['url']}
            if operation in {'prepare-reanalysis', 'reanalyses'}:
                from .dabcta_reanalysis import prepare, history
                if operation == 'reanalyses':
                    return {'revision': revision(db), 'packets': history(db)}
                return prepare(db, context['database'], body)
            if operation == 'grouping':
                from .dabcta_grouping import preflight
                return preflight(db, body.get('campaigns'), body.get('revision'))
            if operation == 'catalogue':
                from .dabcta_catalogue import catalogue
                return catalogue(db, body.get('variant'))
            if operation == 'business-enable':
                from DABCTA_64F1_QUALIFICATION import activate
                activate(db, body)
                return snapshot(db, context)
            if operation == 'business-review':
                from DABCTA_64F1_QUALIFICATION import decide
                if body.get('variant') is not None:
                    row=db.execute('SELECT payload FROM variants WHERE id=?',(int(body['variant']),)).fetchone()
                    if row is None:
                        raise ValueError('Variante inconnue')
                    candidate=json.loads(row[0])
                else:
                    candidate=context['candidates'][body['candidate']]
                decide(db,candidate,body)
                if body.get('workflow')=='qualification' and body.get('variant') is None:
                    from .dabcta_reconciliation import finish_qualification
                    notice=finish_qualification(db,candidate,body)
                    return {**snapshot(db,context),'workflow_notice':notice}
                return snapshot(db, context)
            if operation == 'scan':
                result = core.inventory(context['root'])
                context['candidates'], context['errors'] = {}, result['errors']
                for run in result['runs']:
                    try:
                        c = core.prepare(run, allow_reanalysis=True)
                        context['candidates'][run['run_id']] = c
                    except (ValueError, KeyError, OSError) as exc:
                        context['errors'].append({'manifest': run['copies'][0], 'error': str(exc)})
            elif operation == 'capitalize-reanalysis':
                from DABCTA_64E4_FILIATION import capitalize
                capitalize(db, context['candidates'][body['candidate']], body)
            elif operation == 'decide':
                c = context['candidates'][body['candidate']]
                if core.sha256(Path(c['run']['copies'][0]) / 'result.xlsx') != c['run']['xlsx_sha256']:
                    raise ValueError('Export modifié : relancer l’inventaire')
                from DABCTA_64F1_QUALIFICATION import enabled
                from .dabcta_reconciliation import matches
                if enabled(db) and body.get('mode')!='ignore' and matches(db,c):
                    raise ValueError('Rapprochement détecté : utiliser le parcours Réconcilier')
                mode = body['mode']
                if mode not in {'new', 'keep', 'replace', 'ignore'}:
                    raise ValueError('Décision inconnue')
                motif = str(body.get('reason', '')).strip()
                if not motif:
                    raise ValueError('Un motif est obligatoire')
                if mode=='new' and enabled(db):
                    from .dabcta_reconciliation import admit
                    admit(db,c,{**body,'label':body.get('label',''),'reason':motif})
                    return snapshot(db,context)
                cid = None if mode in {'new', 'ignore'} else int(body['campaign'])
                core.record(db, c, cid, 'keep' if mode == 'new' else mode, motif,
                            str(body.get('label', '')).strip(), expected_revision=int(body['revision']),
                            qualification=body.get('qualification'), require_qualification=True)
            elif operation in {'activate', 'reopen'}:
                motif = str(body.get('reason', '')).strip()
                if not motif:
                    raise ValueError('Un motif est obligatoire')
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    if revision(db) != int(body['revision']):
                        raise ValueError('La base a changé : actualiser avant de décider')
                    if operation == 'activate':
                        vid = int(body['variant'])
                        row = db.execute('SELECT campaign_id FROM variants WHERE id=?', (vid,)).fetchone()
                        if not row:
                            raise ValueError('Variante inconnue')
                        cid = row[0]
                        prior = db.execute('SELECT variant_id FROM active WHERE campaign_id=?', (cid,)).fetchone()
                        db.execute('INSERT INTO active VALUES(?,?) ON CONFLICT(campaign_id) DO UPDATE SET variant_id=excluded.variant_id', (cid, vid))
                        core.event(db, 'REVISE_SELECTION', {'campaign': cid, 'previous': prior[0] if prior else None, 'selected': vid, 'reason': motif})
                    else:
                        row = db.execute("SELECT provenance FROM origins WHERE run_id=? AND status='IGNORED'", (body['run'],)).fetchone()
                        if not row:
                            raise ValueError('Exclusion introuvable')
                        c = json.loads(row[0])
                        for origin in db.execute("SELECT * FROM origins WHERE status='IGNORED'").fetchall():
                            other = json.loads(origin['provenance'])
                            if core.same_export_context(c, other):
                                core.event(db, 'REOPEN_EXCLUSION', {'previous': dict(origin), 'reason': motif})
                                db.execute("UPDATE origins SET status='REOPENED' WHERE run_id=?", (origin['run_id'],))
            elif operation != 'status':
                raise ValueError('Opération inconnue')
            return snapshot(db, context)
        except (ValueError, KeyError, TypeError, OSError, sqlite3.DatabaseError) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            if db is not None:
                db.close()
