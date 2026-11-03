// 64F3: décision sur un run ; comparaison et arbitrage dans leur espace.
const reconcileKinds={DUPLICATE:'Doublon — mêmes entrées et résultats',SELECTION_VARIANT:'Mêmes acquisitions — sélection différente',STATISTICAL_VARIANT:'Mêmes essais — paramètres CI / tolérance différents',ANALYSIS_VARIANT:'Mêmes essais — traitement différent',COMPLEMENTARY:'Même configuration — essais complémentaires',PARTIAL_OVERLAP:'Recouvrement partiel des acquisitions',RESULT_CONFLICT:'Anomalie — résultats supposés invariants différents',UNDETERMINED:'Comparaison non vérifiable avec les informations disponibles'};
businessLabels.APPROVED='Accepté pour capitalisation';businessLabels.REWORK='À retraiter — corrections requises';businessLabels.REJECTED='Rejeté — justification requise';
let reconcileSelected=null;
function reconcileGo(c){reconcileSelected=c.key;flowGo('reconcilier');renderReconciliation()}
review=function(){
  const c=candidate();$('review').hidden=!c;if(!c)return;
  $('review').querySelector('h2').textContent='Qualifier ce run de campagne';
  $('decision-form').hidden=true;const box=$('candidate-info');box.replaceChildren(summary(c));
  const config=document.createElement('details');config.append(text('summary','Configuration archivée à examiner'),
    table(['Paramètre','Valeur','Unité'],(c.qualification_config||[]).map(r=>[r['Libellé']||r.Code,catFormat(r.Valeur),r['Unité']||'—'])));box.append(config);
  box.append(text('p','Vérifier les entrées, les paramètres requis et appliqués, les décisions DIAG et les livrables. Cette décision porte sur ce seul run.','muted'));
  if(!state.business_gate){box.append(text('p','Activer le sas métier pour prendre une décision de qualification.','warn'));return}
  businessForm(box,c,{candidate:c.key,workflow:'qualification'});
  showHistoricalMatches(c,box);
  if(c.status!=='À examiner'){box.append(text('p','État d’inventaire : '+c.status+'. Aucune nouvelle capitalisation à décider.','muted'));return}
  const matches=c.reconciliation||[];
  if(matches.length||c.reanalysis){
    box.append(text('p',`${matches.length} campagne(s) de même configuration détectée(s). La comparaison et le choix de référence se font dans Réconcilier.`, 'warn'),
      button(c.business.eligible?'Comparer dans Réconcilier':'Consulter les rapprochements',()=>reconcileGo(c)));
  }else if(c.business.eligible&&c.status==='À examiner'){
    box.append(button('Intégrer en base',()=>task('Capitalisation…',async()=>{
      const label=[c.identity.report_number,c.identity.configuration_id].filter(Boolean).join(' — ')||c.key;
      state=await api('admit-qualified',{candidate:c.key,label,reason:c.business.reason,historical_campaign:historicalChoice(c)});render();status('Run capitalisé et décision tracée.');
    })));
  }
};
function renderReconciliation(){
  if(!state)return;
  let host=$('reconciliation');if(!host){host=text('section','');host.id='reconciliation';$('grouping').before(host)}
  host.replaceChildren(text('h2','Comparer un run en attente avec la base'));
  const stored=state.campaigns.flatMap(cp=>cp.eligible?cp.variants.filter(v=>v.statistical_shareable).map(v=>({cp,v})):[]);
  if(stored.length){
   const box=text('details','');box.append(text('summary',`${stored.length} déclinaison(s) statistique(s) déjà conservée(s), non encore partagée(s)`));
   for(const {cp,v} of stored){
    const item=text('section',''),reason=text('textarea',''),confirm=text('input','');confirm.type='checkbox';confirm.style.width='auto';
    const label=text('label',' Je confirme la même campagne et le rattachement à son analyse commune.');label.prepend(confirm);
    item.append(text('h3',`${cp.label} — ${typeof runName==='function'?runName(v.id):'Run_V'+v.id}`),
      text('p',`Run : ${v.run} · Référence : ${typeof runName==='function'?runName(cp.active):cp.active}`),
      table(['Paramètre','Référence','Run conservé'],Object.entries(v.statistical_settings||{}).filter(([k])=>['MEAN_CI_CONF_LEVEL','ISO_MEDIAN_CONF_LEVEL','ISO_TOL_P_CONTENT','ISO_TOL_CONF_LEVEL'].includes(k)).map(([k,x])=>[catParams[k]||k,catFormat((cp.variants.find(a=>a.id===cp.active)?.statistical_settings||{})[k]*100)+' %',catFormat(x*100)+' %'])),
      label,text('label','Motif du rattachement'),reason);
    item.append(button('Consulter les polynômes',()=>viewCatalogue(v.id)),button('Capitaliser cette déclinaison',()=>task('Rattachement statistique…',async()=>{
      if(!confirm.checked||!reason.value.trim())throw Error('Confirmer la campagne et renseigner le motif.');
      state=await api('share-stored-statistics',{variant:v.id,same_campaign:true,reason:reason.value.trim()});render();status('Déclinaison rattachée ; décision tracée au journal.');
    })));
    box.append(item);
   }
   host.append(box);
  }
  const candidates=state.candidates.filter(c=>(c.reconciliation?.length||c.reanalysis)&&c.status==='À examiner'&&!['REWORK','REJECTED','WITHDRAWN'].includes(c.business?.status));
  if(!candidates.length){host.append(text('p','Aucun candidat en attente de rapprochement. Inventorier les sources dans Ajouter ; les campagnes déjà capitalisées restent regroupables ci-dessous.'));return}
  const pick=document.createElement('select');pick.id='reconcile-candidate';
  for(const c of candidates){const o=text('option',runCaption(c));o.value=c.key;pick.append(o)}
  if(candidates.some(c=>c.key===reconcileSelected))pick.value=reconcileSelected;
  reconcileSelected=pick.value;
  host.append(text('p',`${candidates.length} run(s) inventorié(s) en attente de rapprochement. Les runs déjà arbitrés ne figurent pas dans ce sélecteur.`));
  const label=text('label','Run en attente — à comparer avec la base');label.append(pick);host.append(label);
  const body=text('div','');host.append(body);
  function display(){
    reconcileSelected=pick.value;const c=candidates.find(x=>x.key===pick.value);body.replaceChildren();
    if(c.reanalysis&&!(c.reconciliation||[]).some(r=>r.kind==='STATISTICAL_VARIANT')){
      body.append(text('p','Réanalyse agrégée : utiliser le contrôle de filiation ci-dessous.'));
      showAggregate(c,body);return;
    }
    const rows=c.reconciliation;
    body.append(text('h3','Run en attente : '+runCaption(c)),text('p',c.path,'path muted'),text('p','Chaque ligne ci-dessous compare cette référence au run en attente. Les acquisitions communes sont identifiées par empreinte des fichiers ; les essais retenus sont détaillés plus bas.'));
    body.append(table(['Référence comparée en base','Statut en base','Écart avec le run en attente','Acquisitions communes','Uniquement dans cette référence','Uniquement dans le run en attente'],rows.map(r=>[
      referenceCaption(r),referenceState(r),reconcileKinds[r.kind],r.common,r.existing_only,r.candidate_only])));
    const refs=document.createElement('select');for(const r of rows){const o=text('option',referenceCaption(r)+' · '+referenceState(r));o.value=r.campaign;refs.append(o)}
    const refLabel=text('label','Référence de la base à afficher en détail');refLabel.append(refs);body.append(refLabel);
    const detail=text('div','');body.append(detail);
    function comparePair(){
      const r=rows.find(x=>String(x.campaign)===refs.value);detail.replaceChildren();
      detail.append(text('h3',reconcileKinds[r.kind]),text('p','Qualification de la référence : '+(businessLabels[r.business_status]||'Non renseignée')),text('p',`Sélection retenue : ${r.selected_common} essais communs ; ${r.selected_existing_only} propres à la référence ; ${r.selected_candidate_only} propres au candidat.`));
      const changed=r.fields.filter(f=>f.different),same=r.fields.filter(f=>!f.different);
      const headers=['Information','En base : '+referenceCaption(r),'Run en attente : '+runCaption(c)];
      detail.append(text('p',referenceState(r),'muted'));
      if(r.kind==='RESULT_CONFLICT'&&!r.statistical_check)detail.append(text('p','Ce run et cette référence ont les mêmes entrées archivées comparées, mais des résultats exportés différents. Cela ne prouve pas que les campagnes de la base sont incohérentes entre elles. La cause reste à examiner ; aucune substitution automatique.','warn'));
      if(r.kind==='PARTIAL_OVERLAP')detail.append(text('p','Une partie des acquisitions du run existe déjà dans cette référence. Si elle est un regroupement, ce recouvrement peut être attendu. Il interdit de capitaliser à nouveau ces essais comme une campagne indépendante.','warn'));
      function values(f){return [deltaLabels[f.key]||f.label,deltaValue(f.before,f.key),deltaValue(f.after,f.key)]}
      detail.append(text('h3','Différences observées'),table(headers,changed.map(values)));
      if(!changed.length)detail.append(text('p','Aucun écart dans les paramètres et informations comparés.'));
      const equal=document.createElement('details');equal.append(text('summary','Informations identiques'),table(headers,same.map(values)));detail.append(equal);
      if(r.statistical_check){
        const audit=r.statistical_check;
        detail.append(text('h3',audit.status==='PASSED'?'Variante statistique de '+referenceCaption(r):'Contrôle de variante statistique'),
          text('p',audit.message,audit.status==='PASSED'?'muted':'warn'),
          text('p',`${audit.checked} polynômes non concernés contrôlés. Tolérance numérique : relative ${audit.rtol}, absolue ${audit.atol}.`),
          table(['Paramètre modifié','Référence','Run en attente'],audit.parameters.map(p=>[deltaLabels[p.key]||p.key,deltaValue(p.before,p.key),deltaValue(p.after,p.key)])));
        if(audit.affected.length)detail.append(text('h4','Polynômes d’intervalle concernés'),
          table(['Feuille','Type','Statistique','Évolution'],audit.affected.map(p=>[p.sheet,p.type,p.stat,p.change])));
        if(audit.differences.length)detail.append(text('h4','Écarts non expliqués par les paramètres d’intervalle'),
          table(['Feuille','Type','Statistique','Écart','Champs'],audit.differences.map(p=>[p.sheet,p.type,p.stat,p.reason,p.columns.join(', ')])));
      }
      if(r.kind==='STATISTICAL_VARIANT')detail.append(text('p','Cette déclinaison peut rejoindre l’analyse commune : les polynômes identiques sont mutualisés, les paramètres statistiques et la qualification restent propres à chaque run. Les essais ne sont pas comptés plusieurs fois.','muted'));
      detail.append(text('h3','Décision de réconciliation'),text('p','Laisser en attente conserve le run à résoudre et ajoute votre commentaire au journal. Cela ne valide, ne rejette ni n’intègre le run.'));
      const reason=document.createElement('textarea');reason.rows=2;const why=text('label','Motif de l’arbitrage / suites attendues');why.append(reason);detail.append(why);
      const actionsBox=text('div','','toolbar');detail.append(actionsBox);
      async function send(choice,extra={}){
        if(!reason.value.trim())throw Error('Renseigner le motif de l’arbitrage.');
        state=await api('arbitrate-candidate',{candidate:c.key,campaign:r.campaign,choice,reason:reason.value.trim(),...extra});render();status(choice==='defer'?'Commentaire enregistré au journal. Le run reste en attente ; aucune référence modifiée.':'Arbitrage enregistré. Consulter le journal pour la trace complète.');
      }
      actionsBox.append(button('Laisser en attente et enregistrer le commentaire',()=>task('Report…',()=>send('defer'))));
      if(!c.business.eligible){detail.append(text('p','Le candidat doit être accepté dans Ajouter avant capitalisation.','warn'),button('Revenir à sa qualification',()=>{selected=c.key;flowGo('ajouter');review()}));return}
      if((r.protected&&r.kind!=='STATISTICAL_VARIANT')||['RESULT_CONFLICT','PARTIAL_OVERLAP','UNDETERMINED'].includes(r.kind)){
        detail.append(text('p',r.protected?'Cette campagne appartient à un regroupement (parent ou résultat agrégé). Remplacer ce seul élément romprait la cohérence de la provenance : l’arbitrage individuel est bloqué. La révision doit porter sur le regroupement et ses sources.':'Capitalisation bloquée : résoudre cette anomalie ou ce chevauchement, puis réexaminer les données.','warn'));return;
      }
      if(r.kind==='COMPLEMENTARY'){
        detail.append(text('p','Les fichiers ne sont pas identiques. Vérifier leur indépendance réelle : des acquisitions réencodées peuvent avoir des empreintes différentes.','warn'));
        const confirm=document.createElement('input');confirm.type='checkbox';confirm.style.width='auto';const confirmLabel=text('label',' Je confirme des acquisitions expérimentales indépendantes.');confirmLabel.prepend(confirm);detail.append(confirmLabel);
        const name=document.createElement('input');name.value=[c.identity.report_number,c.identity.configuration_id].filter(Boolean).join(' — ');const nameLabel=text('label','Nom de la campagne distincte');nameLabel.append(name);detail.append(nameLabel);
        actionsBox.append(button('Capitaliser comme campagne complémentaire',()=>task('Capitalisation…',()=>send('distinct',{independent:confirm.checked,label:name.value}))));
        detail.append(text('p','Après cette entrée tracée, sélectionner les deux campagnes dans « Préparer un regroupement » ci-dessous pour les retraiter ensemble.'));
      }else{
        const confirm=document.createElement('input');confirm.type='checkbox';confirm.style.width='auto';const confirmLabel=text('label',' Je confirme la même campagne ; les écarts rapport/date/lots affichés seront rectifiés et historisés.');confirmLabel.prepend(confirm);detail.append(confirmLabel);
        if(r.kind==='STATISTICAL_VARIANT')actionsBox.append(button('Capitaliser cette déclinaison statistique',()=>task('Capitalisation des polynômes…',()=>send('share',{same_campaign:confirm.checked}))));
        else actionsBox.append(button('Conserver la référence existante',()=>task('Arbitrage…',()=>send('keep',{same_campaign:confirm.checked}))),
                          button('Retenir le candidat comme référence',()=>task('Arbitrage…',()=>send('replace',{same_campaign:confirm.checked}))));
      }
    }
    refs.onchange=comparePair;comparePair();
  }
  pick.onchange=display;display();
}
function showAggregate(c,host){renderCapitalization(c,host)}
const reconcileRenderBefore=render;
render=function(){reconcileRenderBefore();renderReconciliation()};
actions.DEFER_RECONCILIATION='Réconciliation reportée';
actions.SHARE_STATISTICAL_VARIANT='Déclinaison statistique capitalisée';
actions.MIGRATE_SHARED_POLYNOMIALS='Stockage partagé des polynômes';
// Boot may already have restored the base when this file finishes loading.
if(state){review();renderReconciliation()}

