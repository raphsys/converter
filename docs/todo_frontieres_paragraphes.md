# Correction generale des frontieres de paragraphes

Execution du 2026-10-10. Aucun nom de document, texte ou coordonnee de corpus
ne doit devenir une regle de production. Les cases sont cochees apres verification.
Les validations ci-dessous portent sur les cas testes, pas sur une garantie
universelle de segmentation ou de fidelite visuelle. Les quatre findings de
l'audit ont ensuite ete corriges sur autorisation explicite, avec regressions
synthetiques, puis la protection de prose continue et le correctif de largeur
apres fusion multi-cadres. Verification finale terminee le 2026-10-10 a
15:18 UTC : 655 tests passes et changement 51 -> 54 paragraphes revu et accepte.
Le nombre 51 et Budget en un seul paragraphe n'etaient pas des exigences
utilisateur. Le contrat general, les preuves et les limites sont en section 13.

## 1. Reproduction et contrat
- [x] Identifier les raccords venant des espaces, des regroupements et du contour.
- [x] Verifier les modifications existantes sans les annuler.
- [x] Ajouter les regressions synthetiques avant les corrections.
- [x] Distinguer region de layout, paragraphe valide, ligne et run.

## 2. Lignes visibles et geometrie
- [x] Exclure les lignes uniquement blanches de la geometrie visible.
- [x] Conserver leur information d'espacement et de separation.
- [x] Conserver les retraits, styles, orientations et espaces dans les vrais runs.
- [x] Propager le cadre propre a chaque ligne, sans heriter aveuglement du premier.

## 3. Segmentation et comprehension
- [x] Segmenter les blocs PDF contenant plusieurs paragraphes ou roles.
- [x] Utiliser interligne, blancs, retraits, styles et marqueurs de liste.
- [x] Tenir compte des images voisines et des regions de layout.
- [x] Transmettre a la comprehension les metadonnees geometriques et de style.
- [x] Valider les groupes IA : couverture, unicite, ordre et separateurs proteges.
- [x] Invoquer la comprehension independamment du drapeau historique optionnel.
- [x] Signaler moteur absent, erreur ou reponse invalide et poursuivre prudemment.
- [x] Ne pas assimiler un client HTTP a un modele semantique CPU installe.

## 4. Protection jusqu'au rendu
- [x] Attribuer un identifiant stable et une provenance aux paragraphes valides.
- [x] Preserver les identifiants lors des transformations et fusions autorisees.
- [x] Interdire une refusion fondee seulement sur une colonne commune.
- [x] Conserver les fusions de fragments dont la continuite est prouvee.
- [x] Preserver la prose prouvee continue et les enregistrements autonomes,
  sans quota fixe : observation finale 54 paragraphes, repartis 11/18/25.
- [x] Preserver aussi les paragraphes deja valides sur une page mixte contenant un bloc non valide.

## 5. Contours
- [x] Regrouper les fragments d'une meme ligne reelle.
- [x] Dessiner une enveloppe orthogonale sans diagonales artificielles.
- [x] Fermer separement les composantes disjointes.
- [x] Distinguer les vrais trous de remplissage des composantes independantes.
- [x] Conserver le repere canonique et les contours exclusifs aux diagnostics.

## 6. Validation
- [x] Executer les tests contours/routage : `59 passed`.
- [x] Executer la suite non visuelle finale : `655 passed, 1 skipped, 0 failed, 7 warnings`.
- [x] Regenerer les trois pages du PDF soumis avec layout PaddleX CPU : 9/18/17 zones.
- [x] Conserver 13/40/43 lignes visibles et 142 segments : texte/couleur/gras/italique
  identiques source/catalogue, taille identique au centieme de point.
- [x] Verifier la segmentation revue : 54 paragraphes natifs, soit 11/18/25,
  dont quatre enregistrements Budget autonomes, sans fractionner la prose.
