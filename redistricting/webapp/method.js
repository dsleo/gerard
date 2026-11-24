const $ = selector => document.querySelector(selector);
const fmt = (value, digits = 0) => Number(value).toLocaleString('fr-FR', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const pct = (value, digits = 1) => fmt(value * 100, digits) + ' %';
const points = value => (value > 0 ? '+' : '') + fmt(value * 100, 2) + ' pt';
const blocs = [
  ['lfi', 'Extrême gauche', '#8F3441'], ['left', 'Gauche', '#B85E43'], ['centre', 'Centre', '#D39476'],
  ['right', 'Droite républicaine', '#4E7883'], ['far_right', 'Extrême droite', '#829DA0'], ['other', 'Autres', '#EEE8D8']
];
async function renderMethod() {
  try {
    const data = await window.REDISTRICTING_DATA['projection-2026'];
    const round = data.round_two, validation = round.validation;
    const draft = data.run_summary;
    $('#draft-scope').textContent = fmt(draft.generated_districts) + ' circonscriptions sont générées dans ' + fmt(draft.generated_departments) + ' départements ; ' + fmt(draft.carry_forward_districts) + ' restent inchangées dans les ' + fmt(draft.carry_forward_departments) + ' autres. Le périmètre départemental compte ' + fmt(draft.departmental_districts) + ' sièges, auxquels s’ajoutent 19 sièges hors de ce périmètre, pour un total de 577.';
    $('#validation-stats').innerHTML = '<div><strong>' + pct(validation.bloc_winner_match_rate) + '</strong><span>de gagnants de bloc retrouvés</span></div><div><strong>' + fmt(validation.mean_absolute_vote_share_error * 100, 2) + ' points</strong><span>d’erreur absolue moyenne</span></div><div><strong>' + fmt(validation.held_out_predictions) + '</strong><span>duels historiques testés</span></div>';
    const bars = (row, color) => row ? '<div class="comparison-bars" style="--bloc-color:' + color + '"><div class="comparison-bar"><i style="--share:' + row.vote_share * 100 + '"></i><span>' + pct(row.vote_share) + '</span></div><div class="comparison-bar seats"><i style="--share:' + row.seat_share * 100 + '"></i><span>' + pct(row.seat_share) + '</span></div></div>' : '—';
    $('#metric-table tbody').innerHTML = blocs.map(([id, label, color]) => {
      const before = data.official.blocks[id], after = data.proposal.blocks[id];
      return '<tr><td>' + label + '</td><td class="comparison-cell">' + bars(before, color) + '</td><td class="comparison-cell">' + bars(after, color) + '</td><td>' + (before ? points(before.seat_minus_vote) : '—') + '</td><td>' + (after ? points(after.seat_minus_vote) : '—') + '</td></tr>';
    }).join('');
    $('#electoral-scope').textContent = 'Périmètre métropolitain avec données disponibles : ' + fmt(data.official.districts) + ' circonscriptions sur la carte actuelle et ' + fmt(data.proposal.districts) + ' sur la proposition. Les couvertures diffèrent : les comparaisons électorales ne portent pas exactement sur les mêmes électeurs. Les scores locaux donnent le même poids à chaque circonscription pour le MMD.';
    $('#mmd-table tbody').innerHTML = blocs.map(([id, label]) => {
      const before = data.official.blocks[id]?.mmd, after = data.proposal.blocks[id]?.mmd;
      return '<tr><td>' + label + '</td><td>' + (before == null ? '—' : points(before)) + '</td><td>' + (after == null ? '—' : points(after)) + '</td><td>' + (before == null || after == null ? '—' : points(after - before)) + '</td></tr>';
    }).join('');
  } catch (error) {
    console.error(error);
    $('#method-status').textContent = 'Les données chiffrées ne sont pas disponibles. Les explications ci-dessus restent consultables.';
  }
}
if (window.katex) {
  document.querySelectorAll('.tex-equation').forEach(function (equation) {
    window.katex.render(equation.dataset.tex, equation, { displayMode: true, throwOnError: false });
  });
}
renderMethod();

// Preserve direct links into any section while showing one part of the guide at a time.
(function () {
  var groups = ['methode', 'donnees', 'conclusions'];
  var links = document.querySelectorAll('[data-section-link]');
  function show(group) {
    document.querySelectorAll('[data-guide-group]').forEach(function (el) { el.hidden = el.dataset.guideGroup !== group; });
    document.querySelectorAll('[data-nav-group]').forEach(function (el) { el.hidden = el.dataset.navGroup !== group; });
    links.forEach(function (el) { if (el.dataset.sectionLink === group) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current'); });
  }
  function sync() {
    var hash = decodeURIComponent(location.hash.slice(1));
    var target = document.getElementById(hash);
    var section = target && target.closest('[data-guide-group]');
    show(groups.includes(hash) ? hash : section ? section.dataset.guideGroup : 'methode');
    if (section) requestAnimationFrame(function () { target.scrollIntoView(); });
  }
  links.forEach(function (link) {
    link.addEventListener('click', function (event) {
      event.preventDefault();
      var group = link.dataset.sectionLink;
      if (location.hash !== '#' + group) history.pushState(null, '', '#' + group);
      show(group);
    });
  });
  window.addEventListener('hashchange', sync);
  sync();
})();
