// 64F7 — noms d'affichage uniquement ; identifiants et décisions inchangés.
businessLabels.APPROVED='Accepté métier';
businessLabels.REJECTED='Rejeté';
businessLabels.REWORK='À retraiter';

function runCampaign(id){
 return state?.campaigns.find(c=>c.variants.some(v=>v.id===id))
}
function runName(id,c=runCampaign(id)){
 return (c?.parents?.length>1?'Run_Extd_V':'Run_V')+id
}
function runPosition(c,v){
 if(c.replaced_by)return ['Parent intégré à un regroupement','history'];
 if(['REJECTED','WITHDRAWN'].includes(v.business?.status))
  return ['Exploitation interdite','blocked'];
 if(v.id===c.active&&c.eligible)return ['Référence exploitée','reference'];
 if(v.statistical_exploitable)return ['Déclinaison statistique exploitable','reference'];
 if(v.id===c.active)
  return ['Référence bloquée — décision métier nécessaire','pending'];
 return ['Conservé en base — non retenu','history'];
}
function runBadge(c,v){
 const [label,kind]=runPosition(c,v);
 return text('span',label,'run-state run-'+kind)
}
function runQualification(v){
 const b=v.business||{status:'PENDING'},box=text('div','');
 box.append(text('strong',businessLabels[b.status]||b.status));
 if(b.document)
  box.append(text('small',`${b.document} · révision ${b.document_revision||'—'}`,'muted'));
 return box;
}

const runStyle=text('style',`
.run-state{display:inline-block;padding:5px 8px;border-radius:5px;line-height:1.4}
.run-reference{background:#dff1e5;color:#145c35}
.run-candidate{background:#e3effc;color:#194d80}
.run-history{background:#edf0f2;color:#455564}
.run-pending{background:#fff0d1;color:#785008}
.run-blocked{background:#fce3e3;color:#8a2424}
.run-action-row td{background:#f7f9fb;padding:8px 12px!important;border-bottom:2px solid #d6e0e6}
.run-action-row .toolbar{justify-content:flex-start;gap:10px}
.run-action-row button{width:260px;min-width:0;max-width:100%;flex:0 1 260px;white-space:normal}
#campaign-list table,#consult-base table{table-layout:auto;min-width:850px}
#campaign-list th,#campaign-list td,#consult-base th,#consult-base td{white-space:normal!important;overflow-wrap:anywhere;min-width:0;width:auto}
#consult-base th:nth-child(n){width:auto}
#campaign-list th:nth-child(1),#consult-base th:nth-child(1){min-width:125px}
#campaign-list th:nth-child(4),#campaign-list th:nth-child(5){min-width:170px}
#campaign-list td:nth-child(6){min-width:210px;max-width:360px}
.run-scroll{overflow-x:auto}
.run-legend{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
`);
document.head.append(runStyle);

// Les boutons quittent les cellules d'information et conservent leurs handlers.
const runOriginalTable=table;
table=function(headers,rows){
 const captured=rows.map(row=>{
  const buttons=[];
  const cells=row.map(value=>{
   if(!(value instanceof Node))return value;
   if(value.nodeName==='BUTTON'){
    buttons.push(value);
    return ''
   }
   for(const b of [...value.querySelectorAll('button')]){
    buttons.push(b);
    b.remove()
   }
   return value;
  });
  return {cells,buttons};
 });
 const empty=value=>value instanceof Node
  ?!value.textContent.trim()&&!value.querySelector('input,select,textarea,a')
  :value==='';
 const drop=new Set(headers.map((h,i)=>
  ['Actions','Action','Consultation','Détail','Lecture',''].includes(h)
  &&captured.length&&captured.every(r=>empty(r.cells[i]))?i:-1
 ));
 const kept=headers.map((_,i)=>i).filter(i=>!drop.has(i));
 const t=runOriginalTable(
  kept.map(i=>headers[i]),
  captured.map(r=>kept.map(i=>r.cells[i]))
 );
 const trs=[...t.children].filter(n=>n.nodeName==='TR').slice(1);
 captured.forEach((r,i)=>{
  if(!r.buttons.length)return;
  const tr=text('tr','','run-action-row');
  const td=text('td',''),bar=text('div','','toolbar');
  td.colSpan=kept.length;
  bar.append(...r.buttons);
  td.append(bar);
  tr.append(td);
  trs[i].after(tr)
 });
 return t;
};

function runLegend(){
 const n=text('div','','run-legend');
 for(const [kind,label] of [
  ['reference','Référence exploitée'],
  ['candidate','À examiner / intégrer'],
  ['history','Conservé hors exploitation'],
  ['pending','Décision nécessaire'],
  ['blocked','Exploitation interdite']
 ])n.append(text('span',label,'run-state run-'+kind));
 return n
}

