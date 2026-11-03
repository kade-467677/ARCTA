// 64F6 : consultation uniquement, sans arbitrage.
flowPages.consulter=['Consulter la base','Campagnes, références et variantes archivées. Consultation en lecture seule.'];
const consultStyle=document.createElement('style');
consultStyle.textContent=`
body[data-workspace="consulter"] #consult-base,body[data-workspace="consulter"] #catalogue{display:block}
#consult-base .scroll{overflow-x:auto}
#consult-base table{table-layout:fixed;min-width:850px;width:100%}
#consult-base th,#consult-base td{white-space:normal;overflow-wrap:anywhere;word-break:normal;padding:9px;line-height:1.4}
#consult-base th:nth-child(1){width:30%}#consult-base th:nth-child(2){width:19%}
#consult-base th:nth-child(3){width:12%}#consult-base th:nth-child(4){width:9%}
#consult-base th:nth-child(5){width:17%}#consult-base th:nth-child(6){width:13%}
#consult-base .consult-tools{display:flex;gap:12px;flex-wrap:wrap;align-items:end}
#consult-base .consult-tools label:first-child{flex:2;min-width:220px}
#consult-base .consult-tools label{flex:1;min-width:180px}
#consult-base button{padding:7px;max-width:100%;white-space:normal}
#consult-base .consult-variants{table-layout:auto;min-width:720px}
#consult-base .consult-variants th{width:auto}
body[data-workspace="consulter"] #catalogue table{table-layout:auto;min-width:600px}
body[data-workspace="consulter"] #catalogue th,body[data-workspace="consulter"] #catalogue td{white-space:normal;overflow-wrap:anywhere;max-width:32rem}
body[data-workspace="consulter"] #catalogue th{min-width:5rem}
`;
document.head.append(consultStyle);
const consultBox=text('section','');consultBox.id='consult-base';
$('base-preview').after(consultBox);
const consultLink=flowLink('Consulter la base','consulter');
document.querySelector('aside').insertBefore(consultLink,document.querySelector('aside [data-flow-page="ajouter"]'));
$('work-choices').append(flowLink('Consulter toutes les campagnes et leurs variantes','consulter'));
let consultQuery='',consultFilter='all';

function consultActive(c){return c.variants.find(v=>v.id===c.active)}
function consultState(c){return c.replaced_by?'Parent regroupé':c.active==null?'Sans référence active':c.eligible?'Éligible à l’exploitation':'Non éligible à l’exploitation'}

function consultMatches(c){
 const a=consultActive(c),m=a?.metadata||c.metadata||{};
 const hay=[c.id,c.label,m.entity,m.program_id,m.configuration_id,m.report_number,m.test_date,...c.variants.map(v=>v.run)].join(' ').toLocaleLowerCase('fr');
 return hay.includes(consultQuery.toLocaleLowerCase('fr'))&&(consultFilter==='all'||(consultFilter==='eligible'?c.eligible:!c.eligible));
}

function consultVariant(v,c){
 return button('Consulter V'+v.id,()=>task('Lecture de la variante…',async()=>{
  const d=await api('catalogue',{variant:v.id});catRender(d);
  const context=text('div','','card');
  context.append(text('h3','Statut et filiation'),text('p',`Campagne ${c.id} · V${v.id} · ${v.id===c.active?'Référence active':'Variante non active'} · ${reworkQualification(v)}`));
  context.append(text('p',consultState(c)));
  const campaignName=id=>{const found=state.campaigns.find(x=>x.id===id);return found?`${found.label} (campagne ${id})`:`Campagne ${id}`};
  if(c.parents.length)context.append(text('p','Campagnes parentes : '+c.parents.map(campaignName).join(' ; ')));
  if(c.replaced_by)context.append(text('p','Regroupée dans : '+campaignName(c.replaced_by)));
  const requests=new Set(state.journal.filter(j=>j.action==='PREPARE_REWORK'&&(j.detail.variants||[]).includes(v.id)).map(j=>j.detail.request_id));
  const traces=state.journal.filter(j=>['PREPARE_REWORK','OPEN_REWORK_ARCTA'].includes(j.action)&&((j.detail.variants||[]).includes(v.id)||j.detail.variant===v.id||requests.has(j.detail.request_id)));
  if(traces.length)context.append(catRaw(traces,'Retraitements associés — traces archivées'));
  $('catalogue').querySelector('h2').after(context);
  status(`V${v.id} consultée à la révision ${d.revision}. Aucune décision modifiée.`);
 }));
}

