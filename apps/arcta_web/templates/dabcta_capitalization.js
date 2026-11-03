// 64E4 : décision explicite, distincte de la future qualification métier indépendante.
const reviewBefore64E4 = review;
function renderCapitalization(c, host) {
  document.getElementById('capitalization-panel')?.remove();
  if (!c?.reanalysis) return;
  $('decision-form').hidden = true;
  const panel = text('div', '', 'card'); panel.id = 'capitalization-panel';
  panel.append(text('h3', 'Réanalyse — retour dans DABCTA'));
  const r = c.reanalysis;
  if (state.business_gate && !c.business?.eligible) {
    panel.append(text('p','Qualification métier requise avant capitalisation.','warn'));
    host.append(panel); return;
  }
  if (!r.ready) {
    panel.append(text('p', r.error, 'warn')); host.append(panel); return;
  }
  panel.append(text('p', `${r.retained_count} essais retenus ; ${r.excluded_count} écartés lors de la réanalyse.`));
  panel.append(table(['Campagne parente', 'Variante utilisée'], r.parents.map(p => [p.label, p.variant])));
  panel.append(text('p', 'Le regroupement deviendra la référence courante. Ses parents seront archivés et exclus des exports courants, sans suppression de leur historique.'));
  panel.append(text('p', 'La qualification métier et cet arbitrage de capitalisation sont deux décisions distinctes.', 'warn'));
  const label = document.createElement('input'); label.value = [c.identity.report_number, c.identity.configuration_id].filter(Boolean).join(' — ');
  const reason = document.createElement('textarea');
  const confirm = document.createElement('input'); confirm.type = 'checkbox'; confirm.style.width = 'auto';
  for (const [name, input] of [['Nom du regroupement', label], ['Motif de capitalisation', reason], [' Je confirme le remplacement des campagnes parentes dans le périmètre courant.', confirm]]) {
    const field = text('label', name); field.append(input); panel.append(field);
  }
  panel.append(button('Capitaliser et archiver les parents', () => task('Vérification de la filiation et capitalisation…', async () => {
    if (!confirm.checked || !label.value.trim() || !reason.value.trim()) throw Error('Renseigner le nom, le motif et confirmer le remplacement des parents.');
    state = await api('capitalize-reanalysis', {candidate:c.key, label:label.value.trim(), reason:reason.value.trim(), confirm_parents:true});
    render(); status('Regroupement capitalisé. Parents archivés ; aucune acquisition comptée deux fois dans ce remplacement.');
  })));
  host.append(panel);
}
review = function(){reviewBefore64E4();renderCapitalization(candidate(),$('candidate-info'));};
const renderBefore64E4 = render;
render = function() {
  renderBefore64E4();
  const waiting = state.candidates.filter(c=>c.reanalysis && c.status==='À examiner').length;
  let notice = $('inventory-summary');
  if (!notice) {notice=text('p','');notice.id='inventory-summary';$('errors').before(notice)}
  notice.textContent = `${state.candidates.length} run(s) lisible(s) · ${waiting} réanalyse(s) à examiner · ${state.errors.length} export(s) non importable(s).`;
};
actions.CAPITALIZE_REANALYSIS = 'Regroupement capitalisé — parents archivés';
