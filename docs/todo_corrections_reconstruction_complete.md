# Todo complet - reconstruction PDF vers DOCX native

Ce fichier est le registre d'execution. Une case n'est cochee qu'apres la
modification correspondante et une verification reproductible.

## 0. Cadre de travail et inventaire

- [x] Confirmer le chemin CLI actif et le script d'orchestration utilise.
- [x] Confirmer les fichiers intermediaires produits par l'orchestrateur.
- [x] Cartographier le passage PDF -> extraction -> IR -> scene -> plan -> DOCX.
- [x] Identifier les chemins historiques encore appeles par le CLI.
- [x] Verifier les changements deja presents dans le depot et ne rien ecraser.
- [x] Definir les invariants de la reconstruction finale.
- [x] Ajouter dans les diagnostics le chemin de rendu effectivement utilise.

## 1. Repere canonique de page

- [x] Formaliser le repere page affichee `(0, 0, largeur, hauteur)`.
- [x] Formaliser la source de verite des dimensions effectives de page.
- [x] Distinguer dimensions physiques, CropBox, MediaBox et rotation PDF.
- [x] Classer A4/A3/A5 comme metadata sans modifier l'echelle source.
- [x] Verifier portrait/paysage sur les dimensions effectives affichees.
- [x] Completer `PageGeometry` avec un contrat explicite de repere.
- [ ] Ajouter la validation des limites de page pour chaque bbox.
- [ ] Interdire les conversions implicites native/affichee dans les chemins actifs.
- [ ] Auditer tous les extracteurs qui acceptent `geometrie=None`.
- [ ] Auditer tous les appels de rasterisation qui oublient `geometrie`.
- [ ] Ajouter des tests rotation 0/90/180/270 avec CropBox.
- [ ] Ajouter des tests de dimensions portrait et paysage.

## 2. Extraction geometrique de tous les elements

- [ ] Auditer les textes natifs, glyphes, OCR, liens et tableaux.
- [ ] Auditer les formes vectorielles et leurs chemins transformes.
- [ ] Auditer les images bitmap et images inline.
- [ ] Auditer les images rasterisees et les tuiles segmentees.
- [ ] Auditer les shadings et fonds synthetiques.
- [ ] Conserver la geometrie complete avant reduction en bbox.
- [ ] Conserver quadrilateres, polygones, angles et matrices utiles.
- [ ] Convertir chaque geometrie une seule fois vers le repere canonique.
- [ ] Ajouter une validation geometrie IR -> page.
- [ ] Ajouter un diagnostic de double transformation.
- [ ] Ajouter un test de concordance avec le rendu PDF pour chaque categorie.

## 3. Images, matrices PDF et placements complexes

- [ ] Corriger l'extraction des images placees par matrice PDF complexe.
- [ ] Exploiter la matrice complete de placement et non une bbox seule.
- [ ] Gerer les images placees dans des XObjects.
- [ ] Gerer rotations, inversions et recadrages internes.
- [ ] Gerer les images reutilisees plusieurs fois avec des placements differents.
- [ ] Distinguer ressource media et placement media.
- [ ] Conserver un identifiant de placement pour chaque `ImageEl`.
- [ ] Verifier le logo Orbital du PDF PowerPoint de regression.
- [ ] Verifier le fond principal et toutes les images de la colonne droite.
- [ ] Ajouter un test de matrice non triviale.
- [ ] Ajouter un test d'image reutilisee a plusieurs positions.
- [ ] Ajouter un audit image source -> bbox IR -> ancre DOCX.
- [x] Distinguer les placements techniques contigus des objets visuels finaux.
- [x] Composer les bandes bitmap qui partagent un axe, une echelle et une proximite compatibles.
- [x] Refuser la composition lorsqu'elle absorberait un fond ou une couche pleine page.
- [x] Conserver les identifiants de placements et XRef dans la provenance du composite.
- [x] Faire passer les composites par le meme RenderPlan que les images natives.
- [x] Verifier la composition sur un PDF PowerPoint avec trois series de bandes et deux bandes accolées.

## 4. Transparence, alpha, fonds et inpainting

