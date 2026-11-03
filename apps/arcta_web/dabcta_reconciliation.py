"""64F3: qualification individuelle distincte de l'arbitrage comparatif."""
import json
import sqlite3
import DABCTA_64B_BASE as core
from DABCTA_64E4_FILIATION import links

INTERVAL_SETTINGS = {'ISO_TOL_P_CONTENT', 'ISO_TOL_CONF_LEVEL', 'ISO_MEDIAN_CONF_LEVEL', 'MEAN_CI_CONF_LEVEL'}


def acquisitions(c, selected=False):
    return {r['SHA256'].lower() for r in c['run']['tables']['ARCTA_SOURCES']
            if isinstance(r.get('SHA256'),str) and r['SHA256'].strip()
            and (not selected or r.get('Accepted_For_ARCTA') is True)}


def classify(old, new):
    a,b=acquisitions(old),acquisitions(new)
    sa,sb=acquisitions(old,True),acquisitions(new,True)
    settings=sorted(k for k in set(old['inputs']['settings'])|set(new['inputs']['settings'])
                    if core.normalized(old['inputs']['settings'].get(k))!=core.normalized(new['inputs']['settings'].get(k)))
    common={'common':len(a&b),'existing_only':len(a-b),'candidate_only':len(b-a),
            'selected_common':len(sa&sb),'selected_existing_only':len(sa-sb),
            'selected_candidate_only':len(sb-sa),'settings_changed':settings}
    missing=any(not isinstance(r.get('SHA256'),str) or not r['SHA256'].strip()
                for c in (old,new) for r in c['run']['tables']['ARCTA_SOURCES'])
    if missing or not a or not b:
        kind='UNDETERMINED'
    elif a==b:
        if sa!=sb:kind='SELECTION_VARIANT'
        elif old['input_key']==new['input_key']:
            kind='DUPLICATE' if old['result_key']==new['result_key'] else 'RESULT_CONFLICT'
        else:
            other_changed=any(core.normalized(old['inputs'].get(k))!=core.normalized(new['inputs'].get(k))
                              for k in set(old['inputs'])|set(new['inputs']) if k!='settings')
            kind='ANALYSIS_VARIANT'
            if settings and set(settings)<=INTERVAL_SETTINGS and not other_changed:
                from .dabcta_statistical_variant import check
                audit = check(old, new, settings)
                common['statistical_check'] = audit
                kind = {'PASSED': 'STATISTICAL_VARIANT', 'CONFLICT': 'RESULT_CONFLICT',
                        'UNVERIFIABLE': 'UNDETERMINED'}[audit['status']]
    elif a&b:kind='PARTIAL_OVERLAP'
    else:kind='COMPLEMENTARY'
    return {**common,'kind':kind}