- [x] Verifier les dimensions de page dans les catalogues et le XML DOCX.
- [x] Tester la page 1 du PDF portrait `0fd83d...` : 4 elements texte.
- [x] Tester la page 1 du PDF NASA `0c6...` : 3 elements texte, rotation source conservee dans le catalogue.
- [x] Inspecter les apercus des trois pages et le catalogue de paragraphes.
- [ ] Verifier positions de page, styles, runs et texte editable dans le DOCX.
- [x] Recevoir le rapport final de Carson : LibreOffice produit trois pages
  correctement attribuees, sans texte omis ou melange entre pages.
- [x] Documenter resultats, fichiers generes et limites restantes ci-dessous.

Les 59 tests cibles et l'ancienne suite 554/1 restent des references historiques.
La suite complete non visuelle finale a ete executee apres les correctifs :
655 passes, 1 ignore, 7 avertissements. La lecture des artefacts confirme les
comptes de lignes, les comptes de paragraphes par section et les dimensions.
Le [rapport final de Carson](../results/verification_frontieres/validation_frontieres.json)
consigne la derniere regeneration, le changement Budget accepte et la distinction entre
styles source/catalogue et rendu Word/LibreOffice : aucune identite stricte de
police ou taille rendue n'est revendiquee, ce qui laisse l'item global
styles/positions ouvert.

## 7. Sections et sauts de page

- [x] Reproduire le decalage : page 1 sans texte, texte de page 1 sur page 2,
  textes des pages 2 et 3 superposes dans la derniere section.
- [x] Identifier l'insertion apres le paragraphe porteur de `w:pPr/w:sectPr`,
  qui attribuait les nouveaux paragraphes a la section suivante.
- [x] Inserer les textes avant le paragraphe terminant chaque section et avant
  le `w:sectPr` final, en respectant les limites XML structurelles.
- [x] Tester le parcours bbox -> non-textes -> texte natif sur plusieurs pages,
  les pages sans texte, les signets et les paragraphes XML imbriques.
- [x] Verifier dans la reference initiale 11/15/25 paragraphes dans les sections attendues sans modifier
  contenu, segmentation, polices ou geometrie pour corriger le routage.

## 8. IA executee et limites de preuve

- [x] Executer le layout PaddleX sur CPU : 9/18/17 zones pour les trois pages.
- [x] Tester les contrats de comprehension textuelle avec un fournisseur factice.
- [x] Signaler explicitement le modele de comprehension textuelle absent et
  utiliser le repli ; un client HTTP seul n'est pas un modele local installe.
- [ ] Executer et valider une inference de comprehension textuelle avec un vrai modele.

Le layout de page a bien ete execute. Les contrats testes avec un fournisseur
factice ne prouvent aucune inference semantique reelle. Les sorties actuelles
utilisent le repli lorsque la comprehension textuelle est indisponible.

## 9. Findings corriges apres autorisation

- [x] P1 : traiter deux vrais `layout_frame_id` non vides distincts comme un
  indice de separation, pas une barriere absolue pour la prose continue.
  Les labels A/A/B/B produisent deux paragraphes, meme contre une fusion IA.
  Une ligne non attachee ne cree pas de frontiere et ne masque pas A/None/B
  lorsque ces groupes sont independants.
  Les temoins lettrine et continuite sans cadre restent valides.
  Le prefixe local `inferred:` de `_attacher_frames_texte` designe un conteneur
  geometrique, pas un vrai cadre IA : A/inferred/A reste un paragraphe,
  A/inferred/B independants en donnent deux et inferred1/inferred2 continu reste
  un paragraphe.
  Le dernier vrai cadre reste memorise ; les roles, styles, gaps et obstacles
  gardent leurs controles, y compris heading/corps sur une meme ligne.
  La prose continue A/B et A/(None ou inferred)/B peut rester un paragraphe :
  helpers existants de texte de corps, minuscule, fin de phrase et styles,
  lignes successives (jamais une meme ligne reelle), meme orientation horizontale
  et role de corps, apres tous les gardes de
  geometrie, blanc, liste, obstacle et voisin valide. La meme preuve autorise
  deux blocs source d'une ligne, sans supprimer les contraintes de provenance,
  frontiere explicite, style et validation. Une colonne commune ne suffit pas.
  Apres fusion de plusieurs cadres non vides distincts, le paragraphe n'herite
  plus du premier : `layout_frame_id=None`, `layout_frame_bbox=element.bbox`
  union, role/strategie communs conserves. Les cadres et provenances des lignes
  restent inchanges. Le meme correctif couvre les fusions legacy de reflow ;
  le cas mono-cadre garde son conteneur original.
