# Segmentation visuelle Codex et audit des bboxes

Source : page 1 de `0c6daef79b7165c1_000744.pdf`.
Repere visible : 792 x 612 pt, paysage. Le PDF porte une rotation native de 90 degres.

## Reference demandee

- [x] Inspecter directement le rendu du PDF original.
- [x] Definir 10 objets de premier plan : 2 blocs texte, 2 logos, 6 illustrations.
- [x] Identifier separement les deux couches de fond.
- [x] Produire un PDF numerote avec une legende et une image de controle.
- [x] Enregistrer les limites visuelles estimees en JSON.
- [x] Garder cette reference independante des decisions de production.

Les cadres blancs des illustrations appartiennent a leur illustration. Les lignes
decoratives appartiennent aux couches graphiques. Le texte extrait `A-1` ne se lit
pas dans le rendu original et n'est pas un objet textuel visible de cette reference.

Les bboxes de reference sont estimees par inspection visuelle de Codex. Elles ne
sont ni une sortie PaddleX ni une preuve de segmentation automatique correcte.

Artefacts :

- [PDF Codex, segmentation puis legende](../results/0c6daef79b7165c1_000744_segmentation_codex.pdf)
- [Apercu de la segmentation](../results/0c6daef79b7165c1_000744_segmentation_codex.png)
- [Coordonnees de reference](benchmarks/segmentation_codex_page1.json)
- [PDF automatique apres correction du dessin](../results/0c6daef79b7165c1_000744_bboxes_repere_corrige.pdf)

## Causes confirmees

1. `pdfexact/render/bbox_debug.py:149`, `annotate_pdf_bboxes()` : les bboxes
   visibles etaient ecrites directement dans le repere natif non tourne de
   PyMuPDF. Le lecteur PDF appliquait ensuite la rotation de page. Cela explique
   les cadres verticaux et ceux qui sortaient de la page dans la capture.
   Correction appliquee aux rectangles et aux contours de paragraphes : passage
   inverse par `PageGeometry`, ecriture temporaire en rotation zero pour respecter
   aussi les CropBox decalees, restauration de l'etat original avant sauvegarde.
   Le contour du paragraphe est ferme.
2. `pdfexact/extract/images.py:143` : un score de recherche visuelle >= 0.35 suffit
   a remplacer la bbox PDF, sans preuve que le placement source etait errone.
   Mesure du bandeau : placement natif visible `(36, 36, 756, 130.14)` ; sortie
   automatique environ `(25.23, 0, 792, 135.21)`. Cette deformation precede le
   dessin du diagnostic. Sa correction reste a realiser.
3. `pdfexact/extract/images.py:100` : l'ordre de parcours est celui des XRef tries.
   Les images produites ne transportent pas l'ordre de peinture PDF. Le journal
   `get_bboxlog()` montre un ancien logo, un texte `A-1` et un insigne peints avant
   les grands fonds qui les recouvrent. Leur presence dans le PDF ne prouve pas
   leur visibilite finale. La gestion de l'occlusion reste a corriger.
4. `pdfexact/layout/ai.py` et `pdfexact/layout/understanding.py` : le run CPU
   PaddleX est bien execute, mais retourne 3 macro-zones. Cela ne constitue pas
   une segmentation fine des 10 objets visibles. Les 1201 occurrences bitmap
   retournees par PyMuPDF incluent des fragments ; elles ne sont pas 1201 objets
   semantiques. Le pipeline produit 21 elements IR, avec des cadres vectoriels,
   des fonds et un texte masque. La correspondance objets visibles/IR reste a valider.

Le nombre de cadres de diagnostic ne doit pas etre reduit artificiellement pour
faire croire a une meilleure segmentation. Le diagnostic garde les objets IR
disponibles pour l'audit. La reference Codex expose les unites visibles attendues.

## Validation realisee

- [x] 16 cas de regression : rotations 0/90/180/270, CropBox complete/decalee,
  rectangles/contours de paragraphes. Verification geometrique et pixels du rendu.
- [x] 43 tests cibles passes, 2 avertissements de dependances.
- [x] Relance reelle CPU : `layout_ai_detected, zones=3` ; 21 cadres IR.
- [x] Verification visuelle du PDF de reference et du PDF automatique corrige.
- [ ] Correction de l'usage de la recherche visuelle des placements.
- [ ] Prise en compte de l'ordre de peinture, des masques et de l'occlusion.
- [ ] Segmentation automatique des objets inclus dans les grands fonds bitmap.
- [ ] Validation visuelle finale du DOCX.

La correction validee ici concerne l'ecriture des cadres PDF. Elle ne certifie
pas encore la reconstruction DOCX ni l'ensemble de la segmentation automatique.
