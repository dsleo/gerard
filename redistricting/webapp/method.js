const $ = selector => document.querySelector(selector);
const fmt = (value, digits = 0) => Number(value).toLocaleString('fr-FR', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const pct = (value, digits = 1) => fmt(value * 100, digits) + ' %';
const points = value => (value > 0 ? '+' : '') + fmt(value * 100, 2) + ' pt';
const blocs = [
  ['left', 'Gauche', '#B85E43'], ['centre', 'Centre', '#D39476'],
  ['right', 'Droite républicaine', '#4E7883'], ['far_right', 'Droite nationale', '#829DA0'], ['other', 'Autres', '#EEE8D8']
];
async function renderMethod() {
  try {
    const data = await window.REDISTRICTING_DATA['projection-2026'];
    const round = data.round_two, validation = round.validation;
    const draft = data.run_summary;
    $('#draft-scope').textContent = fmt(draft.generated_districts) + ' circonscriptions sont générées dans ' + fmt(draft.generated_departments) + ' départements ; ' + fmt(draft.carry_forward_districts) + ' restent inchangées dans les ' + fmt(draft.carry_forward_departments) + ' autres. Le périmètre départemental compte ' + fmt(draft.departmental_districts) + ' sièges, auxquels s’ajoutent 19 sièges hors de ce périmètre, pour un total de 577.';
    $('#round2-coverage').textContent = fmt(round.estimated_districts) + ' circonscriptions départementales ont une estimation, dont ' + fmt(round.matched_historical_pair_districts) + ' à partir de duels analogues de 2024.';
    $('#validation-stats').innerHTML = '<div><strong>' + pct(validation.bloc_winner_match_rate) + '</strong><span>de gagnants de bloc retrouvés</span></div><div><strong>' + fmt(validation.mean_absolute_vote_share_error * 100, 2) + ' points</strong><span>d’erreur absolue moyenne</span></div><div><strong>' + fmt(validation.held_out_predictions) + '</strong><span>duels historiques testés</span></div>';
    $('#calibration-text').textContent = 'Le biais global mesuré est de ' + points(validation.measured_global_bias) + '. ' + (validation.calibration_applied ? 'Une correction globale de ' + points(validation.applied_calibration_bias) + ' est appliquée.' : 'Les corrections globale et par type de duel ont été testées puis écartées : elles n’améliorent pas les critères de validation.') + ' L’intervalle individuel annoncé à 80 % couvre ' + pct(validation['80pct_interval_coverage']) + ' des erreurs historiques testées.';
    $('#validation-table tbody').innerHTML = [
      ['Sans correction', validation.raw_bloc_winner_match_rate, validation.raw_mean_absolute_vote_share_error],
      ['Correction globale testée', validation.candidate_calibrated_bloc_winner_match_rate, validation.candidate_calibrated_mean_absolute_vote_share_error],
      ['Correction par duel testée', validation.pair_calibrated_bloc_winner_match_rate, validation.pair_calibrated_mean_absolute_vote_share_error]
    ].map(([label, rate, error]) => '<tr><td>' + label + '</td><td>' + pct(rate) + '</td><td>' + fmt(error * 100, 2) + '</td></tr>').join('');
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
renderMethod();
