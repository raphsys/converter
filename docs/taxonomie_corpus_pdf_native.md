# Taxonomie du corpus PDF native

Source analysee :

```text
/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/
```

Profilage :

```text
150 PDF
4184 pages
Rapport brut versionne : docs/corpus_taxonomy_pdf_native.json
Rapport brut de generation : tests/logs_converter/corpus_taxonomy_pdf_native.json
```

## Classes observees

Les classes se recoupent : une page peut etre a la fois texte simple, image-heavy et
contenir un tableau.

```text
single_column_text                 2613 pages
image_heavy                         773 pages
sparse_or_cover_page                763 pages
real_table_candidate                548 pages
long_plain_text                     433 pages
two_column_text                     364 pages
orientation/landscape_or_rotated    349 pages
colored_bands_or_fills              340 pages
dense_vector_formula_or_chart       327 pages
multi_column_3plus                   30 pages
scanned_or_fullpage_image            28 pages
false_table_columns_candidate         4 pages
```

## Conclusions

Le convertisseur ne doit plus traiter tous les PDF avec une seule strategie. Il faut
classer la page avant de choisir l'extraction :

- texte simple en une colonne ;
- article ou rapport en plusieurs colonnes ;
- vrais tableaux ;
- faux tableaux dus a une mise en page en colonnes ;
- pages scannees ou image pleine page ;
- pages avec figures, formules, graphiques ou vectoriel dense ;
- pages paysage ou avec rotation ;
- pages mixtes avec bandeaux, cadres, fonds colores et tableaux.

Le document `cb3536e7070a8a08_000341.pdf` montre une erreur importante : PyMuPDF detecte
des colonnes journalistiques comme des tableaux. La sortie Word est alors structurellement
propre, mais la decision d'extraction est mauvaise.

## Regles a implementer

### 1. Classifieur de page

Creer une couche `layout_classifier` avant extraction fine. Elle doit produire un profil
de page utilisable par les extracteurs :

```text
single_column_text
two_column_text
multi_column_text
real_table_page
false_table_columns
image_heavy
scanned_or_fullpage_image
dense_vector_formula_or_chart
colored_bands_or_fills
landscape_or_rotated
sparse_or_cover_page
mixed_layout
```

### 2. Validateur de tableaux

Durcir `extract/tables.py` pour rejeter les faux tableaux.

Rejeter comme faux tableau si plusieurs signaux sont vrais :

- 2 colonnes seulement ;
- 2 ou 3 lignes seulement ;
- zone tres grande dans la page ;
- pas de bordures reelles ;
- pas de fonds de cellule significatifs hors blanc ;
- cellules contenant de longs paragraphes continus ;
- longueur moyenne de cellule tres elevee ;
- structure compatible avec des colonnes de texte.

Garder comme vrai tableau si plusieurs signaux sont vrais :

- grille visible ;
- plusieurs lignes regulieres ;
- plusieurs colonnes regulieres ;
- bordures detectees ;
- fonds de cellules ou en-tetes colores ;
- cellules courtes ou semi-structurees ;
- alignements repetitifs ;
- presence d'en-tetes.

### 3. Moteur multi-colonnes

Les pages `two_column_text` et `multi_column_text` doivent etre traitees comme blocs de
colonnes, pas comme tableaux.

Objectif :

- detecter les colonnes ;
- conserver leur bbox ;
- convertir colonne par colonne ;
- garder l'ordre de lecture correct ;
- ne pas envoyer les colonnes a l'extracteur de tableaux.

### 4. Zones protegees

Avant OCR et rendu Word, construire une carte des zones protegees :

- vrais tableaux ;
- images ;
- figures ;
- graphiques ;
- formules/equations ;
- zones vectorielles denses ;
- bandeaux et fonds colores ;
- cadres et encadres.

RapidOCR ne doit pas reinjecter du texte qui touche ces zones, sauf si la zone est
explicitement classifiee comme texte editable.

### 5. Strategie par type de page

Proposition de routage :

```text
scanned_or_fullpage_image
  -> raster page + OCR invisible/optionnel

dense_vector_formula_or_chart
  -> rasteriser les zones complexes, garder le texte courant editable

real_table_page
  -> reconstruire tableaux cellule par cellule, OCR ignore les zones table

false_table_columns / two_column_text / multi_column_text
  -> desactiver tables candidates, reconstruire colonnes/blocs texte

single_column_text / long_plain_text
  -> reflow ou hybrid selon densite visuelle

landscape_or_rotated
  -> respecter taille, orientation et rotation avant tout placement

colored_bands_or_fills
  -> conserver formes/fonds/couleurs avant texte
```

## Documents de reference

Faux tableau / colonnes :

```text
cb3536e7070a8a08_000341.pdf
cddc0da7b710c500_000262.pdf
```

Vrais tableaux complexes :

```text
0fd83d2aa11747d4_000152.pdf
5c4ccaaadf5acb5b_000155.pdf
```

Pages scannees ou image pleine page :

```text
6885cb45c5f01efd_000282.pdf
```

Vectoriel dense / graphiques / formules :

```text
0688ba309c87485d_000029.pdf
077bbf325240285f_000547.pdf
```

Documents paysage / rotation :

```text
077bbf325240285f_000547.pdf
0c6daef79b7165c1_000744.pdf
d7d1994af83d5fce_000737.pdf
```

## Priorite implementation

1. Ajouter un `layout_classifier`.
2. Ajouter un validateur de tableaux et filtrer les faux tableaux.
3. Ajouter le moteur multi-colonnes.
4. Relier les zones protegees au classifieur.
5. Ajouter des tests par famille de mise en page.
6. Lancer des probes sur les documents de reference avant generalisation.