def matches(db, candidate, include_history=False):
    from DABCTA_64F1_QUALIFICATION import state
    from DABCTA_64E4_FILIATION import protected
    result=[]
    for row in db.execute('''SELECT c.id,c.label,c.metadata,a.variant_id FROM campaigns c
        LEFT JOIN active a ON a.campaign_id=c.id WHERE c.config_id=? ORDER BY c.id''',(candidate['config_key'],)):
        vid=row['variant_id']
        if vid is None:
            last=db.execute('SELECT id FROM variants WHERE campaign_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
            vid=last[0] if last else None
        if vid is None:continue
        old=json.loads(db.execute('SELECT payload FROM variants WHERE id=?',(vid,)).fetchone()[0])
        if not include_history and (row['variant_id'] is None or not state(db,old)['eligible']):continue
        labels={r['Code']:r['Libellé'] for r in candidate['run']['tables']['ARCTA_CONFIG_SYNTHESIS']}
        fields=[]
        for group in ('physical','constants','settings','campaign_metadata'):
            a,b=(json.loads(row['metadata']),candidate['campaign_metadata']) if group=='campaign_metadata' else (old['inputs'].get(group,{}),candidate['inputs'].get(group,{}))
            for key in sorted(set(a)|set(b)):
                fields.append({'group':group,'key':key,'label':labels.get(key,key),'before':a.get(key),'after':b.get(key),
                               'different':core.normalized(a.get(key))!=core.normalized(b.get(key))})
        result.append({'campaign':row['id'],'label':row['label'],'variant':vid,'active':row['variant_id'],
                       'business_status':state(db,old)['status'],'existing_qualified':state(db,old)['eligible'],
                       'protected':protected(db,row['id']),'run':old['run']['run_id'],
                       'existing_count':old['run']['accepted_count'],**classify(old,candidate),'fields':fields})
    return result


def admit(db, candidate, body):
    from DABCTA_64F1_QUALIFICATION import enabled,require,revision
    revision(db,body.get('revision'))
    if not enabled(db):raise ValueError('Activer le sas métier avant capitalisation')
    require(db,candidate,check_files=True)
    if matches(db,candidate):raise ValueError('Rapprochement détecté : passer par Réconcilier')
    if candidate['run']['manifest'].get('arcta_reanalysis'):
        raise ValueError('Une réanalyse doit passer par la capitalisation avec filiation')
    from DABCTA_64F4_EXPLOITATION import historical_targets
    history=matches(db,candidate,include_history=True)
    targets=historical_targets(db,candidate,history)
    cid=body.get('historical_campaign')
    if cid is None and len(targets)==1:cid=targets[0]['campaign']
    if len(targets)>1 and cid is None:
        raise ValueError('Plusieurs identités historiques possibles : choisir la campagne de rattachement')
    if cid is not None and (type(cid) is not int or cid not in {r['campaign'] for r in targets}):
        raise ValueError('Rattachement historique invalide ou devenu obsolète')
    return core.record(db,candidate,campaign_id=cid,choice='replace',
                       label=str(body.get('label','')).strip(),reason=str(body.get('reason','')).strip(),
                       qualification='same' if cid is not None else 'new',require_qualification=True,
                       expected_revision=body.get('revision'))


def arbitrate(db,candidate,body):
    from DABCTA_64F1_QUALIFICATION import enabled,require,revision
    revision(db,body.get('revision'))
    if not enabled(db):raise ValueError('Activer le sas métier avant arbitrage')
    reason=str(body.get('reason','')).strip()
    if not reason:raise ValueError('Motif d’arbitrage obligatoire')
    # Deferral is traced without importing or approving anything.
    if body.get('choice')=='defer':
        with db:
            db.execute('BEGIN IMMEDIATE')
            from DABCTA_64F1_QUALIFICATION import revision
            revision(db,body.get('revision'))
            core.event(db,'DEFER_RECONCILIATION',{'run':candidate['run']['run_id'],'reason':reason})
        return
    require(db,candidate,check_files=True)
    selected=next((r for r in matches(db,candidate) if r['campaign']==body.get('campaign')),None)
    if selected is None:raise ValueError('Choisir une campagne de comparaison actuelle')
    if selected['protected'] and not (body.get('choice')=='share' and selected['kind']=='STATISTICAL_VARIANT'):raise ValueError('Campagne liée à un regroupement : arbitrage ordinaire interdit')
    kind=selected['kind'];choice=body.get('choice')
    if kind in {'RESULT_CONFLICT','PARTIAL_OVERLAP','UNDETERMINED'}:
        raise ValueError('Anomalie ou chevauchement à résoudre avant capitalisation')
    if kind=='COMPLEMENTARY':
        if any(r['kind']!='COMPLEMENTARY' for r in matches(db,candidate)):
            raise ValueError('Une autre campagne présente un recouvrement : résoudre tous les rapprochements')
        if choice!='distinct' or body.get('independent') is not True:
            raise ValueError('Confirmer les acquisitions indépendantes et créer une campagne distincte avant regroupement')
        return core.record(db,candidate,label=str(body.get('label','')).strip(),reason=reason,
                           qualification='new',require_qualification=True,expected_revision=body.get('revision'))
    if choice == 'share' and kind != 'STATISTICAL_VARIANT':
        raise ValueError('Seules les déclinaisons statistiques vérifiées peuvent coexister')
    if choice not in {'keep','replace','share'}:raise ValueError('Choisir une référence ou une déclinaison statistique vérifiée')
    if choice=='keep' and not selected['existing_qualified']:
        raise ValueError('Qualifier la référence existante avant de la conserver')
    if body.get('same_campaign') is not True:raise ValueError('Confirmer le rattachement à la même campagne')
    return core.record(db,candidate,selected['campaign'],choice,reason,expected_active=selected['active'],
                       qualification='same',require_qualification=True,expected_revision=body.get('revision'))


def finish_qualification(db,candidate,body):
    if body.get('status')!='APPROVED':
        return 'Décision métier enregistrée. Aucune capitalisation.'
    if core.known(db,candidate) or any(core.same_export_context(candidate,json.loads(r[0]))
                                     for r in db.execute('SELECT payload FROM variants')):
        return 'Run accepté. Résultat équivalent déjà arbitré : aucune nouvelle campagne créée.'
    if candidate['run']['manifest'].get('arcta_reanalysis') or matches(db,candidate):
        return 'Run accepté — en attente de réconciliation. Aucune capitalisation automatique.'
    label=' — '.join(str(candidate['campaign_metadata'].get(k) or '') for k in ('report_number','configuration_id')).strip(' —') or candidate['run']['run_id']
    try:
        admit(db,candidate,{**body,'label':label,'revision':db.execute('SELECT max(revision) FROM journal').fetchone()[0]})
    except (ValueError,OSError,sqlite3.DatabaseError) as exc:
        # Approval remains a valid separate decision; never pretend the import succeeded.
        return 'Qualification enregistrée, mais capitalisation non aboutie : '+str(exc)
    return 'Run accepté et capitalisé. Qualification et entrée en base sont tracées au journal.'
