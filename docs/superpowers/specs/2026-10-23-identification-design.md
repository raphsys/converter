# Module IDENTIFICATION — conception

## Finalité

Deuxième module du pipeline : `SEGMENTATION -> IDENTIFICATION -> EXTRACTION DES ATTRIBUTS`.
Pour chaque bbox produite par la segmentation, dire **ce que c'est** : son type, pris dans la
liste fermée du référentiel (`docs/referentiel/referentiel.json`), avec son statut, sa
confiance, les autres types possibles et les indices qui fondent la décision. Les types
présents **à l'intérieur d'un texte** (expressions à protéger, éléments en ligne) sont
identifiés à la position du caractère. Les attributs (style, espacements…) relèvent du
module suivant.

## Entrée

- `ResultatSegmentation` : le `Document` segmenté, la granularité (`blocs` | `fine`) et
  `boites()`. Chaque `Boite` désigne son élément (`element_index`) et, en granularité
  `fine`, sa ligne (`ligne_index`).
- Les zones PaddleX de chaque page (`Page.zones_layout` : étiquette brute, rôle, confiance,
  bbox), conservées par la segmentation.
- Le PDF source (taille et rotation des pages).
- Le référentiel : seul vocabulaire autorisé en sortie.

## Sortie

`ResultatIdentification` :

- `segmentation` : le résultat reçu, transmis tel quel au module suivant ;
- `elements` : un `ElementIdentifie` par bbox — `id`, lien vers l'élément segmenté
  (`element_index`, `ligne_index`), `page_index`, `bbox` `[x, y, largeur, hauteur]` en points
  (origine en haut à gauche), `type`, `famille`, `statut` (`identifie` | `ambigu` |
  `non_identifie`), `confiance` (0..1), `alternatives` `[(type, score)]`, `indices` ;
- `expressions` : un `ExpressionIdentifiee` par expression dans un texte — élément porteur,
  `debut`, `fin` (indices de caractères dans le texte de l'élément, lignes jointes par `\n`,
  comme dans le catalogue), `type`, `famille`, `texte`, `confiance`.

Fichiers : un catalogue JSON (`pdfexact.identification/1`, tout champ présent, `null` si non
établi) et un PDF annoté où chaque bbox porte son type, avec une couleur par famille.

## Algorithme

Pour chaque bbox, des **règles indépendantes** proposent des candidats `(type, score, indice)` :

1. **Zone PaddleX** recouvrant l'élément (recouvrement ≥ 50 % de l'élément) : l'étiquette
   brute est traduite en type ; le score part de la confiance de la zone.
2. **Rôle sémantique** déjà posé par la segmentation sur l'élément.
3. **Nature de l'objet** : tableau, lien (externe → `lien`, interne → `renvoi`), image,
   forme.
4. **Géométrie** : filet fin → `separateur` ; aplat sous du texte → `bandeau` ; contour
   couvrant la page → `bordure_page` ; image couvrant la page → `page_numerisee` (porte du
   texte) ou `arriere_plan` ; petite image → `icone` ; bande haute ou basse de la page →
   `en_tete` / `pied_de_page`.
5. **Contenu du texte** : numéro de page, légende (« Figure 3 », « Table 2 »), marqueur de
   liste, code (police à chasse fixe), taille de police nettement supérieure au corps de la
   page (intertitre, titre du document sur la première page).

Les scores d'un même type s'additionnent par combinaison probabiliste
`1 - Π(1 - s)`. Le type retenu est celui de score maximal. Statut : `identifie` si le score
atteint 0,6 et dépasse le second d'au moins 0,15 ; `ambigu` sinon ; `non_identifie` sans
candidat, avec le type de repli `inconnu` (ou `image_generique` quand seule la famille image
est établie). Aucun type hors référentiel ne peut sortir : chaque règle est vérifiée contre
la liste fermée au chargement.

En granularité `fine`, une ligne hérite du type de son élément (indice « ligne de … »).

Expressions : expressions régulières sur le texte de chaque élément textuel (URL, e-mail,
DOI/ISBN → `identifiant`, date, grandeur avec unité ou pourcentage, acronyme hors texte tout
en capitales) ; appel de note : segment numérique en exposant (taille ≤ 75 % du corps de sa
ligne, ligne de base relevée). Les recouvrements entre expressions sont résolus en gardant la
plus longue.

## Limites assumées

Distinguer photo, logo, illustration, signature ou diagramme demande un modèle de vision,
absent : ces images restent `image_generique` sauf zone PaddleX (`chart`, `seal`…) ou règle
géométrique décisive.

## Plan

1. Segmentation : conserver `Page.zones_layout` ; `Boite` porte `element_index` et
   `ligne_index` (ajouts, sans changement de résultat ; références verrouillées inchangées).
2. `pdfexact/identification/referentiel.py` : chargement et contrôle de la liste fermée.
3. `regles.py` : candidats par règle, combinaison, statut.
4. `expressions.py` : expressions et appels de note.
5. `pipeline.py` : `identifier()`, `ResultatIdentification`, `enregistrer_identification()`.
6. `rendu.py` : PDF annoté par type et famille.
7. Lanceur : identification après la segmentation, catalogue `.identification.json` et PDF
   `_types.pdf`.
8. Tests unitaires par règle, test réel sur les PDF de référence, relecture ECC.
