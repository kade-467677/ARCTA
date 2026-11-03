"""64B : SQLite, campagnes explicites, résultat actif et arbitrages pérennes."""
import argparse
import getpass
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from DABCTA_64A_INVENTAIRE import inventory, json_default, sha256, table

META = set(
    'entity program_id configuration_id report_number test_date sample_count '
    'bench_reference sensor_reference operator_name screw_lot nut_lot washer_lot'
    .split()
)
APP_ID = 0x44414243


def dump(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), default=json_default, allow_nan=False
    )


def normalized(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(v) for v in value]
    return value


def fingerprint(value):
    return hashlib.sha256(
        dump(normalized(value)).encode('utf-8')
    ).hexdigest()


def ordered(rows):
    return sorted(rows, key=dump)


def prepare(run, allow_reanalysis=False):
    if run.get('manifest', {}).get('arcta_reanalysis') and not allow_reanalysis:
        raise ValueError('Réanalyse agrégée : utiliser le parcours Web de capitalisation avec contrôle de filiation')
    if run['status'] != 'LU':
        raise ValueError('Conflit de run_id : import interdit')

    config = run['tables']['ARCTA_CONFIG_SYNTHESIS']
    physical = {
        r['Code']: [r.get('Valeur'), r.get('Unité')]
        for r in config
        if r['Section'] == 'Configuration'
        and r['Code'] not in META
        and not r['Code'].startswith('selflock_')
        and (r['Code'] not in {'thread_lead_mm', 'bearing_cone_half_angle_deg'} or r.get('Valeur') is not None)
    }
    sources = run['tables']['ARCTA_SOURCES']
    selected = [
        r for r in sources if r.get('Accepted_For_ARCTA') is True
    ]
    if not selected:
        raise ValueError('Aucun essai accepté')

    for row in sources:
        value = row.get('SHA256', '')
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError('Empreinte essai absente')
        int(value, 16)

    if len({r['Trial_ID'] for r in sources}) != len(sources):
        raise ValueError('Trial_ID dupliqué')
    if len({r['SHA256'] for r in selected}) != len(selected):
        raise ValueError(
            'Deux essais retenus ont le même fichier : vérifier avant import'
        )

    excel = Path(run['copies'][0]) / 'result.xlsx'
    book = openpyxl.load_workbook(
        excel, read_only=True, data_only=False
    )
    try:
        mapping = table(book, 'ARCTA_COLUMN_MAP')
    finally:
        book.close()

    if sha256(excel) != run['xlsx_sha256']:
        raise ValueError('Excel modifié depuis son inventaire')

    mapped = []
    for source in selected:
        roles = [
            (r['Role'], r['Source_Column'])
            for r in mapping if r['Trial_ID'] == source['Trial_ID']
        ]
        if not {'Xg', 'Y'} <= {r[0] for r in roles}:
            raise ValueError('Mapping incomplet pour un essai retenu')
        if len({r[0] for r in roles}) != len(roles):
            raise ValueError('Rôle de mapping dupliqué')
        mapped.append([source['SHA256'], sorted(roles)])

    settings = {
        r['Parameter']: r['Value']
        for r in run['tables']['ARCTA_SETTINGS']
    }
    constants = {
        r['Code']: r.get('Valeur')
        for r in config if r['Section'] == 'Constantes de calcul'
    }
    inputs = {
        'physical': physical,
        'settings': settings,
        'constants': constants,
        'selected_mapping': sorted(mapped),
    }
    if settings.get('TORQUE_BASIS') in {'EFFECTIVE', 'DUAL'}:
        source_hashes = {str(s['Trial_ID']):s['SHA256'] for s in selected}
        inputs['selflock_correction'] = sorted(
            (source_hashes[str(r['Trial_ID'])], r['Autofrein_Nm'], r['Method'])
            for r in run['tables'].get('ARCTA_SELFLOCK_CORRECTION', []))
        if settings.get('SELFLOCK_POLICY'):
            # Identité par acquisition, indépendante des UUID et des noms locaux.
            inputs['selflock_provenance'] = sorted(
                (source_hashes[str(r['Trial_ID'])], r.get('Origin'), r.get('Diag_Status'), r.get('Policy'))
                for r in run['tables'].get('ARCTA_SELFLOCK_CORRECTION', []))
    polys = [
        {k: v for k, v in r.items() if k != 'DABCTA_category'}
        for r in run['tables']['POLY_FITS_STATS']
    ]
    results = {
        'polynomials': ordered(polys),
        'tolerance': ordered(
            run['tables'].get('ARCTA_TOLERANCE_DETAILS', [])
        ),
        'warnings': ordered(
            run['tables'].get('ARCTA_TOLERANCE_WARNINGS', [])
        ),
        'selflock': run['tables'].get('ARCTA_SELF_LOCK_STATS', []),
    }
    return {
        'config_key': fingerprint(physical),
        'physical': physical,
        'input_key': fingerprint(inputs),
        'result_key': fingerprint(results),
        'inputs': inputs,
        'run': run,
        'campaign_metadata': {
            r['Code']: r.get('Valeur')
            for r in config
            if r['Section'] == 'Configuration' and r['Code'] in META
        },
    }


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        app = db.execute('PRAGMA application_id').fetchone()[0]
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if tables or app:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if app != APP_ID or version != 1:
                raise ValueError(
                    'Base étrangère ou version non prise en charge'
                )
        else:
            db.executescript(f'''
BEGIN IMMEDIATE;
PRAGMA application_id={APP_ID};
PRAGMA user_version=1;

CREATE TABLE configurations(
 id TEXT PRIMARY KEY,
 data TEXT NOT NULL
);

CREATE TABLE campaigns(
 id INTEGER PRIMARY KEY,
 config_id TEXT NOT NULL REFERENCES configurations,
 label TEXT NOT NULL,
 metadata TEXT NOT NULL
);

CREATE TABLE variants(
 id INTEGER PRIMARY KEY,
 campaign_id INTEGER NOT NULL REFERENCES campaigns,
 input_key TEXT NOT NULL,
 result_key TEXT NOT NULL,
 payload TEXT NOT NULL,
 UNIQUE(campaign_id,input_key,result_key)
);

CREATE TABLE active(
 campaign_id INTEGER PRIMARY KEY REFERENCES campaigns,
 variant_id INTEGER NOT NULL UNIQUE REFERENCES variants
);

CREATE TABLE origins(
 run_id TEXT PRIMARY KEY,
 excel_sha TEXT NOT NULL,
 variant_id INTEGER REFERENCES variants,
 status TEXT NOT NULL,
 provenance TEXT NOT NULL
);

CREATE TABLE polynomials(
 variant_id INTEGER NOT NULL REFERENCES variants,
 family TEXT NOT NULL,
 statistic TEXT NOT NULL,
 category TEXT NOT NULL,
 data TEXT NOT NULL
);

CREATE TABLE journal(
 revision INTEGER PRIMARY KEY AUTOINCREMENT,
 utc TEXT NOT NULL,
 actor TEXT NOT NULL,
 action TEXT NOT NULL,
 detail TEXT NOT NULL
);

CREATE VIEW active_polynomials AS
 SELECT c.id AS campaign_id,c.label,p.*
 FROM campaigns c
 JOIN active a ON a.campaign_id=c.id
 JOIN polynomials p ON p.variant_id=a.variant_id;

COMMIT;
''')
            with db:
                event(db, 'CREATE_DATABASE', {'schema': 1})
        from DABCTA_64F4_EXPLOITATION import install
        with db:
            install(db)
        from DABCTA_64H2_STATISTICAL_STORAGE import install as install_shared
        install_shared(db)
        return db
    except Exception:
        db.close()
        raise


