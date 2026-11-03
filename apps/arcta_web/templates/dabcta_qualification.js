// Identités déclarées : aucune authentification de personnes à ce jalon.
const businessLabels={DISABLED:'Sas non activé',PENDING:'À examiner',APPROVED:'Validé pour capitalisation',REWORK:'À retraiter',REJECTED:'Rejeté',WITHDRAWN:'Validation retirée'};
function businessForm(host,item,extra) {
  const prior=item.business||{status:'PENDING'};
  const panel=text('div','','card');panel.append(text('h3','Qualification métier — '+businessLabels[prior.status]));
  if(prior.document)panel.append(text('p',`${prior.document} · révision ${prior.document_revision} · validateur déclaré : ${prior.reviewer}`));
  panel.append(text('p','Examiner CONFIG, paramètres, DIAG et livrables avant décision. Les identités sont déclarées ; leur authentification reste à intégrer.','muted'));
  const inputs={};
  for(const [key,label] of [['producer','Producteur ARCTA (identité déclarée)'],['reviewer','Validateur métier (identité déclarée)'],['document','Référence documentaire'],['document_revision','Révision du document'],['reason','Motif / instructions de retraitement']]) {
    const field=text('label',label),input=document.createElement(key==='reason'?'textarea':'input');input.value=prior[key]||'';input.maxLength=2000;field.append(input);panel.append(field);inputs[key]=input;
  }
  const decision=document.createElement('select');
  for(const code of ['APPROVED','REWORK','REJECTED',...(prior.status==='APPROVED'?['WITHDRAWN']:[])]){const o=text('option',businessLabels[code]);o.value=code;decision.append(o)}
  const empty=text('option','Choisir une décision');empty.value='';empty.selected=true;decision.prepend(empty);
  const label=text('label','Décision métier');label.append(decision);panel.append(label);
  const attest=document.createElement('input');attest.type='checkbox';attest.style.width='auto';
  const attestation=text('label',' Je confirme la revue de ce run et la traçabilité de la décision dans le document référencé.');attestation.prepend(attest);panel.append(attestation);
  panel.append(button('Enregistrer la décision métier',()=>task('Contrôle des livrables et enregistrement…',async()=>{
    const fields=Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value.trim()]));
    if(!decision.value||!attest.checked||Object.values(fields).some(v=>!v))throw Error('Compléter la décision, les identités, la référence documentaire, le motif et l’attestation.');
    state=await api('business-review',{...extra,...fields,status:decision.value,attest:true});
    render();status(state.workflow_notice||'Décision métier enregistrée. La capitalisation reste une action distincte.');
  })));
  host.append(panel);
}
const reviewBefore64F1=review;
review=function(){reviewBefore64F1();const c=candidate();if(!c||!state.business_gate)return;
  if(!c.business?.eligible)$('decision-form').hidden=true;
  businessForm($('candidate-info'),c,{candidate:c.key});
};
const actionsBefore64F1=variantActions;
variantActions=function(v,cp){const node=actionsBefore64F1(v,cp);if(state.business_gate)node.append(button('Qualification métier',()=>{
  let box=$('business-variant');if(!box){box=text('section','');box.id='business-variant';$('history').before(box)}
  box.replaceChildren(text('h2',`${cp.label} — variante ${v.id}`));businessForm(box,v,{variant:v.id});box.scrollIntoView({behavior:'smooth'});
}));return node;};
const renderBefore64F1=render;
render=function(){renderBefore64F1();$('business-variant')?.remove();let box=$('business-gate');
  if(!box){box=text('section','');box.id='business-gate';$('candidates').before(box)}box.replaceChildren(text('h2','Sas de qualification métier'));
  if(!state.business_gate){
    box.append(text('p','Sas non activé pour cette base de développement. Après activation, seuls les résultats qualifiés alimenteront la vue SQL d’exploitation. Les références existantes resteront mémorisées, mais devront être qualifiées.','warn'));
    const reason=document.createElement('input');reason.placeholder='Motif de mise en service du sas';box.append(reason);
    box.append(button('Activer le sas pour cette base',()=>task('Activation du sas métier…',async()=>{
      if(!reason.value.trim())throw Error('Renseigner un motif.');
      if(!window.confirm('Activer le contrôle obligatoire ? Les résultats non qualifiés seront exclus de la vue SQL d’exploitation.'))return;
      state=await api('business-enable',{confirm:true,reason:reason.value.trim()});render();status('Sas activé. Les résultats existants restent à qualifier.');
    })));return;
  }
  const counts={};for(const c of state.candidates){const k=c.business.status;counts[k]=(counts[k]||0)+1}
  box.append(text('p','Sas actif — identités déclarées. Aucune décision ne supprime les sources ni les résultats.'));
  box.append(text('p',Object.entries(counts).map(([k,n])=>`${businessLabels[k]} : ${n}`).join(' · ')||'Aucun run inventorié dans cette session de base.'));
  box.append(button('Inventorier de nouveaux runs — Ajouter des éléments',()=>flowGo('ajouter')));
  const audit=document.createElement('details');audit.append(text('summary','Historique des qualifications'),table(['Date','Run','Décision','Validateur déclaré','Document / révision','Motif'],state.journal.filter(j=>j.action==='BUSINESS_REVIEW').map(j=>[date(j.utc),j.detail.run,businessLabels[j.detail.status],j.detail.reviewer,j.detail.document+' / '+j.detail.document_revision,j.detail.reason])));box.append(audit);
};
actions.ENABLE_BUSINESS_GATE='Activation du sas métier';actions.BUSINESS_REVIEW='Décision métier documentée';