- [ ] Verifier que les bboxes de diagnostic sont absentes du DOCX final.
- [ ] Verifier que les images ne recoivent aucun remplissage XML.
- [x] Preserver le canal alpha des medias extraits.
- [ ] Distinguer fond de page et objet visuel independant.
- [ ] Detecter les fonds blancs integres aux logos et objets.
- [ ] Ne pas supprimer les blancs faisant partie du contenu original.
- [ ] Auditer `rasteriser_region_sans_texte` et ses formats de sortie.
- [ ] Auditer `nettoyer_images_fond_texte_positionne`.
- [ ] Auditer les masques d'inpainting dans le repere canonique.
- [ ] Comparer l'inpainting local avec le modele VYSI disponible.
- [ ] Eviter tout inpainting plein-page destructif.
- [x] Ajouter des tests alpha et fond transparent.
- [ ] Ajouter une validation de l'absence de rectangle blanc artificiel.

## 5. Segmentation semantique des paragraphes

- [ ] Auditer la creation des unites de lignes.
- [ ] Auditer la fusion des lignes en paragraphes.
- [ ] Auditer la separation des colonnes.
- [ ] Auditer les pieds de page multi-elements.
- [ ] Auditer titres, sous-titres, labels et captions.
- [ ] Auditer lettrines et zones d'exclusion.
- [ ] Utiliser l'IA pour determiner le nombre d'elements semantiques.
- [ ] Conserver la validation geometrique apres decision IA.
- [ ] Interdire les fusions qui franchissent une colonne.
- [ ] Interdire les fusions qui franchissent une bbox visuelle adjacente.
- [ ] Construire chaque bbox de paragraphe depuis les bords exterieurs de ses lignes.
- [ ] Conserver `line_bboxes` et `exclusion_bboxes` dans l'IR.
- [ ] Regrouper les lignes sous un paragraphe Word unique.
- [ ] Ajouter les tests footer avec deux, trois et plusieurs elements.
- [x] Executer le passage layout IA avant toute segmentation, quel que soit le moteur texte.
- [x] Attacher les zones IA aux lignes natives du mode `spans` sans rasteriser le texte.
- [x] Conserver le repli geometrique avec avertissement explicite lorsque le moteur IA echoue.

## 6. Composition, reflow et bboxes paragraphes

- [ ] Distinguer vrai retour semantique et retour de ligne visuel.
- [ ] Distinguer fin de colonne et fin de paragraphe.
- [ ] Mesurer chaque ligne avec la police et la taille reelles.
- [ ] Calculer la largeur Word necessaire avant composition.
- [ ] Calculer l'interligne depuis les metriques reelles.
- [ ] Preserver les retours intentionnels des titres et labels.
- [ ] Autoriser le reflow naturel des paragraphes de prose.
- [ ] Utiliser les retraits de lignes comme contraintes de composition.
- [ ] Ajuster les bboxes dans l'espace libre uniquement.
- [ ] Bloquer toute extension qui recouvre une bbox adjacente.
- [ ] Verifier les collisions apres chaque ajustement.
- [ ] Appliquer la logique a tous les paragraphes, pas seulement aux mono-lignes.
- [ ] Ajouter des tests de texte long, titre, colonne et paragraphes adjacents.

## 7. Texte Word natif et styles

- [ ] Garantir qu'un texte reconnu n'est jamais rasterise.
- [ ] Conserver chaque span comme run Word natif.
- [ ] Preserver famille de police et variante exacte.
- [ ] Preserver taille en points.
- [ ] Preserver couleur, alpha et contraste sur fond.
- [ ] Preserver gras, italique, souligne et barre.
- [ ] Preserver capitales, exposant, indice et surlignage.
- [ ] Preserver espacement de caracteres et interligne.
- [ ] Preserver angle et orientation des textes speciaux.
- [ ] Traiter textes vectoriels, dessines et calligraphiques comme texte editable.
- [ ] Interdire les fallbacks silencieux vers Arial/Calibri.
- [ ] Diagnostiquer les polices introuvables ou non representables.
- [ ] Verifier le XML `w:rPr` pour chaque run.
- [ ] Ajouter des tests de styles multi-runs.

## 8. Unification du renderer et de l'orchestrateur

- [x] Faire utiliser au CLI une seule scene en memoire.
- [x] Faire utiliser au CLI un seul repere canonique.
- [x] Construire un seul `RenderPlan` pour tous les sorties.
- [x] Faire valider tous les elements par `native_contract`.
- [ ] Supprimer les decisions concurrentes du renderer historique.
- [ ] Remplacer les insertions XML par decoupage textuel fragiles.
- [ ] Produire le DOCX vierge depuis le plan canonique.
- [ ] Inserer les visuels depuis le meme plan.
- [ ] Inserer les textes natifs depuis le meme plan.
- [ ] Conserver les fichiers intermediaires uniquement comme artefacts de controle.
- [ ] Ajouter dans le rapport les comptes par type et par strategie de rendu.
- [ ] Ajouter un mode d'echec explicite si un element n'a pas de bbox canonique.
- [x] Rendre l'analyse layout obligatoire dans l'orchestrateur CLI et dans `extraire`.
- [x] Conserver `--no-layout-ai` uniquement comme compatibilite de parsing, sans desactiver le contrat universel.

