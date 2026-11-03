"""Polynômes mutualisés, provenance par run et déclinaisons statistiques explicites.

Les instantanés JSON historiques restent des archives d'audit immuables.
La vue polynomials assure la compatibilité des importateurs existants.
"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import DABCTA_64B_BASE as core


def canonical(data):
    # Pas d'arrondi ni de rapprochement numérique approché dans le stockage.
    return core.dump(core.normalized(json.loads(data)))


def install(db):
    db.create_function('dabcta_poly_json', 1, canonical, deterministic=True)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='polynomial_objects'").fetchone():
        return
    if db.in_transaction:
        raise ValueError('Migration 64H2 attendue hors transaction')
    count = db.execute('SELECT count(*) FROM polynomials').fetchone()[0]
    backup = None
    if count:
        location = db.execute('PRAGMA database_list').fetchone()[2]
        if not location:
            raise ValueError('Migration d’une base en mémoire non prise en charge')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        backup = str(Path(location).with_name(Path(location).name + '.before-64H2-' + stamp + '.bak'))
        with closing(sqlite3.connect(backup)) as copy:
            db.backup(copy)
    with db:
        db.execute('BEGIN IMMEDIATE')
        # Un autre processus peut avoir migré pendant la sauvegarde.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='polynomial_objects'").fetchone():
            return
        db.execute('''CREATE TABLE polynomial_objects(
            id INTEGER PRIMARY KEY, family TEXT NOT NULL, statistic TEXT NOT NULL,
            category TEXT NOT NULL, data TEXT NOT NULL,
            UNIQUE(family,statistic,category,data))''')
        db.execute('''CREATE TABLE polynomial_links(
            variant_id INTEGER NOT NULL REFERENCES variants,
            object_id INTEGER NOT NULL REFERENCES polynomial_objects,
            PRIMARY KEY(variant_id,object_id))''')
        db.execute('''CREATE TABLE statistical_members(
            anchor_variant INTEGER NOT NULL REFERENCES variants,
            variant_id INTEGER PRIMARY KEY REFERENCES variants)''')
        db.execute('''INSERT OR IGNORE INTO polynomial_objects(family,statistic,category,data)
            SELECT family,statistic,category,dabcta_poly_json(data) FROM polynomials''')
        db.execute('''INSERT OR IGNORE INTO polynomial_links
            SELECT p.variant_id,o.id FROM polynomials p JOIN polynomial_objects o
            ON o.family=p.family AND o.statistic=p.statistic AND o.category=p.category
            AND o.data=dabcta_poly_json(p.data)''')
        # Vérifie le contenu, pas seulement le nombre (les doublons exacts sont fusionnés).
        lost = db.execute('''SELECT variant_id,family,statistic,category,dabcta_poly_json(data)
            FROM polynomials EXCEPT SELECT l.variant_id,o.family,o.statistic,o.category,o.data
            FROM polynomial_links l JOIN polynomial_objects o ON o.id=l.object_id''').fetchone()
        if lost:
            raise ValueError('Migration 64H2 : polynôme non conservé')
        db.execute('DROP TABLE polynomials')
        db.execute('''CREATE VIEW polynomials AS
            SELECT l.variant_id,o.family,o.statistic,o.category,o.data
            FROM polynomial_links l JOIN polynomial_objects o ON o.id=l.object_id''')
        db.execute('''CREATE TRIGGER polynomial_insert INSTEAD OF INSERT ON polynomials BEGIN
            INSERT OR IGNORE INTO polynomial_objects(family,statistic,category,data)
                VALUES(NEW.family,NEW.statistic,NEW.category,dabcta_poly_json(NEW.data));
            INSERT OR IGNORE INTO polynomial_links
                SELECT NEW.variant_id,id FROM polynomial_objects
                WHERE family=NEW.family AND statistic=NEW.statistic AND category=NEW.category
                AND data=dabcta_poly_json(NEW.data);
            END''')
        refresh_views(db)
        if count:
            core.event(db, 'MIGRATE_SHARED_POLYNOMIALS', {'backup': backup, 'legacy_rows': count,
                'objects': db.execute('SELECT count(*) FROM polynomial_objects').fetchone()[0]})


def refresh_views(db):
    """À appeler aussi après activation initiale du sas métier."""
    from DABCTA_64F1_QUALIFICATION import enabled
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='statistical_members'").fetchone():
        return
    for name in ('active_polynomials', 'active_statistical_polynomials', 'exploitable_statistical_runs'):
        db.execute('DROP VIEW IF EXISTS ' + name)
    qualification = ('AND a.variant_id IN (SELECT id FROM qualified_variants) '
                     'AND v.id IN (SELECT id FROM qualified_variants)' if enabled(db) else '')
    db.execute('''CREATE VIEW exploitable_statistical_runs AS
        SELECT a.campaign_id,v.id AS variant_id,a.variant_id AS reference_variant,
        COALESCE(m.anchor_variant,a.variant_id) AS analysis_id,
        json_extract(v.payload,'$.run.run_id') AS run_id,
        json_extract(v.payload,'$.inputs.settings') AS settings
        FROM active a LEFT JOIN statistical_members m ON m.variant_id=a.variant_id
        JOIN variants v ON v.campaign_id=a.campaign_id AND
        (v.id=a.variant_id OR v.id IN
            (SELECT variant_id FROM statistical_members WHERE anchor_variant=m.anchor_variant))
        WHERE 1=1 ''' + qualification)
    db.execute('''CREATE VIEW active_statistical_polynomials AS
        SELECT r.*,l.object_id AS polynomial_id,o.family,o.statistic,o.category,o.data
        FROM exploitable_statistical_runs r JOIN polynomial_links l ON l.variant_id=r.variant_id
        JOIN polynomial_objects o ON o.id=l.object_id''')
    # Vue historique = union des polynômes, un objet une fois par campagne.
    # Pour choisir un intervalle, utiliser active_statistical_polynomials et settings.
    db.execute('''CREATE VIEW active_polynomials AS
        SELECT p.campaign_id,c.label,min(p.variant_id) AS variant_id,
        p.family,p.statistic,p.category,p.data
        FROM active_statistical_polynomials p JOIN campaigns c ON c.id=p.campaign_id
        GROUP BY p.campaign_id,p.polynomial_id''')


def members(db, variant):
    row = db.execute('SELECT anchor_variant FROM statistical_members WHERE variant_id=?', (variant,)).fetchone()
    if not row:
        return [variant]
    return [r[0] for r in db.execute('SELECT variant_id FROM statistical_members WHERE anchor_variant=? ORDER BY variant_id', (row[0],))]


def validate_share(db, candidate, campaign, previous):
    from DABCTA_64F1_QUALIFICATION import enabled, require
    from apps.arcta_web.dabcta_reconciliation import classify, acquisitions
    if not enabled(db) or previous is None:
        raise ValueError('Partage statistique : référence qualifiée et sas métier requis')
    require(db, candidate, check_files=True)
    reference = db.execute('SELECT payload FROM variants WHERE id=? AND campaign_id=?', (previous,campaign)).fetchone()
    if reference is None:
        raise ValueError('Référence de campagne absente')
    original = json.loads(reference[0])
    require(db,original)
    if core.normalized(original['run'].get('manifest',{}).get('arcta_reanalysis')) != core.normalized(candidate['run'].get('manifest',{}).get('arcta_reanalysis')):
        raise ValueError('Partage refusé : filiation de réanalyse différente')
    # La référence reste active : ses protections de filiation demeurent en vigueur.
    # Vérification explicite car le partage ne déclenche pas les triggers sur active.
    selected = acquisitions(candidate,True)
    for row in db.execute('''SELECT v.payload FROM active a JOIN variants v ON v.id=a.variant_id
        WHERE a.campaign_id!=? AND v.id IN (SELECT id FROM qualified_variants)''', (campaign,)):
        if selected & acquisitions(json.loads(row[0]),True):
            raise ValueError('Partage refusé : acquisitions déjà exploitées dans une autre campagne')
    for vid in members(db, previous):
        prior = json.loads(db.execute('SELECT payload FROM variants WHERE id=?', (vid,)).fetchone()[0])
        kind = classify(prior,candidate)['kind']
        if kind not in {'STATISTICAL_VARIANT','DUPLICATE'}:
            raise ValueError('Partage refusé : écart incompatible avec le run ' + str(vid) + ' (' + kind + ')')


def attach(db, previous, variant):
    row = db.execute('SELECT anchor_variant FROM statistical_members WHERE variant_id=?', (previous,)).fetchone()
    anchor = row[0] if row else previous
    prior = db.execute('SELECT anchor_variant FROM statistical_members WHERE variant_id=?', (variant,)).fetchone()
    if prior and prior[0] != anchor:
        raise ValueError('Run déjà rattaché à une autre analyse')
    db.execute('INSERT OR IGNORE INTO statistical_members VALUES(?,?)', (anchor,previous))
    db.execute('INSERT OR IGNORE INTO statistical_members VALUES(?,?)', (anchor,variant))


def describe(db, variant):
    from DABCTA_64F1_QUALIFICATION import state
    result = []
    for vid in members(db,variant):
        candidate = json.loads(db.execute('SELECT payload FROM variants WHERE id=?', (vid,)).fetchone()[0])
        exposed = db.execute('SELECT analysis_id FROM exploitable_statistical_runs WHERE variant_id=?', (vid,)).fetchone()
        result.append({'variant':vid,'run':candidate['run']['run_id'],
            'settings':candidate['inputs']['settings'], 'business':state(db,candidate)['status'],
            'exploitable':bool(exposed)})
    return result


def select_polynomials(db, campaign, settings):
    """Sélection explicite : filtre sur les paramètres demandés, provenance regroupée.

    Ne reconstitue pas des bornes absentes. Des paramètres insuffisants qui
    sélectionnent plusieurs polynômes différents d'un même type sont refusés.
    """
    if not isinstance(settings,dict) or not settings:
        raise ValueError('Préciser les paramètres statistiques recherchés')
    chosen = {}
    identities = {}
    for row in db.execute('SELECT * FROM active_statistical_polynomials WHERE campaign_id=?', (campaign,)):
        actual = json.loads(row['settings'])
        data = json.loads(row['data'])
        if actual.get('TORQUE_BASIS') == 'DUAL':
            from arcta.dual_campaign import for_mode
            basis = settings.get('TORQUE_BASIS')
            if basis not in ('TOTAL', 'EFFECTIVE'):
                raise ValueError('Préciser TORQUE_BASIS : TOTAL ou EFFECTIVE')
            if not for_mode([data], basis):
                continue
            actual = {**actual, 'TORQUE_BASIS': basis}
        if any(k not in actual or core.normalized(actual[k]) != core.normalized(v) for k,v in settings.items()):
            continue
        data = json.loads(row['data'])
        # 64I1B : la clé d'ambiguïté inclut le segment de validité S des tolérances.
        key = (data.get('Compute_Sheet'),row['family'],row['statistic'],str(data.get('S','') or ''))
        if key in identities and identities[key] != row['polynomial_id']:
            raise ValueError('Sélection statistique ambiguë : préciser les paramètres')
        identities[key] = row['polynomial_id']
        item = chosen.setdefault(row['polynomial_id'], {'polynomial_id':row['polynomial_id'],
            'polynomial':data,'runs':[]})
        item['runs'].append({'run':row['run_id'],'variant':row['variant_id'],'settings':actual})
    return list(chosen.values())