- [x] P1 : ne segmenter que les noeuds non valides et conserver les noeuds
  valides, leurs IDs, styles, coordonnees et metadata inchanges. Les nouveaux
  IDs evitent les `source_id` et `paragraph_id` preexistants. Les noeuds valides
  intercales bloquent les fusions dans le meme bloc et entre fragments, meme
  en cas de decision IA contraire ; une autre colonne ne bloque pas la continuite.
  Le contrat couvre les appels publics repetes et `prepare_document_elements`.
- [x] P2 : verifier les obstacles avant le retour anticipe des fragments sur
  une meme ligne. Le corridor est limite au vide horizontal et au recouvrement
  vertical des fragments ; les objets voisins hors corridor et le fond qui
  contient les deux fragments ne creent pas de fausse frontiere.
- [x] P2 : recopier la direction du bloc sur la copie de ligne seulement si sa
  direction et celles de ses spans sont par defaut, sans baseline ni quad.
  Une orientation, un angle, une courbe ou une geometrie directionnelle propre
  a la ligne reste prioritaire. La provenance `source-block-fallback` est exposee
  et la geometrie utilise la meme orientation, sans modifier les lignes source.
- [x] Aligner la docstring de `segmenter_page_textes` sur l'implementation :
  consultation par bloc source, puis continuite interblocs prouvee ; pas de
  segmentation IA globale de page annoncee.

La premiere passe ajoutait 39 cas, dont 23 echecs reproduits avant correction,
puis donnait 60 tests verts. La precision de provenance `inferred:` ajoute huit
controles RED -> GREEN et donnait 68 tests verts. Le dernier correctif de
continuite intercadres ajoute 40 cas : huit echecs avant correction, puis
`108 passed, 4 warnings` dans `tests/analysis/test_paragraph_segmentation.py`.
Verification elargie ciblee, avec les tests d'attachement des frames :
`381 passed, 1 skipped, 6 warnings`. Ces controles couvrent fallback et fusion
IA valide, un bloc multiligne et deux blocs monolignes. Aucune regeneration ni
suite complete rejouee pour ce dernier correctif ; les preuves corpus/LO des
autres sections sont anterieures. Aucun total de paragraphes ni regroupement
unique de records label/valeur independants n'est impose.
Le dernier garde exclut `_same_row` de cette preuve : quatre echecs reproduits
pour deux colonnes au meme Y et gouttiere de 24 pt, puis 173 tests passes
(114 segmentation + 59 bbox/contours/routage). Les six nouveaux controles
incluent les temoins de fragments dans un meme cadre, toujours fusionnables.
Coherence postfusion : quatre echecs multi-cadres reproduits avant correction,
quatre temoins mono-cadre deja verts ; huit cas verts apres correction, avec
second cadre plus large, plan natif sans perte de largeur et `geometry_locked`.
Resultat actuel : `122 passed, 4 warnings` en segmentation et
`395 passed, 1 skipped, 6 warnings` sur les contrats/rendus cibles, sans regeneration.
Les identifiants `line:N`
restent locaux a une page et doivent etre interpretes avec `page_index`.
Les contours restent des diagnostics : ne pas reconstruire Word en bandes de
lignes, ni introduire une regle propre a l'un des PDF de verification.

## 10. Commandes de reproduction

Depuis la racine du depot. Les commandes ciblees de reference ci-dessous
documentent les controles de Gibbs. La suite complete, les trois regenerations
et LibreOffice ont ensuite ete rejoues sur le code stabilise, voir section 13.
Le test ignore ne constitue pas une validation visuelle.

