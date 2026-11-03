"""64D : consultation de l'instantané capitalisé, sans relire les exports."""
import json


def catalogue(db, variant):
    if isinstance(variant, bool) or not isinstance(variant, int) or variant < 1:
        raise ValueError('Identifiant de variante invalide')
    # Une transaction de lecture garantit une révision cohérente avec le statut actif.
    db.execute('BEGIN')
    try:
        row = db.execute(
            'SELECT v.*, c.label, a.variant_id AS active_id FROM variants v '
            'JOIN campaigns c ON c.id=v.campaign_id '
            'LEFT JOIN active a ON a.campaign_id=c.id WHERE v.id=?', (variant,)
        ).fetchone()
        if row is None:
            raise ValueError('Variante inconnue dans cette base')
        candidate = json.loads(row['payload'])
        run = candidate['run']
        tables = run['tables']
        return {
            'revision': db.execute('SELECT max(revision) FROM journal').fetchone()[0],
            'variant': variant, 'campaign': row['campaign_id'], 'label': row['label'],
            'active': variant == row['active_id'], 'run': run['run_id'],
            'created_at': run['manifest'].get('created_at'),
            'accepted_count': run['accepted_count'],
            'config': tables.get('ARCTA_CONFIG_SYNTHESIS', []),
            'settings': candidate['inputs']['settings'],
            'sources': tables.get('ARCTA_SOURCES', []),
            'polynomials': [json.loads(p[0]) for p in db.execute('SELECT data FROM polynomials WHERE variant_id=?', (variant,))],
            'statistical_runs': __import__('DABCTA_64H2_STATISTICAL_STORAGE').describe(db,variant),
            'statistical_exploitable': db.execute('SELECT 1 FROM exploitable_statistical_runs WHERE variant_id=?', (variant,)).fetchone() is not None,
            'warnings': tables.get('ARCTA_TOLERANCE_WARNINGS', []),
            'tolerance': tables.get('ARCTA_TOLERANCE_DETAILS', []),
            'selflock': tables.get('ARCTA_SELF_LOCK_STATS', []),
            'copies': run.get('copies', []), 'excel_sha256': run.get('xlsx_sha256'),
            'origins': [dict(r) for r in db.execute(
                'SELECT run_id,excel_sha,status FROM origins WHERE variant_id=? ORDER BY run_id',
                (variant,))],
        }
    finally:
        db.rollback()