function consultRender(){
 consultBox.replaceChildren(text('h2','Campagnes enregistrées'));
 if(!state){consultBox.append(text('p','Ouvrir une base pour la consulter.'));return}
 consultBox.append(text('p',`Révision ${state.revision} · ${state.campaigns.length} campagne(s). Les variantes non actives restent consultables. Le statut métier est affiché sans possibilité de modification.`,'muted'));
 const tools=text('div','','consult-tools'),search=text('input',''),filter=text('select','');
 search.type='search';search.value=consultQuery;search.placeholder='Campagne, rapport, configuration, run…';
 for(const [value,label] of [['all','Toutes les campagnes'],['eligible','Éligibles à l’exploitation'],['other','Autres statuts']]){const o=text('option',label);o.value=value;filter.append(o)}filter.value=consultFilter;
 const sLabel=text('label','Rechercher');sLabel.append(search);
 const fLabel=text('label','Périmètre');fLabel.append(filter);
 tools.append(sLabel,fLabel);consultBox.append(tools);
 const list=text('div','','scroll');consultBox.append(list);

 function show(){
  const campaigns=state.campaigns.filter(consultMatches);
  list.replaceChildren(text('p',`${campaigns.length} campagne(s) affichée(s)`));
  const rows=campaigns.map(c=>{
   const a=consultActive(c),m=a?.metadata||c.metadata||{},name=text('div','');
   name.append(text('strong',c.label),text('small',`${m.entity||'—'} / ${m.program_id||'—'} / ${m.configuration_id||'—'}`),text('small','Campagne '+c.id,'muted'));
   const details=document.createElement('details');details.append(text('summary',`${c.variants.length} variante(s)`));
   const t=table(['Variante / run','Qualification','Essais retenus','Lecture'],c.variants.map(v=>[
    text('span',`V${v.id}${v.id===c.active?' — active':''} · ${v.run}`),
    reworkQualification(v),v.count,consultVariant(v,c)
   ]));
   t.classList.add('consult-variants');
   const wrap=text('div','','scroll');wrap.append(t);details.append(wrap);
   const action=text('div','');
   action.append(button('Voir les variantes',()=>{
    const old=$('consult-detail');if(old)old.remove();
    const box=text('div','','card');box.id='consult-detail';
    box.append(text('h3',c.label),details);details.open=true;
    consultBox.append(box);box.scrollIntoView({block:'nearest'});
   }));
   return [
    name,`${m.report_number||'—'} · ${m.test_date||'Date non renseignée'}`,
    a?'V'+a.id:'Aucune',a?a.count:'—',
    a?reworkQualification(a):'Sans référence active',action
   ];
  });
  const t=table(['Campagne / configuration','Rapport / date d’essai','Référence active','Essais retenus','Qualification','Détail'],rows);
  campaigns.forEach((c,i)=>t.querySelectorAll('tr')[i+1]?.children[4].append(text('small',consultState(c),'muted')));
  list.append(t);
 }
 search.oninput=()=>{consultQuery=search.value;show()};
 filter.onchange=()=>{consultFilter=filter.value;show()};
 show();
}

const consultRenderBefore=render;
render=function(){consultRenderBefore();catHide();consultRender()};
const consultOverviewBefore=flowOverview;
flowOverview=function(){
 consultOverviewBefore();
 const small=$('base-preview').querySelector('small');
 if(small)small.textContent='Le catalogue complet est accessible dans « Consulter la base ».';
};
if(location.pathname==='/dabcta/consulter')flowPage='consulter';
consultRender();flowApply();
