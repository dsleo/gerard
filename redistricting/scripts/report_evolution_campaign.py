"""Summarize the executed synthetic rehearsal and prepared real-data campaign."""
import argparse
import csv
import hashlib
import json
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--synthetic',type=Path,required=True)
    ap.add_argument('--prepared',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    summary=json.loads((args.synthetic/'summary.json').read_text())
    config=json.loads((args.prepared/'protocol.json').read_text())
    evolution=json.loads((args.synthetic/'evolution.json').read_text())
    labels=['ReCom + recuit','ReCom + recuit à plusieurs départs','ReCom + short bursts','Hybride ReCom/flip + recuit']
    rows=list(csv.DictReader((args.synthetic/'metrics.csv').open()))
    benchmark={}
    import sys
    sys.path.insert(0,str(ROOT/'src'))
    from redistrict.optimize.evolve import initial_policies
    for p,label in zip(initial_policies(),labels):
        r=[x for x in rows if x['stage']=='benchmark' and x['policy_id']==p.id]
        benchmark[label]={'trials':len(r),'proposal_calls_per_trial':64,
                          'mean_relative_gain':statistics.mean(float(x['relative_gain']) for x in r),
                          'mean_seconds':statistics.mean(float(x['seconds']) for x in r)}
    attempts={'benchmark_real':{'exit_code':3,'status':'NOT_RUN','error':'sandbox-exec: sandbox_apply: Operation not permitted'},
              'evolution_real':{'exit_code':3,'status':'NOT_RUN','error':'sandbox-exec: sandbox_apply: Operation not permitted'}}
    (out/'real_launch_attempts.json').write_text(json.dumps(attempts,indent=2)+'\n')
    result={'real_data_status':'NOT_RUN_OS_ISOLATION_START_DENIED',
            'synthetic_status':summary['status'],'synthetic_trials':summary['trials'],
            'synthetic_proposal_calls':summary['proposal_calls'],'synthetic_benchmark':benchmark,
            'synthetic_unique_policy_evaluations':evolution['unique_evaluations'],
            'synthetic_new_policy_selected':not summary['selection']['selected_is_seed_baseline'],
            'synthetic_evolution_extra_gain_vs_random':summary['train_best_evolution_gain']-summary['train_best_random_control_gain'],
            'retained_map_audit':summary['retained_map_audit'],
            'real_pilot_prepared':True,'national_series_prepared':True,
            'production_changed':False}
    (out/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    lines=['# Benchmark ReCom et petite boucle évolutive','',
      '**Le benchmark réel reste bloqué avant exécution. La répétition synthétique complète est terminée ; le pilote réel et la série nationale sont préparés et exécutables.**','',
      '## Ce qui a été exécuté','',
      f"- {summary['trials']} essais, {summary['proposal_calls']:,} appels de proposition sur quatre graphes synthétiques construits par formule, avec populations non uniformes et deux organisations EPCI.",
      '- Deux graphes servent à l’entraînement, un à la validation et un au test final. Les graines de test sont distinctes. Les graphes et découpages initiaux sont simples ; ils ne représentent pas la complexité française.',
      f"- {evolution['unique_evaluations']} politiques distinctes évaluées : huit évaluations nominales par bras, dont quatre politiques initiales partagées entre évolution et recherche aléatoire.",
      f"- Audit séparé de {summary['retained_map_audit']['distinct_retained_maps_checked']} cartes synthétiques retenues : partitions, sièges, connexité, populations, recouvrements et recalcul des scores. Écart maximal de recalcul : {summary['retained_map_audit']['max_metric_error']:.2e}.",
      '- 88 tests du projet passent, notamment le refus d’utiliser un résultat synthétique pour choisir une stratégie réelle, le gel de la sélection avant le test final et le maintien du score/contraintes.','',
      '## Benchmark synthétique — portée limitée','',
      'Chaque stratégie reçoit exactement 64 propositions par essai, sur les deux graphes d’entraînement avec deux graines. Les gains ci-dessous sont calculés par rapport aux départs synthétiques en bandes. Ce ne sont pas des gains observés sur les cartes françaises.','',
      '| Stratégie | Essais | Baisse moyenne du score v1 synthétique |',
      '|---|---:|---:|']
    for label,r in benchmark.items():lines.append(f"| {label} | {r['trials']} | {100*r['mean_relative_gain']:.2f} % |")
    lines+=['','**Résultat de la boucle évolutive : aucun gain sur le meilleur programme initial, ni sur le contrôle aléatoire, dans ce petit test.** La validation sélectionne le recuit à plusieurs départs. Le même programme est conservé pour le test final ; aucune nouvelle heuristique n’est promue. L’évolution et la recherche aléatoire retrouvent toutes deux le meilleur programme initial sur l’entraînement.',
      'Les temps sont enregistrés par essai mais ces exécutions très courtes ne constituent pas un benchmark de vitesse fiable. Aucun intervalle de confiance ni test d’hypothèse n’est calculé sur ces quelques graphes ; des graines sur un même graphe ne sont pas des instances indépendantes.','',
      '## Première version inspirée d’AlphaEvolve','',
      'La boucle propose des mutations/croisements, évalue chaque enfant avec un évaluateur fixe, conserve une population de bonnes stratégies et compare cette sélection à une recherche aléatoire au même budget nominal. Les premières politiques sont écrites lors de l’implémentation ; les mutations ultérieures sont algorithmiques.',
      'Elle fait évoluer des programmes restreints décrits en JSON : choix du contrôleur (recuit, short bursts ou front de Pareto), biais vers les paires démographiquement déséquilibrées, préférence des arbres pour conserver les EPCI, mélange ReCom/retouches de frontière, température et refroidissement. Les gènes inactifs sont normalisés pour ne pas compter artificiellement deux fois une stratégie identique.',
      '**Le score v1, ses poids, l’allocation D53 et les règles de validité ne peuvent pas muter.** Le score v2 reste une mesure secondaire. Les features sont géographiques, démographiques et EPCI ; aucune donnée électorale n’est utilisée.',
      'C’est une petite évolution d’heuristiques dans un espace borné, pas une réimplémentation d’AlphaEvolve : aucun appel LLM externe, aucune réécriture autonome de Python ni évolution de l’évaluateur. Si les stratégies simples restent meilleures, elles sont conservées.','',
      '## Pilote réel préparé','',
      '| Phase | Départements | Graines | Propositions par stratégie et graine |',
      '|---|---|---|---:|',
      '| Benchmark initial | 01, 03, 50 | 101, 202 | 192 |',
      '| Évolution et contrôle aléatoire | 01, 03, 50 | 11, 23 | 96 |',
      '| Validation des finalistes | 13, 31, 75 | 101, 202 | 192 |',
      '| Test final après sélection figée | 06, 33, 69 | 1009, 1013, 1019 | 256 |','',
      'L’évolution et le contrôle disposent chacun de dix politiques, dont quatre initiales communes. La liste des finalistes est gelée avant validation ; le gagnant et la référence sont gelés avant le test final. Les départements 06/33/69 ne servent pas à régler les heuristiques.',
      'Chaque essai part du gagnant départemental archivé, accompagné des autres départs valides distincts. La meilleure carte connue est toujours conservée. Chaque bras possède un cache de notation neuf. Le benchmark conserve le refroidissement et la famille de propositions de production, mais fixe le nombre maximal de tirages d’arbres à 64 et désactive l’arrêt sur plateau ; ce n’est donc pas un replay exact du calcul historique.',
      'Les budgets sont égaux en appels de proposition, pas en temps CPU : un flip et un ReCom peuvent avoir des coûts différents. Les temps et le nombre d’états distincts sont enregistrés. Si un essai ne finit pas son budget, il n’est pas classé et le pilote est marqué incomplet.',
      'Le pilote est plafonné à 30 minutes, avec une limite souple de 60 secondes par essai, vérifiée entre propositions. Au maximum environ 34 560 appels de proposition sont prévus ; ce nombre n’est pas une prédiction de durée.','',
      '## Série nationale suivante préparée','',
      '- Départements éligibles : départements non gelés à plusieurs circonscriptions, résolus depuis l’état Gate 1. Les départements D53 gelés et les départements à une seule circonscription restent inchangés.',
      '- Trois graines : 509, 1009, 2029 ; 800 propositions par département et graine ; plafond global d’une heure, avec points de reprise et statut partiel explicite si nécessaire.',
      '- La stratégie vient exclusivement du pilote **réel**. Une stratégie nouvelle doit dépasser la référence choisie sur validation dans la moyenne du test final et dans au moins deux des trois départements de test ; sinon la référence est utilisée. Le test final ne déclenche aucune nouvelle mutation.',
      '- Chaque sortie départementale est auditée et ne peut remplacer sa carte de départ que si son score v1 est strictement plus bas. Le score v2 et les compromis restent enregistrés.',
      '- Les plans sont écrits dans un nouveau dossier. Aucun export ni remplacement de la carte de l’application n’est déclenché. L’assemblage et la publication nationale exigent ensuite les contrôles existants.',
      '- Le lanceur national refuse explicitement un pilote synthétique ou incomplet et vérifie les empreintes du code utilisé par le pilote. Cette série est préparée, pas exécutée.','',
      '## Blocage effectif','',
      'Le lancement du benchmark réel, puis celui du nouveau pilote, se sont tous deux arrêtés avec le code 3 : `sandbox-exec: sandbox_apply: Operation not permitted`. Le sandbox macOS exigé par le projet ne démarre pas dans l’environnement d’exécution actuel. La protection n’a pas été désactivée et aucun résultat réel n’est revendiqué.',
      'Le rapport précédent portait sur une réanalyse des cartes archivées. Le présent test synthétique ne permet pas davantage de conclure quelle stratégie est meilleure pour la France.','',
      '## Lancement dans un environnement où l’isolation macOS fonctionne','',
      'Depuis le dossier `redistricting/`, utiliser un nouveau dossier de sortie pour chaque exécution :','',
      '```bash',
      '.venv/bin/python scripts/run_blind.py run_evolution_campaign.py --output data/processed/pipeline_runs/recom_evolve_real',
      '```','',
      'Après réussite du pilote réel et de son audit :','',
      '```bash',
      '.venv/bin/python scripts/run_blind.py run_next_optimization_series.py --pilot-result data/processed/pipeline_runs/recom_evolve_real --output data/processed/pipeline_runs/recom_evolve_national',
      '```','',
      'Les lanceurs refusent les sorties existantes. La série nationale peut terminer partiellement sous son plafond de temps ; ce cas est signalé par un code de sortie non nul et une liste des départements non terminés.','',
      '## Fichiers et référence','',
      '- `run_evolution_campaign.py` : benchmark, évolution, contrôle aléatoire, validation, test final et audit.',
      '- `run_next_optimization_series.py` : sélection figée, confirmation avant déploiement, raffinement national et non-régression.',
      '- `optimize/evolve.py` : langage de politiques, propositions, boucle évolutive et audit des cartes retenues.',
      '- `protocol.json`, `source_hashes.json`, `metrics.csv`, `evolution.json` et les essais JSON permettent d’inspecter les évaluations.',
      '- AlphaEvolve, Novikov et al. (2025) : https://arxiv.org/abs/2506.13131. L’inspiration porte sur la boucle mutation–évaluation–sélection, avec les différences explicitées plus haut.','']
    (out/'rapport_benchmark_evolution.md').write_text('\n'.join(lines))
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
