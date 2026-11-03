"""64F2: choix explicite des sources et trace d'inventaire sans import."""
import json
from pathlib import Path
import DABCTA_64B_BASE as core


def inventory_sources(db, context, body):
    value = body.get('root')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Choisir un dossier de sources ARCTA')
    root = Path(value.strip()).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Dossier de sources absent ou inaccessible : ' + str(root))
    expected = body.get('revision')
    if type(expected) is not int or db.execute('SELECT max(revision) FROM journal').fetchone()[0] != expected:
        raise ValueError('La base a changé : actualiser avant de lancer l’inventaire')

    result = core.inventory(str(root))
    candidates, errors = {}, list(result['errors'])
    for run in result['runs']:
        try:
            candidate = core.prepare(run, allow_reanalysis=True)
            candidates[run['run_id']] = candidate
        except (ValueError, KeyError, OSError) as exc:
            errors.append({'manifest': run['copies'][0], 'error': str(exc)})
    detail = {'root': str(root), 'runs': len(candidates), 'errors': errors,
              'exports': sorted((key, value['run']['xlsx_sha256'],
                                 core.fingerprint({k:v for k,v in value['run']['manifest'].items()
                                                   if k != 'published_directory'}))
                                for key,value in candidates.items())}
    fingerprint = core.fingerprint(detail)
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT max(revision) FROM journal').fetchone()[0] != expected:
            raise ValueError('La base a changé pendant l’inventaire : actualiser')
        previous = db.execute("SELECT detail FROM journal WHERE action='INVENTORY_SOURCES' ORDER BY revision DESC LIMIT 1").fetchone()
        if previous is None or json.loads(previous[0]).get('fingerprint') != fingerprint:
            core.event(db, 'INVENTORY_SOURCES', {**detail, 'fingerprint': fingerprint,
                       'reason': 'Inventaire demandé depuis le parcours Ajouter ; aucune capitalisation automatique'})
    # Only publish the new source context after successful journal commit.
    context.update(root=str(root), candidates=candidates, errors=errors)