function runActions(v,c){
 const b=text('div','');
 b.append(
  button('Consulter '+runName(v.id,c),()=>viewCatalogue(v.id)),
  button('Préparer un retraitement ARCTA',()=>showRework(v,c))
 );
 return b
}

function runDetailsTable(c,readonly=false){
 const rows=c.variants.map(v=>{
  const name=text('div','');
  name.append(text('strong',runName(v.id,c)));
  const origin=document.createElement('details');
  origin.append(text('summary','Identifiant ARCTA'),text('small',v.run));
  name.append(origin);
  return [
   name,date(v.date),v.count,runBadge(c,v),runQualification(v),
   v.id===c.active
    ?'Résultat désigné comme référence'
    :deltaLine(v.comparison,c.active),
   readonly
    ?button("Consulter "+runName(v.id,c),()=>viewCatalogue(v.id))
    :runActions(v,c)
  ]
 });
 const box=text('div','','run-scroll');
 box.append(table([
  'Run conservé','Date du run','Essais retenus',
  'Utilisation actuelle','Qualification métier',
  'Écarts à la référence','Actions'
 ],rows));
 return box;
}

function runFamily(c){
 const box=text('div','');
 const name=id=>{
  const cp=state.campaigns.find(x=>x.id===id);
  return cp?`${cp.label} (campagne ${id})`:`Campagne ${id}`
 };
 if(c.parents?.length)
  box.append(text('p','Campagnes regroupées : '+c.parents.map(name).join(' + ')));
 if(c.replaced_by){
  const target=state.campaigns.find(x=>x.id===c.replaced_by);
  box.append(text('p',
   'Résultats individuels hors exploitation : intégrés dans '+name(c.replaced_by),
   'muted'));
  if(target&&!target.eligible)
   box.append(text('p',
    'Le regroupement n’est pas exploitable. Ses campagnes parentes ne sont pas réactivées automatiquement ; un arbitrage est nécessaire.',
    'warn'))
 }
 return box;
}

function runExisting(){
 if(!state)return;
 const host=$('campaign-list');
 host.replaceChildren(runLegend());
 $('active').querySelector('h2').textContent=
  'Runs conservés — consultation et retraitement';
 for(const c of state.campaigns){
  const card=text('div','','card');
  card.append(
   text('h3',`${c.label} — campagne ${c.id}`),
   runFamily(c),runDetailsTable(c)
  );
  host.append(card)
 }
 if(!state.campaigns.length)
  host.append(text('p','Aucun run enregistré dans cette base.'));
}

consultRender=function(){
 consultBox.replaceChildren(text('h2','Campagnes et runs conservés'));
 if(!state){
  consultBox.append(text('p','Ouvrir une base pour la consulter.'));
  return
 }
 consultBox.append(
  text('p',`Révision ${state.revision} · ${state.campaigns.length} campagne(s). Run_Extd : résultat issu de plusieurs campagnes regroupées.`,'muted'),
  runLegend()
 );
 const controls=text('div','','consult-tools');
 const search=text('input',''),filter=text('select','');
 search.type='search';
 search.value=consultQuery;
 for(const [value,label] of [
  ['all','Toutes les campagnes'],
  ['eligible','Références exploitables'],
  ['other','Autres statuts']
 ]){
  const o=text('option',label);
  o.value=value;
  filter.append(o)
 }
 filter.value=consultFilter;
 const a=text('label','Rechercher une campagne / un rapport');
 const b=text('label','Périmètre');
 a.append(search);b.append(filter);
 controls.append(a,b);consultBox.append(controls);
 const list=text('div','','run-scroll'),detail=text('div','');
 detail.id='consult-detail';
 consultBox.append(list,detail);

 function show(){
  detail.replaceChildren();
  const campaigns=state.campaigns.filter(consultMatches);
  list.replaceChildren(text('p',`${campaigns.length} campagne(s)`));
  list.append(table([
   'Campagne / configuration','Rapport / date d’essai',
   'Référence désignée','Essais retenus','Utilisation actuelle','Détail'
  ],campaigns.map(c=>{
   const v=consultActive(c),m=v?.metadata||c.metadata||{};
   const name=text('div','');
   name.append(
    text('strong',c.label),
    text('small',`${m.entity||'—'} / ${m.program_id||'—'} / ${m.configuration_id||'—'}`)
   );
   return [
    name,`${m.report_number||'—'} · ${m.test_date||'—'}`,
    v?runName(v.id,c):c.replaced_by
     ?'Intégrée au regroupement':'Aucune référence désignée',
    v?v.count:'—',
    v?runBadge(c,v):text('span',
     c.replaced_by?'Parent regroupé':'Sans référence',
     'run-state run-history'),
    button('Voir les runs',()=>{
     detail.replaceChildren(
      text('h3',c.label),runFamily(c),runDetailsTable(c,true)
     );
     detail.scrollIntoView({block:'nearest'})
    })
   ];
  })));
 }
 search.oninput=()=>{consultQuery=search.value;show()};
 filter.onchange=()=>{consultFilter=filter.value;show()};
 show();
};