```bash
PYTHONDONTWRITEBYTECODE=1 .converter/bin/python -m pytest -q -p no:cacheprovider \
  tests/analysis/test_paragraph_segmentation.py

PYTHONDONTWRITEBYTECODE=1 .converter/bin/python -m pytest -q -p no:cacheprovider \
  tests/analysis tests/render/test_bbox_debug.py \
  tests/render/test_paragraph_contours.py tests/render/test_native_paragraph_pages.py \
  tests/render/test_word_native_rewriter.py tests/render/test_package.py \
  tests/extract/test_orientation.py tests/extract/test_document_reading_frames.py \
  tests/layout/test_text_comprehension.py \
  tests/layout/test_text_comprehension_diagnostics.py tests/test_cli_text_comprehension.py

PYTHONDONTWRITEBYTECODE=1 .converter/bin/python -m pytest -q -p no:cacheprovider \
  tests/render/test_bbox_debug.py \
  tests/render/test_paragraph_contours.py \
  tests/render/test_native_paragraph_pages.py

.converter/bin/python -m pytest -q \
  --ignore=tests/capture_ecran --ignore=tests/visual --tb=short

git diff --check
```

Regeneration du cas trois pages et des deux pages de regression. Les noms ne
servent ici qu'a selectionner les fixtures, jamais de regles de production.

```bash
CORPUS=../vysi/vysi_real_corpus/pdf_native
MODELS=../vysi/ai_models
for cas in dc738585d318b299_000019:1-3 0fd83d2aa11747d4_000152:1 0c6daef79b7165c1_000744:1; do
  nom="${cas%:*}"
  pages="${cas#*:}"
  PYTHONPATH=. .converter/bin/python scripts/reconstruct_bbox_native.py \
    "$CORPUS/$nom.pdf" --pages "$pages" --dpi 100 --text-mode spans \
    --layout-provider paddlex --layout-model ppstructurev3/PP-DocLayout_plus-L \
    --layout-model-root "$MODELS" --layout-device cpu \
    --pdf-out "results/${nom}_bboxes_frontieres_corrigees.pdf" \
    --docx-out "results/${nom}_native_frontieres_corrigees.docx"
done
```

Export LibreOffice execute dans l'environnement autorise, avec escalation
`require_escalated`. La commande ne remplace pas le controle des trois pages
ni le rapport final de Carson.

```bash
mkdir -p results/verification_frontieres
env GSETTINGS_BACKEND=memory libreoffice \
  -env:UserInstallation=file:///tmp/converter-frontieres-lo-validated \
  --headless --convert-to pdf --outdir results/verification_frontieres \
  results/dc738585d318b299_000019_native_frontieres_corrigees.docx
```

## 11. Artefacts et geometrie

| Cas et portee | Texte natif | Geometrie conservee | Artefacts |
| --- | --- | --- | --- |
| Trois pages `dc738585...` | 54 paragraphes acceptes : 11/18/25 (observation precedente 51 : 11/15/25, pas un quota) ; 13/40/43 lignes visibles | 612 x 792 pt par page ; XML 12240 x 15840 twips | [PDF bbox](../results/dc738585d318b299_000019_bboxes_frontieres_corrigees.pdf), [DOCX final](../results/dc738585d318b299_000019_native_frontieres_corrigees.docx), [catalogue](../results/dc738585d318b299_000019_native_frontieres_corrigees.extraction.json) |
| Portrait `0fd83d...`, page 1 seulement | 4 elements texte | 612 x 792 pt ; XML 12240 x 15840 twips | [PDF bbox](../results/0fd83d2aa11747d4_000152_bboxes_frontieres_corrigees.pdf), [DOCX final](../results/0fd83d2aa11747d4_000152_native_frontieres_corrigees.docx), [catalogue](../results/0fd83d2aa11747d4_000152_native_frontieres_corrigees.extraction.json) |
| NASA `0c6...`, page 1 seulement | 3 elements texte | 792 x 612 pt affiches, rotation PDF 90 deg ; XML paysage 15840 x 12240 twips | [PDF bbox](../results/0c6daef79b7165c1_000744_bboxes_frontieres_corrigees.pdf), [DOCX final](../results/0c6daef79b7165c1_000744_native_frontieres_corrigees.docx), [catalogue](../results/0c6daef79b7165c1_000744_native_frontieres_corrigees.extraction.json) |

