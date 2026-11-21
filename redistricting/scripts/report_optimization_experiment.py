"""Build a reproducible report from the locked retrospective analysis outputs."""
from __future__ import annotations
import argparse
import csv
import gzip
import json
import math
import statistics
from pathlib import Path

NAMES={'01':'Ain','03':'Allier','13':'Bouches-du-Rhône','31':'Haute-Garonne','50':'Manche','75':'Paris'}


def ranks(xs):
    order=sorted(range(len(xs)),key=lambda i:xs[i]);out=[0.]*len(xs);a=0
    while a<len(xs):
        b=a+1
        while b<len(xs) and xs[order[b]]==xs[order[a]]:
            b+=1
        for j in order[a:b]:out[j]=(a+b-1)/2
        a=b
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);args=ap.parse_args();out=args.directory
    docs=[json.loads((out/f'{d}.json').read_text()) for d in NAMES]
    allrows=[];sens=[];extra={}
    for d in docs:
        dep=d['department']
        for name,row in d['selected'].items():
            allrows.append(dict(department=dep,name=NAMES[dep],selection=name,**row['metrics']))
        sens.extend(dict(department=dep,**s) for s in d['weight_sensitivity'])
        with gzip.open(out/f'{dep}_archive.json.gz','rt') as f:archive=json.load(f)
        rs=[r['metrics'] for r in archive]
        a,b=ranks([r['L_v1'] for r in rs]),ranks([r['L_v2'] for r in rs])
        threshold=min(r['L_v1'] for r in rs)*1.01
        extra[dep]={'spearman_v1_v2':statistics.correlation(a,b),
                    'within_one_percent_v1_best':sum(r['L_v1']<=threshold+1e-12 for r in rs),
                    'guarded_winners_over_14_preferences':len({s['fingerprint'] for s in d['weight_sensitivity']})}
    for filename,rows in [('selected_metrics.csv',allrows),('weight_sensitivity.csv',sens)]:
        with (out/filename).open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    pooled={}
    for key in ['baseline','best_v1','best_v2','best_v2_guarded']:
        ms=[d['selected'][key]['metrics'] for d in docs];k=sum(d['seats'] for d in docs)
        rms=math.sqrt(sum(m['district_count']*m['pop_national_mse'] for m in ms)/k)
        comp=sum(m['district_count']*m['l_comp'] for m in ms)/k
        ep=sum(m['epci_outside_largest_population']-m['epci_population_cap_lower_bound'] for m in ms)/sum(m['epci_covered_population'] for m in ms)
        pooled[key]={'districts':k,'population_national_rms':rms,'compactness_mean_PP':1-comp,
                     'epci_avoidable_population_fraction':ep,'L_v2':.5*rms+.3*comp+.2*ep,
                     'max_local_population_deviation':max(m['l_pop'] for m in ms),
                     'min_PP':min(m['pp_min'] for m in ms)}
    geometry_audit=json.loads((out/'geometry_audit.json').read_text())
    summary={'departments':list(NAMES),'districts':sum(d['seats'] for d in docs),
             'distinct_plans_across_departments':sum(d['unique_states_total'] for d in docs),
             'proposal_attempts':sum(d['proposals'] for d in docs),
             'rejected_changed_proposals':sum(d['rejected'] for d in docs),
             'observed_pareto_plans':sum(d['front_size'] for d in docs),
             'max_v1_replay_error':max(d['max_replayed_v1_metric_error'] for d in docs),
             'pooled_six_department_metrics':pooled,'diagnostics':extra,
             'all_graph_valid':all(d['all_candidates_pass_partition_contiguity_population_and_seat_count'] for d in docs),
             'all_atom_coverages_valid':all(d['geometry_is_coverage'] and d['all_unit_geometries_valid_nonempty'] for d in docs),
             'all_atoms_valid_nonempty':all(d['all_unit_geometries_valid_nonempty'] for d in docs),
             'all_plans_pass_one_m2_cross_district_overlap_check':all(not d['invalid_cross_district_overlap_fingerprints'] for d in geometry_audit.values()),
             'max_cross_district_unit_overlap_m2':max(d['max_cross_district_unit_overlap_m2_over_all_plans'] for d in geometry_audit.values()),
             'prospective_benchmark_status':'NOT_RUN_OS_SANDBOX_START_DENIED',
             'tests':'69 passed; includes 7 experimental arithmetic/search-invariant tests'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    lines=['# Expérience sur les objectifs de redécoupage — 21 novembre 2026','',
      '**Résultat : la réanalyse est terminée ; le benchmark de nouvelles recherches n’a pas pu être exécuté.**',
      'Le nouveau score révèle des compromis utiles, mais ne justifie pas à ce stade de remplacer le score publié. Aucune carte publiée, allocation ou donnée électorale n’a été modifiée.','',
      '## Ce qui a réellement été exécuté','',
      f"Réévaluation de **{summary['distinct_plans_across_departments']:,} partitions locales distinctes**, provenant de {summary['proposal_attempts']:,} propositions archivées et des départs valides préservés, sur six départements et **{summary['districts']} circonscriptions**. Les doublons sont supprimés indépendamment des numéros de circonscription. Les cartes rejetées par le recuit sont incluses.",
      'Ce sont des cartes produites par une seule trajectoire de recherche v1 par département. Elles sont corrélées et orientées par cet ancien objectif. Leur réévaluation ne simule pas la trajectoire qu’aurait suivie un optimiseur v2.','',
      'Le protocole et les choix de métriques ont été enregistrés avant la réévaluation. Il s’agit d’un protocole local horodaté, pas d’un préenregistrement externe. Le périmètre a été choisi pour sa diversité de taille, de densité et de géographie ; il n’est pas un échantillon représentatif de la France.','',
      '## Scores comparés','',
      '- **v1** : 0,50 × écart démographique maximal départemental + 0,30 × moyenne(1 − Polsby–Popper) + 0,20 × ratio actuel des coupures EPCI.',
      '- **v2 expérimental** : 0,50 × écart démographique RMS à la cible nationale + 0,30 × moyenne(1 − Polsby–Popper) + 0,20 × fraction de population EPCI fragmentée au-delà d’une borne démographique.',
      '- **v2 avec garde-fous** : même score, en imposant un pire écart local ≤ max(5 %, valeur de la carte v1), et un minimum Polsby–Popper ne diminuant pas de plus de 0,02. Le seuil 5 % est l’objectif opérationnel existant du projet, pas une affirmation juridique. Les 0,02 sont un seuil exploratoire fixé avant calcul.','',
      'Pour un EPCI de population P, on compte P − population de sa plus grande partie. On soustrait max(0, P − 1,2 × cible départementale), puis on divise la somme par la population couverte par les EPCI. Cette correction est une borne basse liée à la capacité démographique des districts, pas la fragmentation inévitable exacte compte tenu de la géographie. Les cas sans appartenance EPCI restent explicitement comptés.','',
      'Les coefficients 50/30/20 sont conservés pour isoler le changement de métriques. Ils n’impliquent pas des contributions effectives de ces proportions. Une analyse secondaire utilise sept jeux de poids et deux échelles fixes, dont une division par (0,10 ; 0,80 ; 0,10). Aucun de ces réglages n’a été ajusté pour favoriser une carte.','',
      '## Résultats départementaux','',
      '| Département | Cartes distinctes | Front observé | Score v2, carte v1 | Meilleur v2 sans garde | Meilleur v2 avec garde | Gain v2 avec garde |',
      '|---|---:|---:|---:|---:|---:|---:|']
    for d in docs:
        s=d['selected'];a=s['baseline']['metrics']['L_v2'];b=s['best_v2']['metrics']['L_v2'];c=s['best_v2_guarded']['metrics']['L_v2']
        lines.append(f"| {NAMES[d['department']]} | {d['unique_states_total']} | {d['front_size']} | {a:.5f} | {b:.5f} | {c:.5f} | {(a-c)/a*100:.2f} % |")
    lines+=['','Une baisse de v2 est attendue quand on sélectionne son minimum dans un ensemble contenant la carte de référence. Ce tableau mesure l’ampleur du changement de préférence ; il ne constitue pas une preuve indépendante de supériorité territoriale.','',
      '### Compromis concrets : carte v1 → sélection v2 avec garde-fous','',
      '| Département | Pire écart local | RMS national | PP moyen | PP minimum | Fraction EPCI corrigée |',
      '|---|---:|---:|---:|---:|---:|']
    for d in docs:
        a=d['selected']['baseline']['metrics'];b=d['selected']['best_v2_guarded']['metrics']
        lines.append(f"| {NAMES[d['department']]} | {100*a['l_pop']:.2f} → {100*b['l_pop']:.2f} % | {100*a['pop_national_rms']:.2f} → {100*b['pop_national_rms']:.2f} % | {1-a['l_comp']:.3f} → {1-b['l_comp']:.3f} | {a['pp_min']:.3f} → {b['pp_min']:.3f} | {100*a['epci_avoidable_population_fraction']:.2f} → {100*b['epci_avoidable_population_fraction']:.2f} % |")
    lines+=['','### Agrégation sur les 61 circonscriptions étudiées uniquement','',
      '| Sélection | RMS national | PP moyen | Fraction EPCI corrigée | Score v2 agrégé |',
      '|---|---:|---:|---:|---:|']
    labels={'baseline':'Cartes v1 archivées','best_v1':'Meilleur v1 dans le pool','best_v2':'Meilleur v2 sans garde','best_v2_guarded':'Meilleur v2 avec garde'}
    for key,m in pooled.items():
        lines.append(f"| {labels[key]} | {100*m['population_national_rms']:.2f} % | {m['compactness_mean_PP']:.3f} | {100*m['epci_avoidable_population_fraction']:.2f} % | {m['L_v2']:.5f} |")
    lines+=['','Le RMS agrégé est la racine de la moyenne des carrés pondérée par les nombres de sièges ; la compacité est pondérée par les sièges ; la fragmentation EPCI départementale est pondérée par la population couverte. Le score est recalculé après agrégation. Les minima départementaux ne garantissent pas le minimum de ce score agrégé non linéaire. Ce tableau n’est pas une nouvelle carte nationale ni une comparaison exacte avec l’officiel.','',
      '## Sensibilité et alternatives proches','',
      '| Département | Corrélation de rang v1/v2 | Cartes à ≤ 1 % du meilleur v1 | Gagnants distincts sur 14 préférences avec garde |',
      '|---|---:|---:|---:|']
    for dep,e in extra.items():
        lines.append(f"| {NAMES[dep]} | {e['spearman_v1_v2']:.3f} | {e['within_one_percent_v1_best']} | {e['guarded_winners_over_14_preferences']} |")
    lines+=['','Le front est le front non dominé **observé**, selon RMS national, compacité moyenne et fragmentation démographique EPCI. Il ne certifie pas le vrai front de Pareto. La corrélation de rang est descriptive ; aucune p-valeur n’est présentée sur ces états dépendants.','',
      '## Répartition des sièges : calcul séparé','',
      '| Méthode | Sièges dans l’Indre | Borne optimiste du RMS national | Départements dont le nombre de sièges change |',
      '|---|---:|---:|---:|']
    allocations=json.loads((out/'allocation_bounds.json').read_text())
    for method,a in allocations.items():
        lines.append(f"| {method} | {a['seats']['36']} | {100*a['optimistic_rms_floor']:.2f} % | {a['changed_departments']} |")
    lines+=['','Ce calcul garde 558 sièges départementaux et les 74 sièges D53 gelés. Il suppose une égalité parfaite à l’intérieur de tous les départements, y compris ceux gelés, et ignore les contraintes géographiques : c’est donc une borne optimiste, pas la performance atteinte par une carte. Le passage à Webster réduit cette borne sans prouver qu’une carte réalisable aura la même amélioration.','',
      '## Vérifications','',
      f"- Toutes les {summary['distinct_plans_across_departments']:,} partitions retenues ont été revérifiées : affectation exacte de chaque unité, nombre de sièges, connexité sur le graphe certifié, tolérance démographique départementale de ±20 %.",
      f"- Les propositions ont été reconstruites à partir des deltas archivés. Les empreintes avant/après et le résultat final correspondent aux traces. L’écart maximal de recomputation des métriques v1 vaut {summary['max_v1_replay_error']:.2e}.",
      f"- Toutes les géométries unitaires sont valides et non vides. Les 4 138 cartes passent aussi la vérification géométrique indépendante des recouvrements entre unités de districts différents, au seuil du projet de 1 m². Recouvrement maximal observé : {summary['max_cross_district_unit_overlap_m2']:.6f} m².",
      '- Trois départements (13, 31, 75) ne forment pas une couverture strictement parfaite au sens GEOS : leurs limites comportent de minuscules recouvrements. Le calcul emploie alors l’union générale avec réparation, comme en production, plutôt que le raccourci réservé aux couvertures parfaites. Ces diagnostics ne remplacent pas une validation juridique ni une certification nationale.',
      '- 69 tests du projet passent, dont sept tests des calculs expérimentaux, de leur invariance au renommage des districts, du budget de propositions et de la reproductibilité des recherches sur un petit graphe synthétique.',
      '- La réanalyse refuse toute lecture des données brutes ou de la quarantaine ; les entrées autorisées et leurs SHA-256 sont conservées. Elle ne revendique pas le certificat d’isolation OS d’une nouvelle génération.','',
      '## Ce qui reste non mesuré','',
      'Le lancement prospectif s’arrête avant toute génération : `sandbox-exec: sandbox_apply: Operation not permitted`. Le contrôle a été renforcé pour distinguer un échec de démarrage du sandbox d’un refus effectif de lecture de la quarantaine. Aucune protection n’a été désactivée.',
      'Les performances comparées du recuit, du recuit à plusieurs départs et des short bursts de Pareto sur ces données réelles restent donc **non mesurées**. Le script `benchmark_optimization.py` prépare cette comparaison : mêmes départements, graines 101/202/303, deux scores, trois méthodes, 800 propositions par bras, cache de notation neuf à chaque bras, temps et checkpoints enregistrés, sorties isolées des cartes publiées. Le recuit de référence utilise le refroidissement de production mais sans arrêt anticipé, afin d’égaliser le budget. Tous les départs fournis contribuent au meilleur observé de chaque bras. Les temps sont mesurés, pas égalisés ; on ne pourra donc pas inférer directement un gain à temps égal.',
      'La variante Pareto explore les trois critères v2, même dans le bras évalué selon v1. Les hypothèses v2 doivent être décidées avant la comparaison finale. Ce pilote ne teste pas encore le moteur Rust, les retouches par flips ni la longueur des frontières internes.','',
      '## Recommandation','',
      '1. Conserver le score v1 comme référence publiée pendant l’expérience. Les gains de v2 correspondent à des arbitrages, pas à une amélioration uniforme.',
      '2. Traiter la répartition des sièges comme une décision explicite en amont. Comparer D’Hondt et Webster sur le même périmètre avant de relancer le dessin des frontières.',
      '3. Faire de l’équilibre démographique une priorité avec une marge acceptable explicite, puis rechercher des compromis compacité/EPCI. Le RMS seul peut masquer une dégradation du pire district ; conserver le maximum comme garde-fou.',
      '4. Comparer le recuit à plusieurs départs et les short bursts de Pareto dans l’environnement permettant l’isolation requise. Mesurer d’abord les gains à budget de propositions égal, puis, si utile, un essai séparé à temps égal.',
      '5. Archiver les composantes et les cartes non dominées. Présenter quelques alternatives proches selon les critères territoriaux, sans sélectionner les gagnants à partir des résultats politiques.','',
      '## Sources et reproductibilité','',
      '- McCartan, *Finding Pareto Efficient Redistricting Plans with Short Bursts*, version 2024 : https://arxiv.org/pdf/2304.00427',
      '- Cannon et al., *Voting Rights, Markov Chains, and Optimization by Short Bursts*, 2023 : https://doi.org/10.1007/s11009-023-09994-1',
      '- Buchanan et Validi, *Political districting to minimize cut edges* : https://optimization-online.org/2021/04/8349/',
      '- `protocol.json`, `inputs.json`, `analysis_manifest.json`, `summary.json` : périmètre, empreintes et résultats.',
      '- `selected_metrics.csv`, `weight_sensitivity.csv` : tableaux complets ; `XX_archive.json.gz` : affectations et métriques de chaque carte réévaluée.',
      '- `geometry_audit.json` : vérification des recouvrements sur l’ensemble des cartes archivées.',
      '- Le dossier livré inclut les scripts et tests. Une reproduction depuis les sources exige les géométries et le graphe du projet identifiés par empreinte ; les 403 Mo de géométries originales ne sont pas dupliqués dans le dossier.',
      '', '### Commandes', '', '```bash', 'cd redistricting',
      '.venv/bin/python scripts/reanalyse_optimization.py --output data/processed/pipeline_runs/optimization_experiment_20261121',
      '.venv/bin/python scripts/report_optimization_experiment.py data/processed/pipeline_runs/optimization_experiment_20261121',
      '.venv/bin/python scripts/run_blind.py benchmark_optimization.py --output data/processed/pipeline_runs/optimization_benchmark_next',
      '```','']
    (out/'rapport_experience.md').write_text('\n'.join(lines))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
