// 64F5 : le retraitement ne change ni qualification ni référence active.
function reworkQualification(v){
  const b=v.business||{status:'PENDING'};
  return (businessLabels[b.status]||b.status)+(b.document?` · ${b.document} / ${b.document_revision}`:'');
}
variantActions=function(v,cp){
  const node=text('div','','toolbar');
  node.append(text('small',reworkQualification(v)),button('Consulter',()=>viewCatalogue(v.id)),
    button('Préparer un retraitement ARCTA',()=>showRework(v,cp)));
  return node;
};
function reworkOpen(p){return button('Ouvrir dans ARCTA — '+p.title,()=>task('Ouverture de la session ARCTA…',async()=>{
  const result=await api('open-reanalysis',{request_id:p.request_id});
  try{localStorage.setItem('arcta_web_session_id',result.session_id)}catch(e){}
  window.location.assign(result.url);
}))}
function reworkPacketsBox(){
  let box=$('rework-packets');if(!box){box=text('section','');box.id='rework-packets';$('history').before(box)}return box;
}
async function reworkHistory(){
  const d=await api('reworks'),box=reworkPacketsBox();
  box.replaceChildren(text('h2','Retraitements préparés'));
  if(!d.packets.length)box.append(text('p','Aucun retraitement préparé.'));
  for(const p of d.packets){const card=text('div','','card');card.append(reworkOpen(p),text('p',`Campagne ${p.campaigns.join(', ')} · variante ${p.variants.join(', ')} · ${p.trial_count} essais · ${date(p.utc)}`),text('p',p.reason),text('p',p.directory,'path muted'));box.append(card)}
}
function showRework(v,cp){
  let box=$('rework-form');if(!box){box=text('section','');box.id='rework-form';$('active').after(box)}
  box.replaceChildren(text('h2',`Retraiter — ${cp.label} · V${v.id}`),summary(v),
    text('p','Qualification actuelle : '+reworkQualification(v)),
    text('p','Copie des acquisitions, reprise de la CONFIG et des paramètres statistiques en brouillon. Aucune modification de la base ni de ses références avant un nouvel arbitrage.'));
  const title=document.createElement('input');title.maxLength=120;title.value=('Retraitement '+cp.label+' V'+v.id).slice(0,120);
  const reason=document.createElement('textarea');reason.maxLength=2000;reason.rows=3;
  const scope=document.createElement('select');
  for(const [value,label] of [['all','Tous les essais archivés, y compris ceux précédemment écartés'],['retained','Uniquement les essais précédemment retenus']]){const o=text('option',label);o.value=value;scope.append(o)}
  for(const [label,input] of [['Nom du dossier de retraitement',title],['Périmètre à réexaminer dans ARCTA',scope],['Motif obligatoire — corrections attendues',reason]]){const field=text('label',label);field.append(input);box.append(field)}
  const preview=text('div',''),confirmation=document.createElement('input');confirmation.type='checkbox';confirmation.style.width='auto';
  const confirmLabel=text('label',' Je confirme le périmètre affiché et demande une nouvelle analyse dans ARCTA.');confirmLabel.prepend(confirmation);
  let checked=null,requestId=crypto.randomUUID();
  const invalidate=()=>{checked=null;confirmation.checked=false;preview.replaceChildren();requestId=crypto.randomUUID()};
  scope.onchange=invalidate;title.oninput=()=>{requestId=crypto.randomUUID()};reason.oninput=()=>{requestId=crypto.randomUUID()};
  box.append(button('Vérifier les sources à reprendre',()=>task('Vérification des acquisitions…',async()=>{
    checked=await api('rework-preview',{variant:v.id,scope:scope.value});confirmation.checked=false;
    preview.replaceChildren(text('p',`${checked.retained_count} fichiers à reprendre sur ${checked.total_count}. ${checked.prior_retained_count} étaient retenus dans le run source.`),
      table(['Essai','Fichier','Sélection précédente','Reprise','Source'],checked.sources.map(s=>[s.trial,s.name,s.previously_accepted?'Retenu':'Écarté',s.accepted?'Oui':'Non',s.status])));
    for(const message of checked.blockers)preview.append(text('p',message,'warn'));
    status(checked.blockers.length?'Préparation bloquée : corriger les sources signalées.':'Sources vérifiées. Confirmer le périmètre puis préparer le dossier.',!!checked.blockers.length);
  })),preview,confirmLabel,button('Préparer le dossier ARCTA',()=>task('Copie vérifiée et journalisation du retraitement…',async()=>{
    if(!checked||checked.blockers.length||checked.scope!==scope.value||!confirmation.checked)throw Error('Vérifier puis confirmer le périmètre de retraitement.');
    if(!title.value.trim()||!reason.value.trim())throw Error('Renseigner un nom et un motif de retraitement.');
    const packet=await api('prepare-rework',{variant:v.id,scope:scope.value,title:title.value.trim(),reason:reason.value.trim(),revision:checked.revision,request_id:requestId});
    state=await api('status');render();
    const result=reworkPacketsBox();result.replaceChildren(text('h2','Retraitement prêt'),text('p',packet.directory,'path'),text('p',`${packet.trial_count} essais copiés. Le motif et la variante source sont conservés au journal.`),reworkOpen(packet));
    result.scrollIntoView({behavior:'smooth'});status('Dossier préparé. Cliquer sur « Ouvrir dans ARCTA » pour poursuivre. La qualification source reste inchangée.');
  })));
  box.scrollIntoView({behavior:'smooth'});
}
function renderSasExisting(){
  let box=$('sas-existing');if(!box){box=text('section','');box.id='sas-existing';$('history').before(box)}
  box.replaceChildren(text('h2','Réviser volontairement une qualification'),text('p','Cette page est distincte du retraitement. Une nouvelle décision exige un motif et une référence documentaire. Elle peut modifier l’éligibilité à l’exploitation.'));
  if(!state?.business_gate){box.append(text('p','Activer le sas métier pour qualifier les résultats.'));return}
  const rows=[];
  for(const cp of state.campaigns)for(const v of cp.variants){const actions=text('div','','toolbar');actions.append(button('Consulter',()=>viewCatalogue(v.id)),button('Ouvrir la revue métier',()=>{
    let form=$('business-variant');if(!form){form=text('section','');form.id='business-variant';box.after(form)}
    form.replaceChildren(text('h2',`${cp.label} — V${v.id}`),summary(v));businessForm(form,v,{variant:v.id});form.scrollIntoView({behavior:'smooth'});
  }));rows.push([cp.label,`V${v.id}`,v.id===cp.active?'Référence retenue':'Variante archivée',reworkQualification(v),actions])}
  box.append(table(['Campagne','Variante','Position dans la base','Qualification','Actions'],rows));
}
const reworkRenderBefore=render;
render=function(){reworkRenderBefore();$('rework-form')?.remove();renderSasExisting();const box=reworkPacketsBox();box.replaceChildren(text('h2','Reprendre un retraitement préparé'),button('Afficher les dossiers préparés',()=>task('Lecture du journal des retraitements…',reworkHistory)))};
const reworkFlowBefore=flowApply;
flowApply=function(){reworkFlowBefore();if(flowPage!=='sas')$('business-variant')?.remove();if(flowPage!=='retraiter')$('rework-form')?.remove()};
actions.PREPARE_REWORK='Préparation d’un retraitement ARCTA';actions.OPEN_REWORK_ARCTA='Ouverture du retraitement dans ARCTA';