## 9. XML DOCX et dimensions de page

- [ ] Verifier largeur/hauteur DOCX contre le repere canonique.
- [ ] Verifier orientation Word contre les dimensions effectives.
- [ ] Verifier les marges et l'origine des ancres.
- [ ] Verifier `relativeFrom=page` pour les objets flottants.
- [ ] Verifier absence de remplissage et de contour des cadres finaux.
- [ ] Verifier ordre de superposition fond -> formes -> images -> textes.
- [ ] Verifier absence de clipping des paragraphes.
- [ ] Verifier compatibilite LibreOffice et Word.
- [ ] Ajouter un audit XML des positions et dimensions.

## 10. Validation et benchmark

- [x] Executer la suite unitaire avant correction.
- [x] Conserver le resultat de reference.
- [ ] Ajouter les fixtures de regression portrait et paysage.
- [ ] Ajouter le PDF PowerPoint de regression.
- [ ] Ajouter des tests PDF A4/A3/A5.
- [x] Produire PDF annote, DOCX bbox, DOCX non-textes et DOCX final.
- [ ] Rendre le DOCX final en PDF avec LibreOffice.
- [ ] Comparer positions, dimensions et superposition avec le PDF source.
- [ ] Verifier que les textes restent selectionnables et editables.
- [ ] Verifier l'absence de texte duplique ou aplati.
- [ ] Executer la suite complete.
- [ ] Cocher uniquement les taches validees.
- [ ] Documenter les limites restantes, s'il en existe.

### Verification du 2026-10-09 - layout universel obligatoire

- [x] Corriger `pdfexact/extract/document.py` pour analyser chaque page avant les
  branches `spans`, `glyphs` et OCR.
- [x] Corriger `scripts/reconstruct_bbox_native.py` pour utiliser le contrat
  obligatoire, independamment de l'ancien drapeau CLI.
- [x] Corriger `pdfexact/cli.py` pour transmettre toujours `layout_ai=True`.
- [x] Corriger `_attacher_frames_texte()` afin qu'une zone IA soit exploitee meme
  lorsqu'il n'existe pas encore de plan OCR classique.
- [x] Ajouter les tests d'attachement de frames et d'integration `spans`.
- [x] Produire le meme plan de comprehension de page pour `spans`/`glyphs` et OCR.
- [x] Validation cible : `36 passed, 2 warnings`.
- [x] Ajouter la dispatch multi-fournisseurs et les tests de disponibilite locale.
- [x] Executer le benchmark de regression PowerPoint avec les nouveaux cadres de layout.
- [x] Rejouer la suite non visuelle apres le branchement universel : `386 passed, 1 skipped, 3 warnings`.

### Verification du 2026-10-10 - reference visuelle Codex et diagnostic tourne

- [x] Segmenter visuellement la page originale avec Codex : 10 objets et 2 fonds.
- [x] Produire le PDF numerote, sa legende, son apercu et le JSON des coordonnees.
- [x] Reproduire l'erreur de dessin des bboxes dans le mauvais repere PDF.
- [x] Convertir rectangles et contours du repere visible vers le repere d'ecriture.
- [x] Restaurer rotation et CropBox originales apres ajout des cadres.
- [x] Fermer les contours de paragraphes dans le PDF de diagnostic.
- [x] Verifier les 4 rotations, avec et sans CropBox decalee, sur le rendu pixel.
- [x] Executer les tests cibles : 43 passes, 2 avertissements.
- [x] Regenerer et inspecter le PDF automatique apres correction de repere.
- [x] Documenter la difference entre macro-zones IA, primitives IR et objets visibles.
- [ ] Corriger le remplacement d'une bbox PDF exacte par une recherche visuelle approximative.
- [ ] Transporter et respecter l'ordre reel de peinture PDF pour les images.
- [ ] Identifier les objets entierement recouverts, y compris les textes masques.
- [ ] Segmenter les objets visibles inclus dans les fonds bitmap sans les dupliquer.
- [ ] Comparer la segmentation automatique a la reference visuelle independante.

