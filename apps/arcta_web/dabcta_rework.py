"""64F5 : retraiter une variante sans modifier sa référence ni sa qualification."""
import json
import DABCTA_64B_BASE as core
from .dabcta_grouping import source_location


def variant(db, vid):
    if type(vid) is not int or vid < 1:
        raise ValueError('Choisir une variante de la base')
    row = db.execute('SELECT v.id,v.campaign_id,v.payload,c.label FROM variants v '
                     'JOIN campaigns c ON c.id=v.campaign_id WHERE v.id=?', (vid,)).fetchone()
    if row is None:
        raise ValueError('Variante inconnue')
    return row, json.loads(row['payload'])


def preflight_rework(db, body):
    from DABCTA_64F1_QUALIFICATION import revision, state
    revision(db, body.get('revision'))
    row, candidate = variant(db, body.get('variant'))
    scope = body.get('scope')
    if scope not in {'all', 'retained'}:
        raise ValueError('Choisir tous les essais ou uniquement les essais précédemment retenus')
    sources, blockers, seen, cache = [], [], set(), {}
    for r in candidate['run']['tables']['ARCTA_SOURCES']:
        prior = r.get('Accepted_For_ARCTA') is True
        included = scope == 'all' or prior
        item = dict(campaign=row['campaign_id'], variant=row['id'], trial=r.get('Trial_ID'),
                    name=r.get('Source_Name'), sha256=r.get('SHA256'), accepted=included,
                    previously_accepted=prior, decision=r.get('DIAG_Decision'), path=None)
        if included:
            item.update(source_location(r, cache))
            if not item['path']:
                blockers.append('Source non vérifiée : ' + str(item['name']))
            digest = str(item['sha256']).lower()
            if digest in seen:
                blockers.append('Acquisition dupliquée : ' + str(item['name']))
            seen.add(digest)
        else:
            item['status'] = 'Écarté du périmètre de retraitement choisi'
        sources.append(item)
    if not any(s['accepted'] for s in sources):
        blockers.append('Aucun essai dans le périmètre choisi')
    revision(db, body.get('revision'))
    return dict(revision=body['revision'], sources=sources, blockers=blockers,
                warnings=['CONFIG, paramètres, mapping et DIAG sont à revoir dans ARCTA.'],
                campaigns=[dict(id=row['campaign_id'], variant=row['id'], label=row['label'],
                                run=candidate['run']['run_id'], metadata=candidate['campaign_metadata'])],
                business=state(db,candidate), retained_count=sum(s['accepted'] for s in sources),
                prior_retained_count=sum(s['previously_accepted'] for s in sources),
                total_count=len(sources), scope=scope)


def prepare_rework(db, database, body):
    from .dabcta_reanalysis import prepare
    row, _ = variant(db, body.get('variant'))
    # A single campaign is an explicit operation, never a simulated grouping.
    return prepare(db, database, {**body, 'settings_campaign':row['campaign_id'],
                                  'campaigns':[row['campaign_id']], 'independent':False}, rework=True)