def event(db, action, detail):
    db.execute(
        'INSERT INTO journal(utc,actor,action,detail) VALUES(?,?,?,?)',
        (
            datetime.now(timezone.utc).isoformat(),
            getpass.getuser(),
            action,
            dump(detail),
        ),
    )


def known(db, candidate):
    run = candidate['run']
    row = db.execute(
        'SELECT * FROM origins WHERE run_id=?',
        (run['run_id'],),
    ).fetchone()
    if row and row['excel_sha'] != run['xlsx_sha256']:
        raise ValueError(
            'Même run_id mais Excel différent de celui enregistré'
        )
    return row if row and row['status'] != 'REOPENED' else None


QUALIFICATION_FIELDS = ('report_number', 'test_date', 'screw_lot', 'nut_lot', 'washer_lot')


def campaign_changes(before, after):
    return [{'key': k, 'before': before.get(k), 'after': after.get(k)}
            for k in QUALIFICATION_FIELDS
            if normalized(before.get(k)) != normalized(after.get(k))]


def same_export_context(a, b):
    return (a['input_key'], a['result_key'], normalized(a['campaign_metadata'])) == (
        b['input_key'], b['result_key'], normalized(b['campaign_metadata']))


def record(db, candidate, campaign_id=None, choice='keep', reason='', label='', expected_active=-1, expected_revision=None, qualification=None, require_qualification=False):
    """Conserve candidat, arbitrage et référence active en une transaction."""
    run = candidate['run']
    with db:
        db.execute('BEGIN IMMEDIATE')
        if expected_revision is not None and db.execute('SELECT max(revision) FROM journal').fetchone()[0] != expected_revision:
            raise ValueError('La base a changé ; actualiser avant de décider')
        if known(db, candidate) and choice != 'share':
            return 'DÉJÀ TRAITÉ'

        if choice == 'ignore':
            if not reason.strip():
                raise ValueError('Motif obligatoire')
            db.execute(
                '''INSERT INTO origins VALUES(?,?,?,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET
                   variant_id=excluded.variant_id,
                   status=excluded.status,
                   provenance=excluded.provenance''',
                (
                    run['run_id'], run['xlsx_sha256'],
                    None, 'IGNORED', dump(candidate),
                ),
            )
            event(db, 'IGNORE', {
                'run': run['run_id'], 'reason': reason
            })
            return 'ÉCARTÉ'

        from DABCTA_64E4_FILIATION import guard_record
        if choice != 'share':
            guard_record(db, candidate, campaign_id)
        from DABCTA_64F1_QUALIFICATION import require
        require(db, candidate, check_files=True)
        prior_metadata = None
        qualification_changes = []
        if campaign_id is None:
            nearby = db.execute('SELECT metadata FROM campaigns WHERE config_id=?', (candidate['config_key'],)).fetchall()
            needs = any(campaign_changes(json.loads(r[0]), candidate['campaign_metadata']) for r in nearby)
            if require_qualification and needs and qualification != 'new':
                raise ValueError('Rapport/date/lots différents : confirmer une nouvelle campagne')
        else:
            row = db.execute('SELECT metadata FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
            if row:
                prior_metadata = json.loads(row[0])
                qualification_changes = campaign_changes(prior_metadata, candidate['campaign_metadata'])
                if require_qualification and qualification_changes and qualification != 'same':
                    raise ValueError('Rapport/date/lots différents : confirmer la même campagne ou en créer une nouvelle')
        if campaign_id is None:
            if not label.strip():
                raise ValueError('Libellé de campagne obligatoire')
            db.execute(
                'INSERT OR IGNORE INTO configurations VALUES(?,?)',
                (candidate['config_key'], dump(candidate['physical'])),
            )
            campaign_id = db.execute(
                '''INSERT INTO campaigns(config_id,label,metadata)
                   VALUES(?,?,?)''',
                (
                    candidate['config_key'], label,
                    dump(candidate['campaign_metadata']),
                ),
            ).lastrowid

        campaign = db.execute(
            'SELECT * FROM campaigns WHERE id=?', (campaign_id,)
        ).fetchone()
        if not campaign or campaign['config_id'] != candidate['config_key']:
            raise ValueError(
                'Campagne absente ou configuration physique différente'
            )

        previous = db.execute(
            'SELECT variant_id FROM active WHERE campaign_id=?',
            (campaign_id,),
        ).fetchone()
        previous = previous[0] if previous else None
        if expected_active != -1 and previous != expected_active:
            raise ValueError(
                'Résultat actif modifié pendant le choix ; relancer le scan'
            )

        if choice == 'share':
            if not reason.strip() or qualification != 'same':
                raise ValueError('Confirmer la même campagne et justifier le partage statistique')
            from DABCTA_64H2_STATISTICAL_STORAGE import validate_share
            validate_share(db, candidate, campaign_id, previous)

        existing = db.execute(
            '''SELECT id FROM variants
               WHERE campaign_id=? AND input_key=? AND result_key=?''',
            (
                campaign_id,
                candidate['input_key'],
                candidate['result_key'],
            ),
        ).fetchone()

        if existing:
            variant_id = existing[0]
            action = 'KNOWN_VARIANT'
        else:
            if choice not in ('keep', 'replace', 'share') or not reason.strip():
                raise ValueError('Décision et motif obligatoires')
            variant_id = db.execute(
                '''INSERT INTO variants(
                   campaign_id,input_key,result_key,payload)
                   VALUES(?,?,?,?)''',
                (
                    campaign_id, candidate['input_key'],
                    candidate['result_key'], dump(candidate),
                ),
            ).lastrowid
            db.executemany(
                'INSERT INTO polynomials VALUES(?,?,?,?,?)',
                [
                    (
                        variant_id, p['Type'], p['Stat'],
                        p['DABCTA_category'], dump(p),
                    )
                    for p in run['tables']['POLY_FITS_STATS']
                ],
            )
            if previous is None or choice == 'replace':
                db.execute(
                    '''INSERT INTO active VALUES(?,?)
                       ON CONFLICT(campaign_id) DO UPDATE SET
                       variant_id=excluded.variant_id''',
                    (campaign_id, variant_id),
                )
                action = 'ACTIVATE' if previous is None else 'REPLACE'
            else:
                action = 'KEEP_EXISTING'

        if choice == 'share':
            from DABCTA_64H2_STATISTICAL_STORAGE import attach, members
            if variant_id in members(db, previous) and known(db, candidate):
                return 'DÉJÀ RATTACHÉ'
            attach(db, previous, variant_id)
            action = 'SHARE_STATISTICAL_VARIANT'

        db.execute(
            '''INSERT INTO origins VALUES(?,?,?,?,?)
               ON CONFLICT(run_id) DO UPDATE SET
               variant_id=excluded.variant_id,
               status=excluded.status,
               provenance=excluded.provenance''',
            (
                run['run_id'], run['xlsx_sha256'],
                variant_id, action, dump(candidate),
            ),
        )
        detail = {'campaign': campaign_id, 'candidate': variant_id,
                  'previous_active': previous, 'run': run['run_id'], 'reason': reason}
        if qualification == 'same' and qualification_changes:
            corrected = dict(prior_metadata)
            for item in qualification_changes:
                corrected[item['key']] = item['after']
            db.execute('UPDATE campaigns SET metadata=? WHERE id=?', (dump(corrected), campaign_id))
            detail.update(qualification='same', metadata_before=prior_metadata,
                          metadata_after=corrected, corrected_fields=qualification_changes)
        elif qualification == 'new':
            detail['qualification'] = 'new'
        event(db, action, detail)
        return action

def choose(prompt, allowed):
    while True:
        value = input(prompt).strip()
        if value in allowed:
            return value
        print('Choix attendu :', ', '.join(sorted(allowed)))


def reason():
    while True:
        text = input('Motif (conservé au journal) : ').strip()
        if text:
            return text


def import_one(db, c):
    run = c['run']
    if known(db, c):
        print('Déjà traité :', run['run_id'])
        return

    matches = db.execute(
        '''SELECT id,campaign_id,payload FROM variants
           WHERE input_key=? AND result_key=?''',
        (c['input_key'], c['result_key']),
    ).fetchall()
    matches = [
        r for r in matches
        if normalized(json.loads(r['payload'])['campaign_metadata'])
        == normalized(c['campaign_metadata'])
    ]
    if len(matches) == 1:
        print(record(
            db, c, matches[0]['campaign_id'],
            reason='Variante déjà arbitrée',
        ))
        return

    for ignored in db.execute(
        "SELECT provenance FROM origins WHERE status='IGNORED'"
    ):
        prior = json.loads(ignored[0])
        if same_export_context(prior, c):
            print(record(
                db, c, choice='ignore',
                reason='Exclusion antérieure reconduite',
            ))
            return

    print('\nCandidat :', run['run_id'], run['identity'])
    print('Informations campagne :', c['campaign_metadata'])
    print(
        'Essais retenus :', run['accepted_count'],
        '| Répertoire :', run['copies'][0],
    )

    campaigns = db.execute(
        'SELECT * FROM campaigns WHERE config_id=? ORDER BY id',
        (c['config_key'],),
    ).fetchall()
    for campaign in campaigns:
        print(f"  {campaign['id']} : {campaign['label']}")
        print('   ', json.loads(campaign['metadata']))

    print(
        'N : nouvelle campagne | X : écarter durablement | '
        'Entrée : reporter'
    )
    answer = choose(
        'Campagne existante (numéro), N ou X : ',
        {str(r['id']) for r in campaigns} | {'N', 'X', ''},
    )
    if not answer:
        with db:
            event(db, 'DEFER', {'run': run['run_id']})
        return

    if answer == 'X':
        print(record(db, c, choice='ignore', reason=reason()))
        return

    if answer == 'N':
        label = input('Nom de cette campagne : ').strip()
        print(record(db, c, label=label, reason=reason()))
        return

    cid = int(answer)
    equivalent = db.execute(
        '''SELECT id FROM variants
           WHERE campaign_id=? AND input_key=? AND result_key=?''',
        (cid, c['input_key'], c['result_key']),
    ).fetchone()
    if equivalent:
        print(record(
            db, c, cid,
            reason='Variante déjà arbitrée : décision conservée',
        ))
        return

    active = db.execute(
        '''SELECT v.* FROM variants v
           JOIN active a ON a.variant_id=v.id
           WHERE a.campaign_id=?''',
        (cid,),
    ).fetchone()

    if active:
        old = json.loads(active['payload'])
        print(
            'Résultat actif : variante', active['id'],
            '| essais :', old['run']['accepted_count'],
        )
        for key in c['inputs']:
            if normalized(c['inputs'][key]) != normalized(old['inputs'][key]):
                print('Différence :', key)
                if isinstance(c['inputs'][key], dict):
                    fields = set(c['inputs'][key]) | set(old['inputs'][key])
                    for field in sorted(fields):
                        before = old['inputs'][key].get(field)
                        after = c['inputs'][key].get(field)
                        if normalized(before) != normalized(after):
                            print(' ', field, ':', before, '->', after)

        for title, a, b in [('Retirés', old, c), ('Ajoutés', c, old)]:
            selected = {
                r['SHA256']: r['Source_Name']
                for r in a['run']['tables']['ARCTA_SOURCES']
                if r.get('Accepted_For_ARCTA') is True
            }
            other = {
                r['SHA256']
                for r in b['run']['tables']['ARCTA_SOURCES']
                if r.get('Accepted_For_ARCTA') is True
            }
            print(
                title, ':',
                ', '.join(
                    v for k, v in selected.items() if k not in other
                ) or 'aucun',
            )

        if active['input_key'] == c['input_key']:
            print(
                'CONFLIT : entrées archivées identiques, '
                'résultats différents.'
            )

        answer = choose(
            'G : garder actif | R : remplacer par candidat | '
            'Entrée : reporter : ',
            {'G', 'R', ''},
        )
        if not answer:
            with db:
                event(db, 'DEFER', {
                    'run': run['run_id'], 'campaign': cid
                })
            return

        print(record(
            db, c, cid,
            'replace' if answer == 'R' else 'keep',
            reason(),
            expected_active=active['id'],
        ))
    else:
        print(record(db, c, cid, reason=reason()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'database', help='Chemin du fichier SQLite à créer ou ouvrir'
    )
    parser.add_argument(
        'outputs', nargs='?', help='Dossier ARCTA_OUTPUTS'
    )
    parser.add_argument('--journal', action='store_true')
    parser.add_argument(
        '--reconsider', help='Réouvrir une exclusion : run_id'
    )
    parser.add_argument(
        '--activate', type=int,
        help='Réviser un choix : identifiant de variante',
    )
    args = parser.parse_args()
    db = connect(args.database)

    try:
        if args.journal:
            for row in db.execute(
                'SELECT * FROM journal ORDER BY revision'
            ):
                print(dict(row))

        elif args.reconsider:
            target = db.execute(
                "SELECT * FROM origins WHERE run_id=? AND status='IGNORED'",
                (args.reconsider,),
            ).fetchone()
            if not target:
                raise ValueError(
                    'Run exclu introuvable ; '
                    'pour une variante utiliser --activate'
                )
            prior = json.loads(target['provenance'])
            motif = reason()
            with db:
                db.execute('BEGIN IMMEDIATE')
                rows = db.execute(
                    "SELECT * FROM origins WHERE status='IGNORED'"
                ).fetchall()
                for row in rows:
                    other = json.loads(row['provenance'])
                    if same_export_context(other, prior):
                        event(db, 'REOPEN_EXCLUSION', {
                            'previous': dict(row),
                            'reason': motif,
                        })
                        db.execute(
                            "UPDATE origins SET status='REOPENED' WHERE run_id=?",
                            (row['run_id'],),
                        )
            print('Exclusion réouverte ; relancer le scan pour choisir.')

        elif args.activate is not None:
            row = db.execute(
                'SELECT campaign_id FROM variants WHERE id=?',
                (args.activate,),
            ).fetchone()
            if not row:
                raise ValueError('Variante inconnue')
            motif = reason()
            with db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute(
                    'SELECT variant_id FROM active WHERE campaign_id=?',
                    (row[0],),
                ).fetchone()
                db.execute(
                    '''INSERT INTO active VALUES(?,?)
                       ON CONFLICT(campaign_id) DO UPDATE SET
                       variant_id=excluded.variant_id''',
                    (row[0], args.activate),
                )
                event(db, 'REVISE_SELECTION', {
                    'campaign': row[0],
                    'previous': old[0] if old else None,
                    'selected': args.activate,
                    'reason': motif,
                })

        elif args.outputs:
            scan = inventory(args.outputs)
            for error in scan['errors']:
                print(
                    'NON IMPORTÉ :', error['manifest'],
                    '|', error['error'],
                )
            for run in scan['runs']:
                try:
                    import_one(db, prepare(run))
                except (ValueError, KeyError, OSError) as exc:
                    print('NON IMPORTÉ :', run['run_id'], '|', exc)

        else:
            parser.error('Fournir outputs, --journal ou --activate')

        print('Résultats actifs :')
        for row in db.execute(
            '''SELECT c.id,c.label,a.variant_id
               FROM campaigns c
               JOIN active a ON a.campaign_id=c.id'''
        ):
            print(dict(row))
        print(
            'Révision de base :',
            db.execute('SELECT max(revision) FROM journal').fetchone()[0],
        )
    finally:
        db.close()


if __name__ == '__main__':
    main()