// 64F3A — qualification, arbitrage et exploitation : trois états distincts.
function runCaption(c) {
  const i=c.identity||{};
  return `${i.report_number||'Rapport non renseigné'} · ${i.configuration_id||'Configuration non renseignée'} · ${date(c.date)||'Date inconnue'} · ${c.count} essais · run ${(c.run||c.key||'').slice(0,8)}`;
}
function referenceInfo(r) {
  const cp=state.campaigns.find(x=>x.id===r.campaign);
  const v=cp?.variants.find(x=>x.id===r.variant);
  return {cp,v};
}
function referenceState(r) {
  const {cp}=referenceInfo(r);
  if(cp?.replaced_by)return `Parent archivé — remplacé par la campagne ${cp.replaced_by} (hors exploitation)`;
  if(cp?.parents?.length)return `Regroupement des campagnes ${cp.parents.join(' + ')} — ${cp.eligible?'exploitable':'non éligible à l’exploitation'}`;
  if(r.active==null)return 'Archivée — aucune référence active';
  return cp?.eligible?'Référence active et exploitable':'Référence active, non éligible à l’exploitation';
}
function referenceCaption(r) {
  const {v}=referenceInfo(r);
  return `${r.label} · V${r.variant} · ${v?date(v.date):'date inconnue'} · run ${(r.run||v?.run||'').slice(0,8)}`;
}
function runAdmission(c) {
  if(c.status==='Conflit d’identité du run')return c.status;
  for(const cp of state.campaigns){
    const v=cp.variants.find(x=>x.run===(c.run||c.key));
    if(!v)continue;
    if(cp.replaced_by)return `En base, parent archivé — campagne ${cp.id} / V${v.id} ; regroupé dans ${cp.replaced_by}`;
    if(v.statistical_exploitable&&v.id!==cp.active)return `En base, déclinaison statistique exploitable — campagne ${cp.id} / V${v.id}`;
    if(v.id!==cp.active)return `En base, variante archivée — campagne ${cp.id} / V${v.id}`;
    return `En base, référence retenue — campagne ${cp.id} / V${v.id} (${cp.eligible?'exploitable':'non éligible à l’exploitation'})`;
  }
  if(c.status!=='À examiner')return `${c.status} — décision déjà mémorisée ; voir le journal`;
  if(c.business?.eligible)return c.reanalysis||c.reconciliation?.length?'Accepté — intégration en attente de réconciliation':'Accepté — intégration à finaliser';
  return 'Pas de nouvelle intégration en base';
}
function runNeedsAction(c) {
  return (c.status==='À examiner'&&!['REWORK','REJECTED','WITHDRAWN'].includes(c.business?.status))||c.status==='Conflit d’identité du run';
}
function renderRunQueue() {
  if(!state)return;
  $('candidates').querySelector('h2').textContent='Runs à examiner';
  const todo=state.candidates.filter(runNeedsAction),done=state.candidates.filter(c=>!runNeedsAction(c));
  $('counts').textContent=`${todo.length} run(s) avec une action en attente · ${done.length} run(s) déjà arbitrés ou avec une décision de retraitement / rejet · ${state.candidates.length} exports lisibles.`;
  function rows(items,history){return items.map(c=>[
    runCaption(c),businessLabels[c.business?.status]||'À examiner',runAdmission(c),
    button(history?'Consulter':(c.business?.eligible&&(c.reanalysis||c.reconciliation?.length)?'Réconcilier':(c.business?.eligible?'Intégrer en base':'Examiner')),()=>{
      if(!history&&c.business?.eligible&&(c.reanalysis||c.reconciliation?.length)){reconcileGo(c);return}
      selected=c.key;review();$('review').scrollIntoView({behavior:'smooth'});
    })]);}
  const box=$('candidate-list');box.replaceChildren();
  if(todo.length)box.append(table(['Run ARCTA','Avis métier','Situation en base','Action'],rows(todo,false)));
  else box.append(text('p','Aucun run en attente d’examen dans cet inventaire.'));
  const history=document.createElement('details');history.append(text('summary',`Runs déjà traités ou orientés vers une autre suite (${done.length})`));
  history.append(table(['Run ARCTA','Avis métier','Situation en base','Consultation'],rows(done,true)));box.append(history);
  $('business-gate')?.append(text('p','Les nombres ci-dessus comptent les avis métier sur les exports inventoriés, pas les références exploitables en base. Acceptation, intégration et sélection active sont des états différents.','muted'));
}
const readableReviewBefore=review;
review=function(){
  const c=candidate();
  if(!c||runNeedsAction(c)){readableReviewBefore();return}
  $('review').hidden=false;$('decision-form').hidden=true;
  $('review').querySelector('h2').textContent='Consulter un run déjà traité';
  const box=$('candidate-info');box.replaceChildren(summary(c),text('p',runAdmission(c)),text('p','Avis métier : '+(businessLabels[c.business?.status]||'Non renseigné')));
  if(c.business?.document)box.append(text('p',`${c.business.document} · révision ${c.business.document_revision} · ${c.business.reviewer}`));
  if(c.business?.reason)box.append(text('p','Motif : '+c.business.reason));
  box.append(text('p','Consultation sans nouvelle décision. Pour revoir un choix, utiliser Retraiter / réviser ou consulter le Journal.','muted'));
};
const readableRenderBefore=render;
render=function(){readableRenderBefore();renderRunQueue()};
flowPages.reconcilier[1]='Comparer un run en attente aux références de même configuration. Seules les références actives et qualifiées imposent un rapprochement.';
$('reconcile-help').replaceChildren(text('h2','Lire les rapprochements'),text('p','Le run en attente est comparé séparément à chaque référence de la base. Les lignes ne comparent pas les références entre elles. Seules les références actives et qualifiées sont présentées ici. L’historique reste consultable dans Ajouter, sans imposer de réconciliation. Tout retour en exploitation est contrôlé contre les acquisitions déjà exploitées.'));
if(state){renderRunQueue();review();renderReconciliation();flowApply()}