Details et preuves : `docs/audit_segmentation_codex_2026-10-10.md`.

### Verification du 2026-10-10 - plantage OpenCV sur les gabarits chromatiques

- [x] Reproduire l'assertion `cv2.matchTemplate()` sur la page 1 de
  `96a80f28f8366209_000751.pdf` : image source 382 x 426 px, page rendue 1056 x 566 px.
- [x] Identifier l'absence de controle de dimensions dans
  `pdfexact/extract/image_placement.py::_template_bbox_from_chroma()`.
- [x] Ecarter les echelles dont la largeur OU la hauteur depasse celle de la cible,
  avant redimensionnement et comparaison OpenCV.
- [x] Conserver le resultat `None` si aucune echelle ne convient ; l'extracteur
  conserve alors sa bbox PDF. Aucun traitement propre au document n'est ajoute.
- [x] Ajouter quatre regressions : depassement vertical, horizontal, taille limite
  et aucune echelle admissible. Les quatre echouent avant correction et passent apres.
- [x] Executer les tests images/geometrie : 78 passes.
- [x] Relancer la commande utilisateur en CPU : 49 zones IA, code de sortie 0.
- [x] Generer `results/96a80f28f8366209_000751_bboxes_orchestrated.pdf` et
  `results/96a80f28f8366209_000751_bbox_native_orchestrated.docx`.

Cette verification valide la correction du plantage. Elle ne certifie pas la
segmentation semantique complete ni la fidelite visuelle du DOCX.

## 11. Definition de fini

- [ ] Toute page utilise un seul repere canonique.
- [ ] Tout element est extrait et positionne dans ce repere.
- [ ] Toute bbox finale est transparente.
- [ ] Toute image conserve sa position, sa taille et sa transparence.
- [ ] Tout texte reconnu est Word natif et editable.
- [ ] Toute police, taille, couleur et style sont conserves.
- [ ] Tous les paragraphes sont semantiquement regroupes.
- [ ] Les retours a la ligne sont intelligents et non destructifs.
- [ ] Aucune bbox adjacente n'est detruite par un ajustement.
- [ ] Le DOCX final respecte les dimensions et l'orientation du PDF.
- [ ] Le benchmark de regression est valide.

### Reference avant corrections

- Suite pytest : 385 tests passes, 1 test ignore.
- Le test visuel LibreOffice a ete bloque par l'environnement (dconf en lecture seule), sans echec fonctionnel du code Python.

### Verification intermediaire apres les corrections en cours

- Suite pytest : 386 tests passes, 1 test ignore ; le test visuel LibreOffice reste bloque par `dconf` en lecture seule.
- Tests cibles extraction/geometrie/rendu/alpha : 79 tests passes.
- Execution CLI paysage de regression : terminee ; aucun traitement special au fichier, au logo ou au XRef n'a ete ajoute.
- Composition generique des placements bitmap : 18 placements sources ramenes a 10 objets visuels sur le PDF PowerPoint de regression ; aucune regle ne reference le document, le logo ou un XRef particulier.
- Tests apres composition : 50 tests cibles passes ; `git diff --check` propre.

### Verification ciblee du 2026-10-10 - frontieres, contours et routage des sections

Cette section ajoute les preuves du chantier cible sans cocher les anciens
items globaux de ce registre. Elle ne certifie ni la segmentation universelle,
ni les styles complets, ni la fidelite visuelle finale. Mise a jour documentaire
uniquement ; aucun correctif de code n'est apporte pendant l'audit.

- [x] Integration non visuelle rapportee : `554 passed, 1 skipped, 0 failed`.
- [x] Tests cibles bbox, contours et routage : `59 passed`.
- [x] Regenerer le cas trois pages avec layout PaddleX CPU : 9/18/17 zones.
- [x] Conserver 13/40/43 lignes visibles et 142 segments source/catalogue :
  texte/couleur/gras/italique identiques, taille identique au centieme de point.
- [x] Verifier 51 paragraphes natifs dans trois sections : 11/15/25.
- [x] Corriger le routage qui inserait les textes apres le paragraphe terminant
  la section (`w:pPr/w:sectPr`) et les attribuait a la page suivante. Les textes
  sont maintenant inseres avant cette limite et avant le `w:sectPr` final.
- [x] Tester bbox -> non-textes -> texte natif sur plusieurs pages, avec pages
  sans texte, signets et paragraphes XML imbriques, sans regle propre au corpus.
