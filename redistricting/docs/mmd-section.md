# Section MMD : texte proposé

Brouillon pour la page « Comment ça marche », chapitre « Des voix partout, ou quelques bastions ? ». Non publié sur le site.

## Texte à ajouter

Après le paragraphe sur l’exemple (« … Cet indicateur décrit donc une asymétrie, pas la dispersion. ») :

### Ce que mesurent les deux cartes

Sur la carte neutre, le MMD est calculé pour la carte actuelle et pour la proposition, à partir des votes du premier tour 2024 dans chaque circonscription disposant de résultats. Le tableau ci-dessous compare les deux, bloc par bloc.

Sur les cartes partisanes, chaque scénario est comparé à la carte actuelle selon le même calcul. La variation affichée dans l’atlas correspond au scénario choisi ; elle reste « — » lorsqu’elle n’est pas calculée.

Un MMD positif signifie que la moyenne des circonscriptions dépasse la médiane pour ce bloc ; une variation positive signifie que cet écart a augmenté. Ni l’un ni l’autre ne dit, à lui seul, combien de sièges un bloc obtient.

## Tableau

En-têtes proposés : « Carte actuelle (points) », « Carte neutre (points) », « Variation (points) » (au lieu de « Actuel (points) » et « Proposé (points) »).

## À vérifier avant publication

- La base de calcul de la carte neutre (premier tour 2024) est déduite du pipeline Python (`scripts/augment_partisan_metrics.py`, `scripts/build_results_view_data.py`), pas confirmée dans les sorties affichées sur le site.
- Vérifier que le calcul partisan et le calcul neutre utilisent bien la même définition du MMD.
