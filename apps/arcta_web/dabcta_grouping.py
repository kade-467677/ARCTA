"""64E1 : précontrôle de campagnes distinctes ; aucune écriture ni fusion."""
import json
from pathlib import Path
import DABCTA_64B_BASE as core


def source_location(source, cache):
    digest = source.get('SHA256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdefABCDEF' for c in digest):
        return {'status': 'Empreinte absente ou invalide', 'path': None}
    attempts = []
    for key, label in (('Original_Source_Path', 'Original vérifié'), ('Server_Copy_Path', 'Copie serveur vérifiée')):
        raw = source.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            attempts.append('Chemin non absolu : ' + raw)
            continue
        identity = (str(path), digest.lower())
        if identity not in cache:
            try:
                cache[identity] = 'OK' if path.is_file() and core.sha256(path).lower() == digest.lower() else 'Fichier absent ou empreinte différente'
            except OSError as exc:
                cache[identity] = 'Fichier inaccessible : ' + str(exc)
        if cache[identity] == 'OK':
            return {'status': label, 'path': str(path), 'attempts': attempts}
        attempts.append(str(path) + ' : ' + cache[identity])
    return {'status': 'Source non vérifiée', 'path': None, 'attempts': attempts}


def preflight(db, campaigns, expected_revision):
    if (not isinstance(campaigns, list) or not 2 <= len(campaigns) <= 20
            or any(type(x) is not int or x < 1 for x in campaigns)
            or len(set(campaigns)) != len(campaigns)):
        raise ValueError('Choisir de 2 à 20 campagnes distinctes')
    if type(expected_revision) is not int:
        raise ValueError('Révision de base obligatoire')
    from DABCTA_64E4_FILIATION import protected
    from DABCTA_64E4_FILIATION import links
    # Reopening exploitation does not authorize rewriting historical lineage.
    if any(any(cid in (r['parent_id'],r['aggregate_id']) for r in links(db)) for cid in campaigns):
        raise ValueError('Campagne déjà liée à une réanalyse ; regroupements successifs non pris en charge à ce jalon')
    db.execute('BEGIN')
    try:
        rev = db.execute('SELECT max(revision) FROM journal').fetchone()[0]
        if rev != expected_revision:
            raise ValueError('La base a changé : actualiser avant le précontrôle')
        selected = []
        for cid in campaigns:
            row = db.execute(
                'SELECT c.id,c.label,c.config_id,c.metadata AS current_metadata,a.variant_id,v.payload '
                'FROM campaigns c LEFT JOIN active a ON a.campaign_id=c.id '
                'LEFT JOIN variants v ON v.id=a.variant_id WHERE c.id=?', (cid,)
            ).fetchone()
            if row is None or row['payload'] is None:
                raise ValueError('Campagne inconnue ou sans variante active : ' + str(cid))
            from DABCTA_64F1_QUALIFICATION import require
            require(db, json.loads(row['payload']))
            selected.append({**dict(row), 'candidate': json.loads(row['payload'])})
    finally:
        db.rollback()

    blockers, warnings, changes, sources = [], [], [], []
    if len({s['config_id'] for s in selected}) != 1:
        blockers.append('Les configurations physiques archivées diffèrent.')

    for group, label in (('constants', 'Constantes de calcul'), ('settings', 'Paramètres statistiques')):
        keys = sorted(set().union(*(s['candidate']['inputs'][group] for s in selected)))
        for key in keys:
            values = [s['candidate']['inputs'][group].get(key) for s in selected]
            if len({core.dump(core.normalized(v)) for v in values}) > 1:
                changes.append({'group': label, 'key': key,
                                'values': [{'campaign': s['id'], 'value': v} for s, v in zip(selected, values)]})
        if any(r['group'] == label for r in changes):
            (blockers if group == 'constants' else warnings).append(
                label + (' différents : à harmoniser avant regroupement.' if group == 'constants'
                         else ' différents : choisir un paramétrage commun pour la future réanalyse.'))

    profiles = set()
    cache, seen, all_selected = {}, {}, 0
    for s in selected:
        c = s['candidate']
        mapping = dict(c['inputs']['selected_mapping'])
        rows = c['run']['tables'].get('ARCTA_SOURCES', [])
        retained = [r for r in rows if r.get('Accepted_For_ARCTA') is True]
        if len(retained) != c['run']['accepted_count'] or not retained:
            blockers.append('Sélection incohérente ou vide dans la campagne ' + str(s['id']))
        for r in rows:
            accepted = r.get('Accepted_For_ARCTA') is True
            item = {'campaign': s['id'], 'variant': s['variant_id'],
                    'trial': r.get('Trial_ID'), 'name': r.get('Source_Name'),
                    'accepted': accepted, 'sha256': r.get('SHA256'),
                    'decision': r.get('DIAG_Decision')}
            if accepted:
                all_selected += 1
                item.update(source_location(r, cache))
                if not item['path']:
                    blockers.append('Source non vérifiée : campagne ' + str(s['id']) + ' / ' + str(item['name']))
                roles = mapping.get(r.get('SHA256'), [])
                if not {'Xg', 'Y'} <= {x[0] for x in roles}:
                    blockers.append('Mapping incomplet : campagne ' + str(s['id']) + ' / ' + str(item['name']))
                profiles.add(core.dump(sorted(core.normalized(roles))))
                digest = r.get('SHA256')
                if isinstance(digest, str):
                    seen.setdefault(digest.lower(), []).append({'campaign': s['id'], 'trial': item['trial'], 'name': item['name']})
            else:
                item.update(status='Non retenu — conservé pour traçabilité', path=None)
            sources.append(item)

    duplicates = [members for members in seen.values() if len(members) > 1]
    if duplicates:
        blockers.append('Des fichiers retenus sont identiques : arbitrage nécessaire, aucun doublon supprimé automatiquement.')
    if len(profiles) > 1:
        blockers.append('Les affectations rôle/colonne diffèrent : un mapping commun doit être établi.')

    # Un autre processus peut avoir écrit pendant la lecture des fichiers.
    if db.execute('SELECT max(revision) FROM journal').fetchone()[0] != rev:
        raise ValueError('La base a changé pendant le précontrôle : recommencer')

    return {'revision': rev, 'blockers': list(dict.fromkeys(blockers)), 'warnings': warnings,
            'campaigns': [{'id': s['id'], 'label': s['label'], 'variant': s['variant_id'],
                           'run': s['candidate']['run']['run_id'],
                           'metadata': json.loads(s['current_metadata']),
                           'run_metadata': s['candidate']['campaign_metadata']} for s in selected],
            'differences': changes, 'sources': sources, 'duplicates': duplicates,
            'retained_count': all_selected, 'unique_files': len(seen),
            'status': 'BLOQUE' if blockers else 'A_REVOIR',
            'notes': [
                'Base de travail : essais retenus dans les variantes actives. Les essais écartés restent listés et ne sont pas réintégrés automatiquement.',
                'Une empreinte identique signale le même fichier ; une empreinte différente ne prouve pas une acquisition indépendante.',
                'Égalité des champs renseignés ne prouve pas une équivalence physique complète. Confirmer l’indépendance des campagnes et examiner les champs manquants.',
                'Structure et unités des fichiers bruts à contrôler dans ARCTA avant calcul. Aucune compatibilité complète n’est certifiée ici.',
                'Aucune campagne créée, aucun calcul lancé, aucune moyenne des coefficients. Les fichiers devront être revérifiés avant la réanalyse.'
            ]}
