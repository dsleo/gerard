# Estimer un second tour sur de nouvelles circonscriptions

## Ce que montre l’écran

La légende resserrée et le sélecteur des tours sont regroupés dans un bandeau
centré en haut du canevas de la carte. Le cadrage réserve la place du bandeau
pour ne pas masquer le territoire.

Le sélecteur « Aujourd’hui / Demain ? » du titre passe de la carte officielle
au scénario de redécoupage. Un sélecteur à deux positions, juste sous la légende,
affiche le premier ou le second tour : résultats officiels de 2024 pour la carte actuelle, estimations
à partir des votes de 2024 pour les nouvelles limites. Les candidats élus dès
le premier tour restent représentés dans le résultat final de la carte officielle.

L’hémicycle figure dans la section « Second tour hypothétique », sous la carte.
Un second sélecteur compare la projection à la composition actuelle de l’Assemblée.
Le survol ou le focus d’un bloc affiche son total de sièges et, pour la projection,
sa plage de sièges simulée. La page principale ne présente plus de légende ni de
tableau sous l’hémicycle. Les sièges vacants de l’Assemblée actuelle et les sièges
sans estimation de la projection sont distingués au survol.

Le sélecteur de comparaison est placé sous l’hémicycle. Une icône d’information
à côté de « Second tour » ouvre l’explication en trois étapes dans une modale.
La vue des gains et pertes de sièges par département a été retirée de la carte.

La section « Comment la répartition des voix change ? » apparaît avant
l’hémicycle, avec uniquement la variation du MMD par bloc. Le MMD décrit une
asymétrie des scores locaux, pas leur dispersion. Sa formule et la définition
de la variation sont rendues en MathML dans une modale, accessible par une
icône discrète dont le libellé apparaît au survol ou au focus. Les détails de
validation, les limites et les comparaisons voix–circonscriptions sont regroupés
dans la page « Comment ça marche » (`redistricting/webapp/method.html`),
accessible depuis le pied de page commun aux deux vues. Elle décrit aussi
le graphe territorial, les mouvements ReCom, leur usage dans le recuit simulé
et les critères de recherche, avec un schéma et des références scientifiques.

Cette projection est un duel hypothétique entre les deux blocs arrivés en tête
au premier tour de chaque nouvelle circonscription. Elle ne prédit pas les
candidats qui se qualifieraient, les candidatures ni les désistements. Elle ne
représente pas des reports individuels de voix.

## Données et méthode

Les voix du premier tour sont réaffectées aux nouveaux contours à partir des
résultats des bureaux de vote et du croisement bureaux–IRIS. Les résultats de
second tour par circonscription officielle sont aussi disponibles. On retient
pour l’apprentissage les scrutins à exactement deux candidats, dont les deux
nuances appartiennent à deux blocs distincts. Les blocs sont agrégés selon les
correspondances publiées dans `blocs.draft.yaml`.

Pour chaque circonscription proposée, les deux premiers blocs forment le duel
hypothétique. Le modèle cherche les duels de 2024 avec les mêmes blocs finalistes
et un profil de premier tour proche (parts de voix de tous les blocs). Il
calcule une moyenne pondérée par la proximité pour estimer la part du premier
bloc dans le duel. Si moins de cinq duels historiques comparables existent, le
modèle revient à une référence sans transfert, proportionnelle aux parts du
premier tour des deux blocs finalistes.

La calibration mesure le biais moyen sur des prédictions hors échantillon.
Chaque département de validation est corrigé avec les erreurs des autres
départements. La correction globale n’est appliquée au modèle final que si elle
réduit l’erreur moyenne sans réduire le taux de bons blocs gagnants. Une
correction propre à chaque paire de blocs est également évaluée; elle n’est pas
retenue si elle dégrade le test hors échantillon.

Les intervalles de part de voix utilisent le 80e centile des erreurs absolues
après calibration. Quand un duel dispose d’au moins vingt erreurs de validation,
son profil d’erreurs sert à l’intervalle; sinon on reprend l’intervalle global.
Le repli sans transfert utilise une borne plus large, basée sur le 90e centile
global. Pour la fourchette de sièges, le modèle tire des erreurs observées et
réévalue le gagnant dans 1 000 simulations. La fourchette est élargie pour
inclure les résultats agrégés selon les regroupements politiques fin et large.

## Validation historique

La validation laisse de côté un département entier à la fois, afin que les
circonscriptions voisines d’un département ne soient pas à la fois dans
l’apprentissage et dans le test. Les résultats de calibration affichés dans
l’application sont issus de ces prédictions hors échantillon. Sur les 373 duels
testés, le biais global mesuré est de −0,01 point. Une correction globale ou
par paire de blocs n’améliore pas les résultats hors échantillon; la correction
appliquée est donc nulle. Le modèle retrouve le bloc gagnant dans 91,96 % des
cas, avec une erreur absolue moyenne de 2,24 points. L’intervalle annoncé comme
80 % couvre 79,9 % des erreurs testées. Ces scores mesurent la reproduction de
duels de blocs déjà observés; ils ne valident pas les hypothèses de candidature
sur une nouvelle carte.

L’estimation courante couvre 546 des 558 circonscriptions départementales de
la proposition. Parmi celles-ci, 542 ont un duel rapproché d’exemples de 2024;
les quatre autres utilisent la référence sans transfert. Les sièges non estimés
restent sans couleur dans l’hémicycle.

## Limites importantes

- Les duels historiques sont des résultats de candidats ramenés à leurs nuances,
  puis à des blocs. Les nuances et les blocs sont des catégories politiques,
  pas une observation du comportement individuel des électeurs.
- Un électeur peut s’abstenir, voter blanc ou nul, ou choisir un autre candidat.
  Le modèle absorbe ces différences dans les résultats agrégés sans reconstituer
  de flux individuels.
- La règle légale de qualification s’applique aux candidats selon leur part des
  inscrits (article L.162 du code électoral). Les résultats par bloc ne
  permettent pas de l’appliquer aux candidats fictifs d’un nouveau découpage.
- Les fourchettes de sièges rééchantillonnent les erreurs par circonscription et
  n’estiment pas les chocs communs à plusieurs départements. Elles restent une
  indication de sensibilité, pas une garantie probabiliste complète.
- Les regroupements politiques fin et large donnent des résultats différents;
  la fourchette affichée intègre cette sensibilité.

La carte reste une exploration d’un découpage de travail, non certifié.
