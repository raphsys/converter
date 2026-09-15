# Plan d'implementation de la taxonomie layout

Ce document sert de reference de suivi pour transformer la taxonomie du corpus PDF native
en architecture d'extraction generale.

Taxonomie source :

```text
docs/taxonomie_corpus_pdf_native.md
docs/corpus_taxonomy_pdf_native.json
```

## Principe

Le convertisseur ne doit plus enchainer directement :

```text
PDF -> extraction texte/images/tables -> DOCX
```

Il doit d'abord comprendre la page :

```text
PDF
 -> page analyzer
 -> region detector
 -> region classifier
 -> strategy planner
 -> extractor by region
 -> DOCX renderer
```

Regle d'or :

```text
find_tables() ne decide plus.
RapidOCR ne decide plus.
Le classifieur layout decide.
```

## Architecture cible

Chaque page devient une liste de regions documentaires.

```python
LayoutRegion(
    kind="text|table|image|figure|formula|shape|header|footer|caption|form",
    bbox=...,
    confidence=...,
    editable=True,
    strategy="word_text|word_table|raster|shape|ignore|ocr",
    children=[],
    style_hints={},
)
```

Modules a creer :

```text
pdfexact/layout/model.py
pdfexact/layout/analyzer.py
pdfexact/layout/detectors.py
pdfexact/layout/classifier.py
pdfexact/layout/planner.py
```

Tests a creer :

```text
tests/layout/test_classifier.py
tests/layout/test_table_validation.py
tests/layout/test_columns.py
tests/layout/test_protected_zones.py
```

## Objets principaux

```text
LayoutPage
LayoutRegion
RegionKind
RegionStrategy
TableCandidate
TextColumn
ProtectedZone
LayoutDecision
```

Objectif : separer clairement :

- ce que la page contient ;
- ce qui est editable ;
- ce qui doit rester immuable ;
- comment chaque region doit etre rendue en DOCX.

## Taxonomie des elements dans la page

La taxonomie de page donne le contexte general : page standard, tableau dense,
colonnes, paysage, page scannee, bandeaux colores, etc. Elle ne suffit pas.

Chaque element doit aussi recevoir une decision documentaire propre :

```text
role       : real-table | text-column | section-band | image | scanned-page |
             figure-or-diagram | formula-or-complex-vector | page-border
strategy   : word-table | word-text | shape-background | raster-image |
             raster-immutable | shape
editable   : true/false
confidence : score de decision
context    : profils de page actifs au moment de la decision
reasons    : signaux qui ont motive la classification
```

Regle :

```text
Le type de page influence la decision, mais ne remplace jamais la classification
de l'element lui-meme.
```

Exemples :

```text
page dense-table + element table
  -> role=real-table, strategy=word-table, editable=true

page two-column + lignes natives separees en deux groupes
  -> role=text-column, strategy=word-text, editable=true

page colored-bands + rectangle rempli large
  -> role=section-band, strategy=shape-background, editable=false

zone vectorielle dense
  -> role=figure-or-diagram, strategy=raster-immutable, editable=false

image couvrant presque toute la page
  -> role=scanned-page, strategy=raster-image, editable=false
```

Implementation actuelle :

```text
pdfexact/layout/understanding.py
  PageUnderstanding.zones     -> protections OCR/layout
  PageUnderstanding.elements  -> decisions role/strategy/editable
  UnderstandingElement        -> taxonomie elementaire exploitable par les extracteurs
```

## Page Analyzer

Le Page Analyzer collecte les signaux bruts sans prendre de decision finale.

Signaux :

```text
page size
rotation
native text blocks
text spans
fonts
colors
images
drawings
fills
strokes
table candidates from PyMuPDF
OCR lines if needed
text density
image coverage
vector density
column distribution
```

Sortie attendue :

```python
LayoutPage(
    page_index=...,
    width=...,
    height=...,
    rotation=...,
    text_blocks=[...],
    image_blocks=[...],
    drawing_blocks=[...],
    table_candidates=[...],
    metrics={...},
)
```

## Detecteurs de regions

Detecteurs a implementer progressivement :

```text
detect_text_regions()
detect_table_candidates()
detect_image_regions()
detect_vector_regions()
detect_formula_regions()
detect_header_footer()
detect_captions()
detect_form_regions()
detect_colored_bands()
detect_columns()
```

Chaque detecteur renvoie des hypotheses de regions avec bbox et confiance.

## Classification

Une meme zone peut avoir plusieurs hypotheses :

```text
table_candidate
text_column
figure
formula
shape_background
caption
header
footer
```

Le classifieur arbitre.

Exemples de decisions :

```text
si table_candidate ressemble a une colonne de texte
  -> text_column

si vectoriel dense + peu de texte courant
  -> figure ou formula, strategie raster

si image couvre presque toute la page
  -> scanned_or_fullpage_image

si petite image + texte proche dessous
  -> image + caption

si zone haut/bas repetee
  -> header/footer

si grille/fonds/bordures/cellules regulieres
  -> table
```

## Strategy Planner

Le planner transforme les regions classifiees en strategies d'extraction/rendu.

```text
TextRegion       -> Word editable
TableRegion      -> Word table
ImageRegion      -> anchored image
FigureRegion     -> raster immutable
FormulaRegion    -> raster immutable
ShapeRegion      -> Word shape if simple, raster if complex
Header/Footer    -> Word header/footer if stable, otherwise positioned text
CaptionRegion    -> Word editable attached to figure/table
FormRegion       -> table/shape/text hybrid
```

## Branchement dans document.py

Etat actuel simplifie :

```text
vector -> images -> tables -> OCR/text
```