// 64F4 — historique informatif, rattachement sans nouvelle campagne artificielle.
function showHistoricalMatches(c,host){
  const rows=c.historical_matches||[];if(!rows.length)return;
  const d=document.createElement('details');d.append(text('summary',`${rows.length} référence(s) historique(s) ou non exploitable(s) — information, pas de réconciliation imposée`));
  d.append(table(['Référence','Statut','Comparaison informative'],rows.map(r=>[referenceCaption(r),referenceState(r),reconcileKinds[r.kind]])));host.append(d);
  const targets=c.historical_targets||[];
  if(targets.length===1)host.append(text('p',`Intégration dans la campagne existante « ${targets[0].label} » (n° ${targets[0].campaign}). Son identité est conservée ; le nouveau run remplacera sa référence non exploitable. La provenance antérieure reste archivée.`));
  if(targets.length>1){
    const select=document.createElement('select');select.id='historical-campaign';
    const empty=text('option','Choisir la campagne historique correspondante…');empty.value='';select.append(empty);
    for(const t of targets){const o=text('option',`${t.campaign} — ${t.label}`);o.value=t.campaign;select.append(o)}
    const label=text('label','Plusieurs rattachements possibles — choisir avant intégration');label.append(select);host.append(label);
  }
}
function historicalChoice(c){
  const targets=c.historical_targets||[];
  if(targets.length===1)return targets[0].campaign;
  if(targets.length>1){const value=$('historical-campaign')?.value;if(!value)throw Error('Choisir la campagne historique de rattachement.');return Number(value)}
  return null;
}
