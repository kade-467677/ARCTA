// 64E2 : préparation explicite, distincte de la validation métier.
const groupingBefore64E2 = showGrouping;
showGrouping = function(box, d) {
  groupingBefore64E2(box, d);
  if (d.blockers.length) return;
  const panel = text('div', '', 'card');
  panel.append(text('h3', 'Constituer le dossier de réanalyse'), text('p',
    'Copie des seuls essais retenus et archivage de leur provenance. Aucun calcul ni validation métier.'));
  const title = document.createElement('input'); title.maxLength = 120;
  const reason = document.createElement('textarea'); reason.maxLength = 2000;
  const select = document.createElement('select');
  const empty = text('option', 'Choisir les paramètres statistiques communs'); empty.value = ''; select.append(empty);
  d.campaigns.forEach(c => {const o = text('option', `Campagne ${c.id} — ${c.label}`); o.value = c.id; select.append(o)});
  const independent = document.createElement('input'); independent.type = 'checkbox'; independent.style.width = 'auto';
  function field(label, input) {const el = text('label', label); el.append(input); panel.append(el)}
  title.placeholder = 'Exemple : Regroupement Main Wheel';
  field('Nom de la réanalyse — pas un chemin', title);
  panel.append(text('p', 'Destination automatique : sous-dossier REANALYSES à côté de la base SQLite ouverte. Le chemin exact est affiché après création.', 'muted'));
  field('Paramètres statistiques repris de', select);
  field('Motif du regroupement', reason);
  field(' Je confirme que ces campagnes correspondent à des acquisitions indépendantes.', independent);
  panel.append(text('p', 'Les écarts statistiques figurent dans le précontrôle ci-dessus. CONFIG, unités, mapping et DIAG devront être revus dans ARCTA.', 'muted'));
  let requestId = crypto.randomUUID();
  [title, reason, select, independent].forEach(el => el.addEventListener('change', () => {requestId = crypto.randomUUID()}));
  panel.append(button('Créer le dossier de réanalyse', () => task('Vérification et copie des acquisitions…', async () => {
    if (!title.value.trim() || !reason.value.trim() || !select.value || !independent.checked)
      throw Error('Renseigner le nom, le motif, les paramètres communs et confirmer l’indépendance.');
    const packet = await api('prepare-reanalysis', {campaigns: d.campaigns.map(c=>c.id), revision: d.revision,
      title: title.value.trim(), reason: reason.value.trim(), settings_campaign: Number(select.value),
      independent: independent.checked, request_id: requestId});
    state = await api('status'); render();
    status(`Dossier ${packet.reused?'déjà préparé':'créé'} : ${packet.directory} — ${packet.trial_count} essais. Aucun calcul lancé.`);
    await showReanalysisHistory();
  })));
  box.append(panel);
};
async function showReanalysisHistory() {
  const box = $('reanalysis-history'); if (!box) return;
  const response = await api('reanalyses');
  box.replaceChildren(text('h3', 'Dossiers préparés — en attente de réanalyse ARCTA'));
  if (!response.packets.length) {box.append(text('p', 'Aucun dossier préparé.')); return}
  response.packets.forEach(p => box.append(button('Ouvrir dans ARCTA — ' + p.title, () => task('Création ou reprise de la session ARCTA…', async () => {
    const result = await api('open-reanalysis', {request_id:p.request_id});
    try { localStorage.setItem('arcta_web_session_id', result.session_id); } catch (e) {}
    window.location.assign(result.url);
  }))));
  box.append(catTable(['Date','Nom de la réanalyse','Campagnes','Essais','Paramètres de','Révision','Emplacement réel'], response.packets.map(p=>[
    date(p.utc),p.title,p.campaigns.join(', '),p.trial_count,`Campagne ${p.settings_campaign}`,p.revision,p.directory])));
}
const renderGroupingBefore64E2 = renderGrouping;
renderGrouping = function(s) {
  renderGroupingBefore64E2(s);
  const host = $('grouping'), box = text('div', ''); box.id = 'reanalysis-history';
  host.append(button('Afficher les dossiers de réanalyse', () => task('Lecture des dossiers préparés…', showReanalysisHistory)), box);
};