- [x] Verifier la regression portrait `0fd83d...`, page 1 : 4 elements texte,
  612 x 792 pt, XML DOCX 12240 x 15840 twips.
- [x] Verifier la regression NASA `0c6...`, page 1 : 3 elements texte,
  792 x 612 pt affiches, rotation PDF 90 deg conservee au catalogue et XML DOCX
  paysage 15840 x 12240 twips.
- [x] Verifier le cas trois pages : 612 x 792 pt et 12240 x 15840 twips par page.
- [x] Tester les contrats de comprehension textuelle avec un fournisseur factice.
- [x] Emettre un avertissement explicite et utiliser le repli si le modele de
  comprehension textuelle est absent ; HTTP seul ne prouve pas un modele installe.
- [ ] Executer une inference de comprehension textuelle avec un vrai modele.
- [x] Recevoir le rapport final de Carson : trois pages LibreOffice correctement
  attribuees, sans omission non blanche ni texte melange entre pages.
- [x] Verifier Budget : 4 lignes, 3 `w:br`, 1 paragraphe Word ; Partners :
  5 lignes, 4 `w:br`, 1 paragraphe Word ; lignes conservees dans le PDF LibreOffice.
- [x] Mettre a jour les six apercus a 144 dpi, 1224 x 1584 pixels, tous non vides.
- [x] Corriger les findings de l'audit : changement de vrai cadre IA dans un
  meme bloc, frontieres validees sur page mixte, obstacle entre fragments de
  meme ligne et orientation explicite portee seulement par le bloc source.
- [x] Aligner la docstring de segmentation sur la consultation par bloc source
  et la continuite interblocs prouvee, sans annoncer une IA globale de page.

La suite complete n'a pas ete relancee pendant cette passe documentaire. La
lecture seule des catalogues et du XML confirme les comptes de lignes, les
comptes de paragraphes par section et les dimensions ci-dessus. Le layout CPU
a bien ete execute ; les fournisseurs factices ne prouvent aucune inference
textuelle reelle. Les `line:N` sont locaux a leur page (`page_index`). Les
contours sont reserves aux diagnostics, pas a une reconstruction Word en bandes.

Commandes de test de reference, depuis la racine du depot, a rejouer hors des
integrations concurrentes :

```bash
PYTHONDONTWRITEBYTECODE=1 .converter/bin/python -m pytest -q -p no:cacheprovider \
  tests/render/test_bbox_debug.py \
  tests/render/test_paragraph_contours.py \
  tests/render/test_native_paragraph_pages.py

PYTHONDONTWRITEBYTECODE=1 .converter/bin/python -m pytest -q -p no:cacheprovider \
  --ignore=tests/visual
```