Intermediaires du cas trois pages : [bbox seul](../results/dc738585d318b299_000019_native_frontieres_corrigees.bboxes.docx)
et [non-textes](../results/dc738585d318b299_000019_native_frontieres_corrigees.non_text.docx).
Diagnostics source : [page 1](../results/dc738585d318b299_000019_frontieres_page1.png),
[page 2](../results/dc738585d318b299_000019_frontieres_page2.png),
[page 3](../results/dc738585d318b299_000019_frontieres_page3.png).

Derniers rendus LibreOffice valides par le [rapport final](../results/verification_frontieres/validation_frontieres.json) :
[PDF](../results/verification_frontieres/dc738585d318b299_000019_native_frontieres_corrigees.pdf),
[page 1](../results/verification_frontieres/docx_page1.png),
[page 2](../results/verification_frontieres/docx_page2.png),
[page 3](../results/verification_frontieres/docx_page3.png).

## 12. Reference LibreOffice avant les quatre correctifs

Cette section decrit la reference precedente 51/11/15/25, pas les artefacts
actuels. La section 13 et le rapport JSON actualise ci-dessous la remplacent
pour la verification finale apres les correctifs.
Cette observation n'impose ni le nombre 51 ni un paragraphe Budget unique.

- [x] Regeneration et export LibreOffice termines avec code de sortie 0 ;
  export realise avec escalation sandbox et trois pages inspectees.
- [x] Verifier le texte ordonne sur sa page source apres retrait des blancs :
  aucune omission de caractere non blanc, ni decalage ou melange de pages.
- [x] Verifier Budget : 4 lignes structurees, 3 `w:br`, 1 paragraphe Word,
  memes lignes dans le catalogue, le DOCX et le PDF LibreOffice hors blancs de bord.
- [x] Verifier Partners : 5 lignes structurees, 4 `w:br`, 1 paragraphe Word,
  memes lignes dans le catalogue, le DOCX et le PDF LibreOffice hors blancs de bord.
- [x] Mettre a jour les six apercus, trois diagnostics et trois rendus DOCX,
  a 144 dpi, 1224 x 1584 pixels ; tous sont non vides.

| Page | Lignes visibles source/catalogue/LibreOffice | Paragraphes catalogue/DOCX | Segments source/catalogue |
| --- | --- | --- | --- |
| 1 | 13/13/13 | 11/11 | 15/15 |
| 2 | 40/40/40 | 15/15 | 60/60 |
| 3 | 43/43/43 | 25/25 | 67/67 |
| Total | 96/96/96 | 51/51 | 142/142 |

Preuves et limites : [validation_frontieres.json](../results/verification_frontieres/validation_frontieres.json)
consigne les controles par page, les lignes structurees et les empreintes
SHA-256 des artefacts. Texte/couleur/gras/italique sont conserves dans les
segments du catalogue. Les tailles sont identiques au centieme ; deux valeurs
flottantes de la page 1 different de leur serialisation decimale de moins de
`1e-6` pt. Ce n'est pas une egalite brute des flottants sur cette page.

Les retours souples de prose sont recomposes par Word/LibreOffice : le resultat
n'est pas pixel-identique. Le XML Word utilise des demi-points (19.98 devient
20 pt et 7.98 devient 8 pt) ; LibreOffice ajuste encore certaines tailles dans
les cadres. La police des puces peut etre substituee. La taille rendue et toutes
les polices ne sont donc pas certifiees identiques a la source. Le fournisseur
de comprehension semantique reste absent, avec un avertissement explicite unique
et repli geometrique/heuristique. Ces limites ne sont pas levees par la validation LO.

## 13. Verification apres les quatre correctifs

- [x] Executer les regressions generiques RED -> GREEN : 23 echecs avant la
  premiere correction, puis huit controles rouges sur la provenance inferree ;
  68 tests passes apres, dont les 21 tests precedents.
- [x] Executer les contrats, rendus et attachements de frames cibles : 341 passes, 1 ignore.
- [x] Carson : rejouer la suite complete apres le dernier correctif multi-cadres :
  655 passes, 1 ignore, 7 avertissements, 0 echec, 52.27 s ; elle inclut les
  122 tests de segmentation et les 59 tests bbox/contours/routage.
