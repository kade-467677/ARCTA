// 64F2: routes dédiées, contexte de base conservé dans l'onglet.
const flowPages={
  base:['Base DABCTA','Ouvrir une base, consulter son aperçu, puis choisir un travail.'],
  ajouter:['Ajouter des éléments','Sources ARCTA → inventaire → qualification métier → capitalisation.'],
  reconcilier:['Réconcilier des campagnes','Comparer des campagnes indépendantes, préparer leur regroupement puis poursuivre dans ARCTA.'],
  retraiter:['Retraiter / réviser des résultats','Choisir un résultat, justifier son retraitement et reprendre le travail dans ARCTA.'],
  sas:['Sas métier — révision volontaire','Revoir une qualification existante avec une référence documentaire et un motif.'],
  journal:['Journal de la base','Retrouver les travaux et décisions, leur révision et leur motif.']
};
const flowKey='dabcta_context_64F2';
let flowPage='base';
function flowReadPath(){return Object.hasOwn(flowPages,location.pathname.split('/').pop())?location.pathname.split('/').pop():'base'}
function flowSave(){try{sessionStorage.setItem(flowKey,JSON.stringify({token,database:state?.database,root:state?.root}))}catch(e){}}
function flowLink(label,page){const a=text('a',label);a.href='/dabcta/'+page;a.dataset.flowPage=page;return a}
function flowGo(page,push=true){
  if(busy)return;
  if(page!=='base'&&!token){status('Ouvrir une base avant de choisir un travail.',true);page='base'}
  flowPage=page;
  if(push)history.pushState({},'', '/dabcta/'+page);
  flowApply();window.scrollTo(0,0);
}
function flowApply(){
  document.body.dataset.workspace=flowPage;
  document.title='DABCTA — '+flowPages[flowPage][0];
  document.querySelector('main h1').textContent=flowPages[flowPage][0];
  $('workspace-caption').textContent=flowPages[flowPage][1];
  document.querySelectorAll('aside [data-flow-page]').forEach(a=>{
    if(a.dataset.flowPage===flowPage)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
  });
  $('work-choices').hidden=!state;$('base-preview').hidden=!state;
  $('business-gate')?.querySelector('details')?.remove(); // Le journal a sa page dédiée.
  if(state){
    $('workspace-base').textContent=state.database;
    $('workspace-base').title=state.database;
  }
}
function flowOverview(){
  if(!state)return;
  const box=$('base-preview');box.replaceChildren(text('h2','Aperçu de la base'));
  const campaigns=state.campaigns,eligible=campaigns.filter(c=>c.eligible).length;
  box.append(text('p',`${campaigns.length} campagne(s) · ${eligible} référence(s) éligible(s) à l’exploitation · révision ${state.revision} · sas ${state.business_gate?'actif':'non activé'}`,'muted'));
  const rows=campaigns.slice(-5).reverse();
  if(rows.length){const t=table(['Campagne','Rapport','Référence','Qualification'],rows.map(c=>[
    c.label,c.metadata.report_number||'—',c.active===null?'Archivée':'V'+c.active,
    c.replaced_by?'Parent archivé':c.active===null?'Sans référence':state.business_gate?(c.eligible?'Validée':'À qualifier'):'Sas non activé'
  ]));t.querySelectorAll('td').forEach(td=>td.title=td.textContent);box.append(t)}
  else box.append(text('p','Base vide. Choisir « Ajouter des éléments » pour inventorier les premiers résultats ARCTA.'));
  if(campaigns.length>5)box.append(text('small',`Les 5 dernières campagnes créées sur ${campaigns.length}. Le catalogue complet est dans « Retraiter / réviser ».`));
}
function flowJournal(){
  if(!state)return;
  $('journal').replaceChildren(table(['Révision','Date','Auteur','Travail / décision','Trace'],state.journal.map(j=>{
    const d=j.detail,cell=text('div','');
    if(j.action==='BUSINESS_REVIEW')cell.append(text('p',`${businessLabels[d.status]||d.status} · run ${d.run} · ${d.document}, révision ${d.document_revision} · validateur déclaré : ${d.reviewer}`));
    else if(j.action==='INVENTORY_SOURCES')cell.append(text('p',`${d.runs} run(s) lisible(s) · ${d.errors.length} refus · ${d.root}`));
    else cell.append(text('p',`Campagne ${d.campaign??'—'} · variante ${d.selected??d.candidate??'—'}`));
    if(d.reason)cell.append(text('p',d.reason));
    const details=document.createElement('details');details.append(text('summary','Trace complète'),text('pre',JSON.stringify(d,null,2)));cell.append(details);
    return [j.revision,date(j.utc),j.actor,actions[j.action]||j.action,cell];
  })));
}
function flowBuild(){
  const aside=document.querySelector('aside');aside.replaceChildren(text('strong','DABCTA'),text('p','Un travail à la fois'));
  for(const [page,label] of [['base','1 — Base'],['ajouter','Ajouter des éléments'],['reconcilier','Réconcilier'],['retraiter','Retraiter / réviser'],['sas','Sas métier'],['journal','Journal']])aside.append(flowLink(label,page));
  const arcta=text('a','Retour à ARCTA');arcta.href='/dabcta/arcta';aside.append(arcta);
  const main=document.querySelector('main'),caption=document.querySelector('main > p');caption.id='workspace-caption';
  const basePath=text('small','','path muted');basePath.id='workspace-base';caption.after(basePath);
  const base=$('base');base.querySelector('h2').textContent='Ouvrir ou créer une base';
  const sources=text('section','');sources.id='sources';sources.append(text('h2','Sources à inventorier'));
  const sourceField=$('root').parentElement;sources.append(sourceField,$('scan'),$('errors'));base.after(sources);
  const preview=text('section','');preview.id='base-preview';preview.hidden=true;base.after(preview);
  const choices=text('section','');choices.id='work-choices';choices.hidden=true;choices.append(text('h2','Que veux-tu faire dans cette base ?'));
  const jobs=text('div','','toolbar');
  for(const [page,label] of [['ajouter','Ajouter des éléments — nouveaux runs ARCTA'],['reconcilier','Réconcilier — regrouper des campagnes'],['retraiter','Retraiter / réviser — résultats existants']]){const b=button(label,()=>flowGo(page)); /* 64F3A couleurs */ b.style.backgroundColor={ajouter:'#146B50',reconcilier:'#175A85',retraiter:'#79451D'}[page];b.style.color='#fff';b.style.borderColor=b.style.backgroundColor;jobs.append(b);}
  choices.append(jobs);preview.after(choices);
  const help=text('section','');help.id='reconcile-help';help.append(text('h2','Regrouper des acquisitions indépendantes'),
    text('p','La qualification métier autorise l’usage des résultats ; la réconciliation décide quelles campagnes analyser ensemble. Les anciennes variantes restent tracées.'),
    flowLink('Qualifier les références existantes avant regroupement','sas'));$('history').before(help);
  $('active').querySelector('h2').textContent='Résultats existants et variantes';
  $('active').querySelector('h2').after(text('p','Le retraitement copie les sources dans une nouvelle session ARCTA. La référence en base et sa qualification restent inchangées. Pour revoir volontairement une qualification, ouvrir le Sas métier.','muted'));
  // Refresh is common to all workspaces; opening the base does not select sources.
  $('status').after($('refresh'));
  document.addEventListener('click',e=>{const a=e.target.closest?.('a[data-flow-page]');if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;e.preventDefault();flowGo(a.dataset.flowPage)});
  window.addEventListener('popstate',()=>{flowPage=token?flowReadPath():'base';if(!token)history.replaceState({},'','/dabcta/base');flowApply()});
}
const flowRenderBefore=render;
render=function(){flowRenderBefore();flowSave();flowOverview();flowJournal();flowApply()};
const flowReviewBefore=review;
review=function(){flowReviewBefore();flowApply()};
actions.INVENTORY_SOURCES='Inventaire des sources';
flowBuild();flowPage=flowReadPath();document.body.dataset.workspace='base';
$('open').onclick=()=>task('Ouverture de la base…',async()=>{
  const d=await api('open',{database:$('database').value});token=d.token;state=d;selected=null;pending=null;
  localStorage.setItem('dabcta_paths',JSON.stringify({database:d.database,root:$('root').value}));
  flowPage='base';history.replaceState({},'','/dabcta/base');render();status('Base ouverte. Choisir un travail ci-dessous. Aucun dossier source inventorié.');
});
$('scan').onclick=()=>task('Inventaire des sources ARCTA…',async()=>{
  state=await api('inventory-sources',{root:$('root').value});selected=null;render();
  localStorage.setItem('dabcta_paths',JSON.stringify({database:state.database,root:state.root}));
  status(`Inventaire terminé : ${state.candidates.length} run(s), ${state.errors.length} refus. Aucune capitalisation automatique. Trace conservée au journal.`);
});
(async()=>{
  await loadDefaults();
  try{
    const stored=JSON.parse(sessionStorage.getItem(flowKey)||'null');
    if(stored?.token){token=stored.token;state=await api('status');$('database').value=state.database;if(state.root)$('root').value=state.root;render();status('Base reprise. Choisir ou poursuivre un travail.');return}
  }catch(e){token=null;state=null;try{sessionStorage.removeItem(flowKey)}catch(ignore){}status('La session de base a expiré. Ouvrir à nouveau la base ; ses décisions restent conservées.',true)}
  flowPage='base';history.replaceState({},'','/dabcta/base');flowApply();controls();
})();