Commandes de regeneration CPU et d'export LibreOffice, limites et findings
detaillees : [checklist frontieres](todo_frontieres_paragraphes.md#10-commandes-de-reproduction).

Artefacts du cas trois pages : [PDF bbox](../results/dc738585d318b299_000019_bboxes_frontieres_corrigees.pdf),
[DOCX final](../results/dc738585d318b299_000019_native_frontieres_corrigees.docx),
[catalogue](../results/dc738585d318b299_000019_native_frontieres_corrigees.extraction.json),
[bbox seul](../results/dc738585d318b299_000019_native_frontieres_corrigees.bboxes.docx)
et [non-textes](../results/dc738585d318b299_000019_native_frontieres_corrigees.non_text.docx).

Regressions, page 1 seulement : portrait
[PDF bbox](../results/0fd83d2aa11747d4_000152_bboxes_frontieres_corrigees.pdf),
[DOCX](../results/0fd83d2aa11747d4_000152_native_frontieres_corrigees.docx),
[catalogue](../results/0fd83d2aa11747d4_000152_native_frontieres_corrigees.extraction.json) ; NASA
[PDF bbox](../results/0c6daef79b7165c1_000744_bboxes_frontieres_corrigees.pdf),
[DOCX](../results/0c6daef79b7165c1_000744_native_frontieres_corrigees.docx),
[catalogue](../results/0c6daef79b7165c1_000744_native_frontieres_corrigees.extraction.json).

LibreOffice, derniere validation terminee selon le
[rapport final de Carson](../results/verification_frontieres/validation_frontieres.json) :
[PDF](../results/verification_frontieres/dc738585d318b299_000019_native_frontieres_corrigees.pdf),
[apercu 1](../results/verification_frontieres/docx_page1.png),
[apercu 2](../results/verification_frontieres/docx_page2.png),
[apercu 3](../results/verification_frontieres/docx_page3.png).

Le rapport detaille les 96 lignes (13/40/43), les 51 paragraphes (11/15/25),
les 142 segments (15/60/67) et les empreintes SHA-256 des artefacts. Les styles
source/catalogue sont verifies sur texte/couleur/gras/italique et taille au
centieme. Deux valeurs flottantes de la page 1 different de leur serialisation
de moins de `1e-6` pt : ne pas annoncer une egalite brute des flottants.

Limites maintenues : Word/LibreOffice recompose legerement les retours souples
de prose, sans promesse pixel-identique. Les tailles XML Word sont en demi-points
(19.98/7.98 pt deviennent 20/8 pt), certaines tailles sont reajustees au rendu
LibreOffice et une substitution de police de puces est observee. L'identite
stricte des styles rendus n'est donc pas prouvee. Le modele semantique reste
absent, avec un avertissement explicite unique et repli. Aucun ancien item global
de fidelite, styles ou IA reelle n'est coche par ces validations ciblees.

### Correctifs cibles P1/P2 du 2026-10-10 - regressions RED -> GREEN

Autorisation explicite limitee a `analysis/text_segmentation.py`,
`render/reflow.py` et `tests/analysis/test_paragraph_segmentation.py`, puis mise
a jour des deux checklists. Aucun autre module ni artefact de corpus modifie.

- [x] Separer les groupes independants de cadres non vides distincts, y compris
  sur une meme ligne et contre une decision IA. Les labels A/A/B/B deviennent
  deux paragraphes ; A/None/B independants restent separes, tandis que les
  lignes non attachees et la lettrine temoin sont conservees.
- [x] Distinguer la provenance locale `inferred:` de `_attacher_frames_texte` :
  ignorer uniquement ce prefixe pour la frontiere stricte, sans oublier le
  dernier vrai cadre. A/inferred/A -> 1, A/inferred/B independants -> 2,
  inferred1/inferred2 continu -> 1 ; roles de titre, styles, gaps et obstacles
  restent proteges.
- [x] Preserver les noeuds deja valides et leur provenance dans l'appel public,
  ses repetitions et la preparation du document. Reserver leurs IDs et bloquer
  les fusions qui traversent un voisin valide, sans bloquer une autre colonne.
- [x] Tester la non-modification par comparaison profonde des styles, geometries,
  coordonnees, source IDs, paragraph IDs et metadata des noeuds valides.
- [x] Controler le corridor entre fragments d'une meme ligne avant le retour
  anticipe, sans assimiler les fonds ou images hors corridor a une separation.
- [x] Appliquer le repli d'orientation bloc -> copie de ligne seulement en
  l'absence d'indices directionnels propres ; conserver angles, courbes,
  baselines et quads explicites, et tracer la provenance du repli.
- [x] Corriger la docstring : comprehension par bloc source, puis fusion
  interblocs seulement si continuite prouvee. Pas de reconstruction en bandes.
- [x] RED : 23 echecs reproduits avant correction, avec temoins positifs.
- [x] GREEN segmentation : `60 passed, 4 warnings` (39 nouveaux cas, 21 precedents).
- [x] GREEN cible elargie : `328 passed, 1 skipped, 6 warnings`.
- [x] Precision de provenance inferree : huit controles supplementaires rouges
  avant correction, puis `68 passed, 4 warnings` en segmentation et
  `341 passed, 1 skipped, 6 warnings` avec les attachements de frames et les
  autres contrats/rendus cibles.
- [x] Dernier correctif general : autoriser la prose prouvee continue entre
  cadres reels, y compris via None/inferred et entre deux blocs source d'une
  ligne. Reutiliser les helpers semantiques existants, apres les gardes de
  geometrie, blanc, liste, obstacle et voisin valide ; garder les contraintes
  de proprietaire source, frontiere explicite, style et validation.
- [x] Continuite intercadres RED -> GREEN : huit echecs avant correction,
  `108 passed, 4 warnings` apres ; verification ciblee elargie
  `381 passed, 1 skipped, 6 warnings`. Labels courts et fins de phrase restent
  separes. Aucun nombre fixe de paragraphes ni fusion de records independants
  n'est impose. Aucune regeneration ni suite complete pour ce dernier patch ;
  les rapports corpus/LO historiques restent anterieurs a ce correctif.
- [x] Limiter la preuve intercadres aux lignes successives (`not _same_row`) :
  deux colonnes au meme Y et gouttiere de 24 pt restent separees, dans un ou
  deux blocs et avec/sans IA. Les fragments d'un meme cadre gardent leur logique.
  RED : quatre echecs ; GREEN : `173 passed, 6 warnings`
  (114 segmentation + 59 bbox/contours/routage), sans regeneration.
- [x] Normaliser le conteneur apres fusion multi-cadres dans la segmentation
  et le reflow legacy : ID de cadre nul, bbox de cadre egale a la bbox union du
  paragraphe, role/strategie communs conserves. Cadres des lignes, provenance,
  styles, coordonnees et sources inchanges ; aucun changement mono-cadre.
  RED : quatre echecs multi-cadres, avec quatre temoins mono-cadre verts.
  GREEN : huit cas, dont le second cadre plus large et le verrouillage du plan
  natif sans perte de largeur ; `122 passed, 4 warnings` en segmentation,
  `395 passed, 1 skipped, 6 warnings` sur les contrats/rendus cibles.
- [x] Carson : suite complete et regeneration/LibreOffice apres ce dernier patch :
  655 passes, 1 ignore, 7 avertissements ; preuves finales ci-dessous.

Commandes exactes et details : [checklist frontieres](todo_frontieres_paragraphes.md#10-commandes-de-reproduction).
La suite 554/59 et le rapport LibreOffice ci-dessus sont des preuves avant le
dernier patch. Ils ne sont pas annonces comme une nouvelle verification apres
patch ; aucun ancien item global non prouve n'est coche.

### Verification historique ciblee du 2026-10-10 a 14:47 UTC

Verification executee sur le code stabilise, sans modification de production
ni des tests de cette passe. Cette section conserve le resultat intermediaire
601/1 et le changement observe ; la verification finale ci-dessous la remplace
pour les artefacts actuels, sans cocher les anciens items globaux.

- [x] Suite complete non visuelle : `601 passed, 1 skipped, 7 warnings`,
  0 echec, 61.63 s. Commande exacte :
  `.converter/bin/python -m pytest -q --ignore=tests/capture_ecran --ignore=tests/visual --tb=short`.
- [x] `git diff --check` propre avant regeneration et apres documentation.
- [x] Regenerer les trois cas avec PaddleX CPU, `PP-DocLayout_plus-L`, mode
  `spans`, 100 dpi, sans anciens drapeaux IA/comprehension : trois codes 0,
  zones layout 9/18/17 pour le cas trois pages, 5 pour portrait et 3 pour NASA.
- [x] Verifier portrait page 1 : 4 elements texte, 6 lignes, 6 segments ;
  texte ordonne inchange hors blancs, styles source/catalogue au centieme,
  612 x 792 pt et XML 12240 x 15840 twips.
- [x] Verifier NASA page 1 : 3 elements texte, 6 lignes, 6 segments ;
  texte ordonne inchange hors blancs, styles source/catalogue au centieme,
  792 x 612 pt affiches, rotation 90 deg et XML 15840 x 12240 twips.
- [x] Verifier trois pages : 96 lignes (13/40/43), 142 segments (15/60/67),
  texte/couleur/gras/italique exacts source/catalogue, tailles au centieme.
- [x] Export LibreOffice avec escalation : code 0, trois pages, texte ordonne
  attribue a sa page sans omission non blanche, ni chevauchement de texte
  visible dans les trois apercus inspectes.
- [x] Actualiser les six apercus a 144 dpi, 1224 x 1584 pixels ; tous non vides
  et verifies contre le rendu du PDF final correspondant.
- [x] Actualiser le rapport JSON avec SHA-256, dates des 16 artefacts finaux
  et empreintes des 111 fichiers Python inchanges pendant la verification.
- [x] Consigner le changement observe : 51 paragraphes (11/15/25) deviennent
  **54 paragraphes (11/18/25)**, dans le catalogue et les sections DOCX.
- [x] Consigner Budget : quatre paragraphes sans `w:br`, chacun rattache
  a un vrai cadre IA distinct (10/11/12/13), au lieu du paragraphe avec trois
  retours precedent. L'arbitrage ulterieur confirme quatre records autonomes
  legitimes ; 51/Budget unique n'etait pas un contrat utilisateur.
- [x] Partners reste cinq lignes, quatre `w:br`, un paragraphe Word.
- [ ] Prouver une inference semantique reelle : endpoint absent, un message
  explicite par analyse, repli geometrique/heuristique.
- [ ] Prouver une identite stricte des styles rendus ou des pixels : demi-points
  Word, ajustements de taille LO, substitution des puces et reflow subsistent.

Le premier rapport avait le statut `regression-observed` par comparaison a
51/Budget unique, attendu auto-impose par le main. L'arbitrage parent/Gibbs a
confirme que quatre records label/valeur autonomes peuvent former quatre
paragraphes natifs. L'historique 51 -> 54 reste explicite ; aucun quota ni nom
de corpus n'est force en production. Le statut final est consigne ci-dessous.

Preuves finales : [rapport JSON](../results/verification_frontieres/validation_frontieres.json),
[checklist ciblee](todo_frontieres_paragraphes.md#13-verification-apres-les-quatre-correctifs),
[PDF LO](../results/verification_frontieres/dc738585d318b299_000019_native_frontieres_corrigees.pdf),
[apercu page 2](../results/verification_frontieres/docx_page2.png),
[apercu page 3](../results/verification_frontieres/docx_page3.png).

### Verification finale du 2026-10-10 a 15:18 UTC - code multi-cadres stabilise

Contrat general retenu : preserver les enregistrements autonomes et la prose
prouvee continue, meme entre cadres, sous les gardes de style/role/geometrie,
sans imposer de nom ni de compte fixe. L'ancien attendu 51/Budget unique est
remplace avec justification, pas masque : observation initiale 51 (11/15/25),
observation finale acceptee **54 (11/18/25)**, quatre records Budget independants.

- [x] Suite complete non visuelle finale : `655 passed, 1 skipped, 7 warnings`,
  0 echec, 52.27 s ; inclut 122 tests de segmentation et 59 bbox/contours/routage.
  Commande : `.converter/bin/python -m pytest -q --ignore=tests/capture_ecran --ignore=tests/visual --tb=short`.
- [x] `git diff --check` propre avant regeneration et apres documentation.
- [x] Trois regenerations CPU sans flags historiques : codes 0 ; layout
  PaddleX `PP-DocLayout_plus-L`, zones 9/18/17, puis 5 portrait et 3 NASA.
- [x] Portrait/NASA page 1 : 4/3 elements texte, six lignes et six segments
  chacun ; texte inchange hors blancs, styles et positions de catalogue
  conserves, dimensions portrait/paysage et rotation NASA 90 deg conservees.
- [x] Trois pages : 96 lignes source/catalogue/LO, soit 13/40/43 ; 142 segments,
  soit 15/60/67. Texte/couleur/gras/italique exacts source/catalogue et tailles
  au centieme ; positions et styles des segments inchanges depuis la reference
  precedente, a la precision d'extraction existante.
- [x] Catalogue et XML : 54 paragraphes Word natifs editables, sections 11/18/25.
  Les blocs de prose de huit et neuf lignes restent chacun un `w:p` sans
  `w:br`, pas des bandes. Budget : quatre records label/valeur complets en
  quatre paragraphes legitimes ; Partners : cinq lignes, quatre retours, un paragraphe.
- [x] Export LO avec escalation : code 0, trois pages, texte complet attribue
  a sa page hors blancs ; aucun chevauchement de texte visible sur les trois
  apercus finaux inspectes.
- [x] Six apercus finaux a 144 dpi, 1224 x 1584 pixels, tous non vides et
  verifies contre le rendu de leur PDF final.
- [x] Rapport `validated-with-reviewed-segmentation-change`, SHA-256 et dates
  des 16 artefacts, empreintes des 111 fichiers Python inchanges pendant cette
  verification. Resultats intermediaires 601/1 et 647/1 conserves comme historiques.
- [ ] Inference semantique reelle : endpoint absent, un diagnostic explicite
  par analyse, repli geometrique/heuristique ; aucun modele CPU semantique revendique.
- [ ] Identite stricte des polices/tailles rendues ou pixels : demi-points Word,
  ajustements LO et substitution de puces connus ; tailles source/catalogue
  au centieme, pas egalite brute des flottants ni des bboxes PDF non quantifiees.

Preuves : [rapport final](../results/verification_frontieres/validation_frontieres.json),
[checklist](todo_frontieres_paragraphes.md#13-verification-apres-les-quatre-correctifs),
[DOCX final](../results/dc738585d318b299_000019_native_frontieres_corrigees.docx),
[PDF LO](../results/verification_frontieres/dc738585d318b299_000019_native_frontieres_corrigees.pdf).
Seuls les artefacts et ces deux notes ont ete actualises pendant cette passe ;
aucune modification de code, de test ni fonctionnalite supplementaire.
