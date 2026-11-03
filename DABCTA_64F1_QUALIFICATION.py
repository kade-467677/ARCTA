"""Sas métier local : identités déclarées, décisions documentées, exploitation filtrée."""
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
import DABCTA_64B_BASE as core
from DABCTA_64A_INVENTAIRE import read_run

STATUSES = {'APPROVED', 'REWORK', 'REJECTED', 'WITHDRAWN'}


def enabled(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='business_reviews'").fetchone() is not None


def signature(candidate):
    run = candidate['run']
    manifest = {k:v for k,v in run['manifest'].items() if k != 'published_directory'}
    data = (run['run_id'], run['xlsx_sha256'], core.dump(manifest))
    return core.fingerprint(data), data


def state(db, candidate):
    if not enabled(db):
        return {'status':'DISABLED','eligible':True}
    key, _ = signature(candidate)
    row = db.execute('SELECT * FROM business_reviews WHERE binding=?', (key,)).fetchone()
    return {**(dict(row) if row else {'status':'PENDING'}), 'eligible':bool(row and row['status']=='APPROVED')}


def revision(db, expected):
    if type(expected) is not int or db.execute('SELECT max(revision) FROM journal').fetchone()[0] != expected:
        raise ValueError('La base a changé : actualiser avant de décider')


def activate(db, body):
    if body.get('confirm') is not True or not str(body.get('reason','')).strip():
        raise ValueError('Confirmer l’activation du sas et renseigner son motif')
    with db:
        db.execute('BEGIN IMMEDIATE')
        revision(db, body.get('revision'))
        if enabled(db):
            return
        db.execute('''CREATE TABLE business_reviews(
            binding TEXT PRIMARY KEY,run_id TEXT NOT NULL,xlsx_sha TEXT NOT NULL,manifest TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('APPROVED','REWORK','REJECTED','WITHDRAWN')),
            producer TEXT NOT NULL,reviewer TEXT NOT NULL,document TEXT NOT NULL,document_revision TEXT NOT NULL,
            reason TEXT NOT NULL,utc TEXT NOT NULL,journal_revision INTEGER NOT NULL REFERENCES journal(revision))''')
        db.execute('''CREATE VIEW qualified_variants AS SELECT v.id FROM variants v JOIN business_reviews r
            ON r.run_id=json_extract(v.payload,'$.run.run_id')
            AND r.xlsx_sha=json_extract(v.payload,'$.run.xlsx_sha256')
            AND r.manifest=json_remove(json_extract(v.payload,'$.run.manifest'),'$.published_directory')
            WHERE r.status='APPROVED' ''')
        db.execute('DROP VIEW active_polynomials')
        db.execute('''CREATE VIEW active_polynomials AS SELECT c.id AS campaign_id,c.label,p.*
            FROM campaigns c JOIN active a ON a.campaign_id=c.id JOIN polynomials p ON p.variant_id=a.variant_id
            WHERE a.variant_id IN (SELECT id FROM qualified_variants)''')
        for operation in ('INSERT','UPDATE'):
            db.execute(f'''CREATE TRIGGER business_active_{operation.lower()} BEFORE {operation} ON active
                WHEN NEW.variant_id NOT IN (SELECT id FROM qualified_variants)
                BEGIN SELECT RAISE(ABORT,'Qualification metier valide requise pour cette variante'); END''')
        core.event(db,'ENABLE_BUSINESS_GATE',{'reason':body['reason'].strip(),
                    'identity_mode':'DECLARED','legacy_results':'REVIEW_REQUIRED'})
        from DABCTA_64F4_EXPLOITATION import install
        install(db,journal=False)
        from DABCTA_64H2_STATISTICAL_STORAGE import refresh_views
        refresh_views(db)


def verify_export(candidate):
    run=candidate['run'];root=Path(run['copies'][0]).resolve()
    fresh=read_run(root/'ARCTA_RUN_MANIFEST.json')
    if signature({'run':fresh}) != signature(candidate):
        raise ValueError('Export modifié depuis l’inventaire ; relancer l’inventaire')
    for name,digest in fresh['manifest'].get('files_sha256',{}).items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or core.sha256(path)!=digest:
            raise ValueError('Livrable absent ou modifié : '+name)
    return fresh


def identity(value):
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())


def decide(db, candidate, body):
    if not enabled(db):
        raise ValueError('Activer le sas métier pour cette base')
    status=body.get('status')
    if status not in STATUSES:
        raise ValueError('Décision métier inconnue')
    fields={}
    for key in ('producer','reviewer','document','document_revision','reason'):
        value=body.get(key)
        if not isinstance(value,str) or not value.strip() or len(value)>2000:
            raise ValueError('Champ métier obligatoire : '+key)
        fields[key]=value.strip()
    if identity(fields['producer'])==identity(fields['reviewer']):
        raise ValueError('Le producteur ARCTA et le validateur métier déclarés doivent être distincts')
    if body.get('attest') is not True:
        raise ValueError('Attester la revue des éléments du run et la référence documentaire')
    verify_export(candidate)
    binding,(run_id,xlsx_sha,manifest)=signature(candidate)
    with db:
        db.execute('BEGIN IMMEDIATE');revision(db,body.get('revision'))
        prior=state(db,candidate)
        if status=='WITHDRAWN' and prior['status']!='APPROVED':
            raise ValueError('Seule une validation en vigueur peut être retirée')
        if prior['status']==status and all(prior.get(k)==v for k,v in fields.items()):
            return
        utc=datetime.now(timezone.utc).isoformat()
        core.event(db,'BUSINESS_REVIEW',{'run':run_id,'binding':binding,'previous':prior.get('status'),
                    'status':status,**fields,'identity_mode':'DECLARED'})
        rev=db.execute('SELECT max(revision) FROM journal').fetchone()[0]
        db.execute('''INSERT INTO business_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(binding) DO UPDATE SET status=excluded.status,producer=excluded.producer,
            reviewer=excluded.reviewer,document=excluded.document,document_revision=excluded.document_revision,
            reason=excluded.reason,utc=excluded.utc,journal_revision=excluded.journal_revision''',
            (binding,run_id,xlsx_sha,manifest,status,fields['producer'],fields['reviewer'],fields['document'],
             fields['document_revision'],fields['reason'],utc,rev))


def require(db,candidate,check_files=False):
    if not enabled(db):
        return
    if not state(db,candidate)['eligible']:
        raise ValueError('Validation métier documentée requise pour ce run exact')
    if check_files:
        verify_export(candidate)


def catalogue_state(db,variant):
    row=db.execute('SELECT payload FROM variants WHERE id=?',(variant,)).fetchone()
    if row is None:
        raise ValueError('Variante inconnue')
    return state(db,json.loads(row[0]))
