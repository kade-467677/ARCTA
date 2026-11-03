"""Suppression explicite des seuls dossiers et fichiers suivis pour un run."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from . import session_campaign_run as store


def refuse(message):
    raise ValueError(message)


def checked(path):
    path = Path(path)
    if not path.is_absolute():
        refuse("Chemin absolu attendu : " + str(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            refuse("Lien ou jonction refusé : " + str(part))
    if path != path.resolve():
        refuse("Chemin non canonique : " + str(path))
    return path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    checked(root)
    files = {}; dirs = []
    if not root.exists():
        if not root.parent.is_dir():
            refuse("Dossier parent inaccessible ; reconnectez le stockage : " + str(root.parent))
        return files, dirs
    if not root.is_dir():
        refuse("Dossier attendu : " + str(root))
    def unreadable(exc):
        raise exc
    for parent, children, names in os.walk(root, followlinks=False, onerror=unreadable):
        for name in children:
            p = checked(Path(parent) / name)
            dirs.append(p.relative_to(root).as_posix())
        for name in names:
            p = checked(Path(parent) / name)
            if not p.is_file():
                refuse("Fichier non régulier : " + str(p))
            files[p.relative_to(root).as_posix()] = digest(p)
    return files, sorted(dirs)


def paths(session, run_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', run_id):
        refuse("Identifiant de run invalide")
    root = checked(Path(session.storage_dir).absolute())
    return checked(root / 'campaign_runs' / run_id), checked(root / 'run_deletions' / (run_id + '.json'))


def relative_file(value):
    p = Path(value)
    if not value or p.is_absolute() or '..' in p.parts or '\\' in value or ':' in value:
        refuse("Chemin de livrable invalide")
    return p.as_posix()


def initial_targets(session, run_id, run_dir):
    run = store.load_session_campaign_run(session, run_id)
    if run is None:
        refuse("Run inconnu")
    if not run.terminal:
        refuse("Un run en cours ne peut pas être supprimé")
    result = store.load_campaign_result_metadata(session, run_id) or {}
    plan_path = run_dir / 'output_locations.json'
    plan = store._read_json_with_retry(checked(plan_path)) if plan_path.exists() else {}
    if plan and plan.get('run_id') != run_id:
        refuse("Destinations associées à un autre run")
    artifacts = {}
    for item in (*run.artifacts, *result.get('artifacts', [])):
        p = Path(item['relative_path']).relative_to(Path('campaign_runs') / run_id)
        artifacts[relative_file(p.as_posix())] = item.get('sha256')
    targets = []
    for item in result.get('output_locations', []):
        target = checked(Path(item['path']))
        declared = next((d for d in plan.get('destinations', []) if d['kind'] == item['kind']), None)
        if declared is None:
            refuse("Destination non déclarée : " + str(target))
        base = checked(Path(declared['path']))
        if target.parent != base.parent or not re.fullmatch(re.escape(base.name) + r'(?:_\d{2,3})?', target.name):
            refuse("Destination différente du plan : " + str(target))
        if target == run_dir or target in run_dir.parents or run_dir in target.parents:
            refuse("Chevauchement avec le stockage technique")
        files, dirs = inventory(target)
        if target.exists():
            manifest_path = target / 'ARCTA_RUN_MANIFEST.json'
            if not manifest_path.is_file():
                refuse("Manifeste absent : " + str(target))
            manifest = store._read_json_with_retry(manifest_path)
            if manifest.get('run_id') != run_id or manifest.get('published_directory') != str(target):
                refuse("Manifeste étranger au run : " + str(target))
            listed = {relative_file(k): v for k, v in manifest['files_sha256'].items()}
            if any(k not in artifacts or (artifacts[k] and v != artifacts[k]) for k, v in listed.items()):
                refuse("Manifeste différent des livrables du run")
            if set(files) - set(listed) - {'ARCTA_RUN_MANIFEST.json'}:
                refuse("Fichiers non suivis présents ; suppression refusée : " + str(target))
        targets.append(dict(kind=item['kind'], path=str(target), files=files, dirs=dirs))
    files, dirs = inventory(run_dir)
    known = set(artifacts) | {'run.json', 'result.json', 'output_locations.json', 'report_options.json',
                              'TOTAL/result.json', 'EFFECTIVE/result.json'}
    # Un run échoué peut avoir laissé des livrables intermédiaires : revue manuelle.
    if set(files) - known:
        refuse("Fichiers techniques non suivis : " + ', '.join(sorted(set(files) - known)))
    targets.append(dict(kind='TECHNICAL', path=str(run_dir), files=files, dirs=dirs))
    for i, a in enumerate(targets):
        for b in targets[i + 1:]:
            pa, pb = Path(a['path']), Path(b['path'])
            if pa == pb or pa in pb.parents or pb in pa.parents:
                refuse("Destinations de suppression imbriquées")
    return targets


def pending(session):
    folder = checked(Path(session.storage_dir).absolute() / 'run_deletions')
    return [p.stem for p in sorted(folder.glob('*.json'))
            if store._read_json_with_retry(checked(p)).get('state') == 'STARTED']


def preview(session, run_id):
    run_dir, journal = paths(session, run_id)
    old = store._read_json_with_retry(journal) if journal.exists() else None
    if old and old.get('state') == 'DONE':
        return dict(run_id=run_id, done=True, token='', targets=[])
    if old and old.get('run_id') != run_id:
        refuse("Journal de suppression étranger au run")
    targets = old['targets'] if old else initial_targets(session, run_id, run_dir)
    snapshot = []
    for target in targets:
        root = checked(Path(target['path']))
        for name in (*target['files'], *target['dirs']):
            relative_file(name)
        files, dirs = inventory(root)
        if any(k not in target['files'] or v != target['files'][k] for k, v in files.items()):
            refuse("Un fichier a changé depuis le début de la suppression : " + str(root))
        if set(dirs) - set(target['dirs']):
            refuse("Un dossier a été ajouté : " + str(root))
        snapshot.append(dict(kind=target['kind'], path=str(root), files=files, dirs=dirs, exists=root.exists()))
    token = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return dict(run_id=run_id, done=False, token=token, targets=snapshot)


def retry(action):
    for attempt in range(6):
        try:
            return action()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(.05 * (attempt + 1))


def delete(session, run_id, token):
    run_dir, journal = paths(session, run_id)
    view = preview(session, run_id)
    if view['done']:
        return dict(run_id=run_id, deleted=True)
    if not token or token != view['token']:
        refuse("Le contenu a changé ; actualisez la confirmation de suppression")
    record = dict(run_id=run_id, state='STARTED', targets=view['targets'])
    store._atomic_json(journal, record)
    # Pointeur retiré seulement s'il désigne ce run ; les autres restent inchangés.
    if store.current_campaign_run_id(session) == run_id:
        retry(store.current_campaign_run_path(session).unlink)
    try:
        for target in record['targets']:
            root = checked(Path(target['path']))
            for name in sorted(target['files'], key=lambda k: (k in {'ARCTA_RUN_MANIFEST.json', 'run.json'}, k)):
                p = checked(root / name)
                if p.exists() and digest(p) != target['files'][name]:
                    refuse("Fichier modifié pendant la suppression : " + str(p))
                retry(p.unlink)
            for name in sorted(target['dirs'], key=lambda k: len(Path(k).parts), reverse=True):
                retry(checked(root / name).rmdir)
            retry(root.rmdir)
    except (OSError, ValueError) as exc:
        raise ValueError("Suppression incomplète, relancez cette action après avoir fermé les fichiers ouverts. " + str(exc)) from exc
    store._atomic_json(journal, dict(run_id=run_id, state='DONE', utc=datetime.now(timezone.utc).isoformat(),
                                    paths=[t['path'] for t in record['targets']]))
    return dict(run_id=run_id, deleted=True)