- [x] Carson : `git diff --check` propre avant regeneration et apres documentation.
- [x] Carson : regenerer les trois cas avec les options CPU de la section 10,
  sans `--layout-ai` ni drapeau de comprehension historique ; codes de sortie 0.
- [x] Carson : rejouer LibreOffice avec escalation, code de sortie 0, trois pages.
- [x] Verifier les regressions page 1 : portrait 4 elements texte, NASA 3,
  texte ordonne inchange hors blancs et styles source/catalogue au centieme.
- [x] Verifier les 96 lignes et 142 segments du cas trois pages : texte,
  couleur, gras et italique source/catalogue conserves ; tailles au centieme.
- [x] Verifier le routage final : trois sections XML 11/18/25, trois pages LO,
  aucun caractere non blanc omis ni melange entre pages.
- [x] Actualiser les six apercus a 144 dpi, 1224 x 1584 pixels et verifier
  chacun contre le rendu du PDF final correspondant.
- [x] Consigner les SHA-256 et dates des 16 artefacts finaux ainsi que les
  empreintes des 111 fichiers Python, inchanges pendant la verification.
- [x] Remplacer l'ancien attendu auto-impose 51/Budget unique par le contrat
  general : enregistrements autonomes natifs, prose prouvee continue protegee,
  aucun nom ou quota dans la production. Observation finale : 54, soit 11/18/25.
- [x] Verifier les positions et styles des 142 segments inchanges par rapport
  au catalogue precedent, a la precision d'extraction existante.
- [x] Verifier le texte Word natif : les deux blocs de prose de huit et neuf
  lignes restent chacun un `w:p` editable avec zero `w:br`, pas des bandes.

Les resultats 554/59 et la validation LO des sections precedentes restent la
reference historique. Les passes intermediaires 601/1 a 14:47 UTC et 647/1
a 15:09 UTC sont conservees dans le JSON, sans les attribuer au dernier code.
La verification finale de Carson, terminee le 2026-10-10 a 15:18 UTC, est tracee dans
[validation_frontieres.json](../results/verification_frontieres/validation_frontieres.json).
Les deux regressions conservent chacune six lignes/six segments, les dimensions
portrait/paysage et la rotation NASA 90 deg. Aucun code de production ni test
n'a ete modifie pendant cette verification ; seuls ces documents et les
artefacts generes ont ete actualises.

| Page | Lignes source/catalogue/LO | Paragraphes catalogue/section DOCX | Segments source/catalogue |
| --- | --- | --- | --- |
| 1 | 13/13/13 | 11/11 | 15/15 |
| 2 | 40/40/40 | 18/18 | 60/60 |
| 3 | 43/43/43 | 25/25 | 67/67 |
| Total | 96/96/96 | 54/54 | 142/142 |

Changement observe et accepte apres arbitrage parent/Gibbs : les quatre lignes
Budget sont quatre enregistrements label/valeur complets et autonomes. Elles
forment quatre paragraphes Word natifs, sans `w:br`, rattaches a quatre vrais
`layout_frame_id` distincts (10/11/12/13), au lieu du paragraphe avec trois
retours de la reference initiale. Ce ne sont pas des bandes de prose ; aucune
fusion artificielle n'est imposee pour retrouver 51. Partners conserve cinq
lignes, quatre `w:br` et un seul paragraphe. Aucun chevauchement de texte visible
n'a ete observe sur les trois apercus LO inspectes.

Le premier controle de 14:47 UTC avait qualifie cet ecart de regression par
rapport a un attendu 51/Budget unique auto-impose par le main, pas par
l'utilisateur. L'historique du changement et de cette interpretation est
conserve, mais cet attendu n'est plus un critere d'acceptation. Le statut JSON
final est `validated-with-reviewed-segmentation-change`, avec preuve de records
independants, preservation des caracteres non blancs sur chaque page et styles
source/catalogue. La prose continue intercadres et la largeur union apres fusion
sont couvertes par la suite finale, sans supprimer les gardes de separation.
Les limites de comprehension semantique reelle et d'identite stricte des styles
rendus/pixels restent ouvertes ; les positions brutes PDF non quantifiees ne
sont pas revendiquees identiques au catalogue.