Etat cible :

```python
profile = analyze_page(page_pdf)
regions = classify_regions(profile)
plan = plan_regions(regions)

for region in plan:
    extractor = extractor_for(region.strategy)
    page_ir.elements.extend(extractor(region))
```

## Phases d'implementation

### Phase 1 - Fondation

Objectif : introduire l'architecture sans casser le comportement actuel.

- creer `pdfexact/layout/model.py`;
- creer `layout/analyzer.py`;
- creer `LayoutPage`, `LayoutRegion`, `ProtectedZone`;
- produire un profil page en verbose/report;
- ne pas encore modifier lourdement le rendu.

Critere de validation :

```text
--visual-exact produit le meme type de DOCX qu'avant,
mais le rapport contient le diagnostic layout.
```

### Phase 2 - Tableaux vs colonnes

Objectif : corriger le probleme `cb3536...`.

- creer `TableDecision`;
- transformer `find_tables()` en fournisseur de candidats seulement;
- rejeter les faux tableaux :
  - 2 colonnes;
  - 2 ou 3 lignes;
  - bbox tres grande;
  - pas de bordures reelles;
  - pas de fonds non blancs;
  - cellules avec longs paragraphes continus;
  - structure compatible colonnes texte;
- ajouter tests sur `cb3536e7070a8a08_000341.pdf`.

Critere de validation :

```text
cb3536... ne produit plus de TableEl pour ses colonnes journalistiques.
```

### Phase 3 - Moteur multi-colonnes

Objectif : convertir les colonnes comme texte Word, pas comme tableaux.

- creer `pdfexact/extract/columns.py`;
- detecter 2 colonnes et 3 colonnes+;
- creer des zones de colonne;
- garder l'ordre de lecture;
- eviter l'OCR/tableaux dans les colonnes deja traitees.

Critere de validation :

```text
pages article/newsletter : colonnes conservees, pas de faux tableau.
```

### Phase 4 - Zones protegees

Objectif : eliminer doublons, superpositions et OCR parasite.

- centraliser les zones protegees;
- types :
  - table;
  - image;
  - figure;
  - formula;
  - vector_dense;
  - colored_band;
  - form;
- RapidOCR ignore toute zone protegee non editable;
- les zones editables sont traitees par leur extracteur dedie.

Critere de validation :

```text
pas de texte OCR reinjecte dans tableaux/figures/formules.
```

### Phase 5 - Figures, formules, vectoriel dense

Objectif : choisir proprement entre Word editable et raster immuable.

- detecter les zones de vectoriel dense;
- detecter graphiques/courbes/axes/labels;
- detecter formules/equations blocs;
- rasteriser seulement les zones complexes;
- garder le texte courant autour editable.

Critere de validation :

```text
les graphiques/formules ne sont plus casses en glyphes ou formes incoherentes.
```

### Phase 6 - Styles texte

Objectif : respecter davantage le texte Word authentique.

- police;
- taille;
- gras;
- italique;
- souligne;
- barre;
- couleur;
- surlignage;
- petites capitales;
- exposant / indice;
- espacement caracteres;
- interligne.

Critere de validation :

```text
les textes editables restent visuellement proches du PDF sans deborder.
```

### Phase 7 - Structure documentaire

Objectif : comprendre les elements repetitifs et documentaires.

- headers;
- footers;
- numeros de page;
- captions;
- notes de bas de page;
- listes;
- titres hierarchiques;
- references;
- sommaires.

Critere de validation :

```text
les elements repetitifs ne polluent plus le flux principal.
```

### Phase 8 - Tableaux avances

Objectif : couvrir les vrais tableaux difficiles.

- cellules fusionnees;
- tableaux sans bordures visibles;
- fonds de cellules;
- bordures/epaisseurs/couleurs;
- tableaux multipages;
- tableaux tournes;
- alignement par cellule;
- padding par cellule.

Critere de validation :

```text
les tableaux restent vrais tableaux Word et gardent leur aspect visuel.
```

### Phase 9 - Audit corpus

Objectif : valider la generalisation.

- relancer le profilage corpus;
- generer un rapport par famille;
- convertir les documents de reference;
- comparer les regressions;
- ajouter les cas nouveaux a la taxonomie.

## CLI diagnostic a ajouter

Commande cible :

```bash
.converter/bin/pdfexact-layout "/path/doc.pdf" --pages 1-5 --json report.json
```

Exemple de sortie :

```json
{
  "page": 1,
  "type": "mixed_layout",
  "regions": [
    {"kind": "header", "bbox": "...", "strategy": "word_text"},
    {"kind": "text_column", "bbox": "...", "strategy": "word_text"},
    {"kind": "figure", "bbox": "...", "strategy": "raster"},
    {"kind": "caption", "bbox": "...", "strategy": "word_text"}
  ],
  "rejected": [
    {"kind": "table_candidate", "reason": "false_table_columns"}
  ]
}
```

## Documents de reference

Faux tableaux / colonnes :

```text
cb3536e7070a8a08_000341.pdf
cddc0da7b710c500_000262.pdf
```

Vrais tableaux complexes :

```text
0fd83d2aa11747d4_000152.pdf
5c4ccaaadf5acb5b_000155.pdf
```

Pages scannees / image pleine page :

```text
6885cb45c5f01efd_000282.pdf
```

Vectoriel dense / graphiques / formules :

```text
0688ba309c87485d_000029.pdf
077bbf325240285f_000547.pdf
```

Paysage / rotation :

```text
077bbf325240285f_000547.pdf
0c6daef79b7165c1_000744.pdf
d7d1994af83d5fce_000737.pdf
```