const runCatBefore=catRender;
catRender=function(d){
 runCatBefore(d);
 const c=runCampaign(d.variant);
 const v=c?.variants.find(x=>x.id===d.variant),box=$('catalogue');
 box.querySelector('h2').textContent=
  `${d.label} — ${runName(d.variant,c)}`;
 const p=box.querySelector('p');
 if(c&&v){
  p.replaceChildren(
   runBadge(c,v),
   text('span',` · ${d.accepted_count} essais retenus · révision ${d.revision}`)
  );
  p.after(runQualification(v),runFamily(c))
 }
};

viewCatalogue=async function(id){
 await task('Lecture du run conservé…',async()=>{
  const d=await api('catalogue',{variant:id});
  catRender(d);
  status(`${runName(id)} consulté — révision ${d.revision}. Aucune décision modifiée.`);
 })
};

const runShowReworkBefore=showRework;
showRework=function(v,c){
 runShowReworkBefore(v,c);
 $('rework-form').querySelector('h2').textContent=
  `Retraiter — ${c.label} · ${runName(v.id,c)}`
};

const runDeltaBefore=deltaLine;
deltaLine=function(d,id){
 const p=runDeltaBefore(d,id);
 p.textContent=p.textContent.replace(
  /\bV(\d+)\b/g,(_,n)=>runName(Number(n))
 );
 p.title=p.textContent;
 return p
};

referenceCaption=function(r){
 const {cp,v}=referenceInfo(r);
 return `${r.label} · ${runName(r.variant,cp)} · ${v?date(v.date):'date inconnue'}`
};

const runFlowOverviewBefore=flowOverview;
flowOverview=function(){
 runFlowOverviewBefore();
 const box=$('base-preview');
 if(!state)return;
 const t=box.querySelector('table');
 if(t)t.replaceWith(table([
  'Campagne','Rapport','Référence désignée','Utilisation actuelle'
 ],state.campaigns.slice(-5).reverse().map(c=>{
  const v=consultActive(c);
  return [
   c.label,c.metadata.report_number||'—',
   v?runName(v.id,c):'Aucune',
   v?runBadge(c,v):c.replaced_by?'Parent regroupé':'Sans référence'
  ]
 })))
};

const runRenderBefore=render;
render=function(){
 runRenderBefore();
 runExisting();
 $('work-choices').querySelector('[data-flow-page="consulter"]').textContent=
  'Consulter les campagnes et leurs runs'
};

const runAdmissionBefore=runAdmission;
runAdmission=function(c){
 return runAdmissionBefore(c)
  .replace(/\bV(\d+)\b/g,(_,n)=>runName(Number(n)))
  .replace('variante archivée','run conservé non retenu')
};

const runQueueBefore=renderRunQueue;
renderRunQueue=function(){
 runQueueBefore();
 if(!state)return;
 const items=[
  ...state.candidates.filter(runNeedsAction),
  ...state.candidates.filter(c=>!runNeedsAction(c))
 ];
 const rows=[...$('candidate-list').querySelectorAll('tr')].filter(r=>
  !r.classList.contains('run-action-row')&&r.children[0]?.nodeName==='TD'
 );
 rows.forEach((r,i)=>{
  const c=items[i];
  if(!c)return;
  const cp=state.campaigns.find(x=>
   x.variants.some(v=>v.run===(c.run||c.key))
  );
  const v=cp?.variants.find(v=>v.run===(c.run||c.key));
  const kind=v?runPosition(cp,v)[1]
   :['REJECTED','WITHDRAWN'].includes(c.business?.status)?'blocked'
   :c.business?.status==='REWORK'?'pending':'candidate';
  r.children[2]?.classList.add('run-'+kind)
 })
};

const runSasBefore=renderSasExisting;
renderSasExisting=function(){
 runSasBefore();
 const box=$('sas-existing');
 if(!box)return;
 for(const r of box.querySelectorAll('tr')){
  if(r.classList.contains('run-action-row'))continue;
  const cell=r.children[1];
  if(!cell)continue;
  const match=/^V(\d+)$/.exec(cell.textContent);
  if(match)cell.textContent=runName(Number(match[1]));
  else if(cell.textContent==='Variante')cell.textContent='Run conservé'
 }
};
if(state)render();
