# Convertisseur PDF natif → DOCX, fidélité visuelle

Date : 2026-08-11
Statut : design validé, prêt pour plan d'implémentation

## 1. Objectif

Une bibliothèque Python et une commande en ligne de commande qui convertissent un PDF
natif (avec couche texte réelle, sans OCR) en document Word `.docx` visuellement fidèle
à l'original.

« Fidèle » signifie ici : ouvert dans Word à 100 % de zoom, le document est indiscernable
à l'œil du PDF source. Ce n'est pas une égalité bit à bit du rendu — Word n'est pas un
moteur de rendu PDF, et cette limite est assumée.

Le document produit n'est pas destiné à une réécriture de fond. Le texte reste réel,
sélectionnable et modifiable, mais la mise en page est figée par positionnement absolu :
modifier un paragraphe ne fait pas refluer le reste de la page.

### Hors périmètre

- PDF scannés / OCR
- Interface graphique (web ou bureau), édition interactive du mappage
- Mode « flux » produisant un document éditable avec styles sémantiques et reflow
- Formulaires PDF interactifs, annotations, signatures, JavaScript embarqué
- PDF chiffrés ou protégés par mot de passe

### Critères de réussite

1. Sur le corpus de référence, chaque page obtient un score SSIM supérieur au seuil fixé
   par rapport au rendu du PDF source.
2. Chaque `.docx` produit s'ouvre dans Word sans boîte de dialogue de réparation.
3. Le texte reste sélectionnable et cherchable ; les hyperliens restent cliquables.
4. Aucun PDF du corpus ne provoque de crash : au pire une page dégradée signalée.

## 2. Contenus pris en charge

Tous les éléments suivants doivent survivre à la conversion :

- Texte multi-colonnes, encadrés, en-têtes et pieds de page, notes de bas de page
- Variations de police : famille, corps, graisse, italique, couleur
- Tableaux, bordurés ou non, cellules fusionnées incluses
- Images bitmap : JPEG, PNG, et tout format porté par PyMuPDF
- Graphiques vectoriels : traits, rectangles, courbes de Bézier, aplats, filigranes
- Hyperliens externes et liens internes vers une autre page

Les tableaux ne sont pas reconstruits en tableaux Word. Un tableau est un ensemble de
traits vectoriels et de lignes de texte ; positionnés exactement, ils produisent le même
rendu. Reconstruire une grille `<w:tbl>` introduirait une mise en page calculée par Word,
donc de la dérive — l'inverse de l'objectif.

## 3. Architecture

Pipeline en trois temps :

```
PDF → Extracteurs → IR → Writer → .docx
```

L'IR (représentation intermédiaire) est le contrat entre les deux moitiés. Les extracteurs
ne connaissent rien d'OOXML ; le writer ne connaît rien du PDF. Chaque moitié est testable
isolément, et une régression se localise immédiatement d'un côté ou de l'autre.

### Arborescence

```
pdfexact/
  cli.py              # analyse des arguments, orchestration de haut niveau
  ir.py               # dataclasses de l'IR — le contrat
  extract/
    document.py       # ouverture PyMuPDF, itération des pages
    text.py           # rawdict → TextBox / Line / Span
    images.py         # xrefs et rectangles de placement, déduplication
    vector.py         # get_drawings() → Path, regroupement en clusters
    links.py          # get_links() → LinkZone
    fonts.py          # extract_font(), normalisation, reconstruction du cmap
  render/
    package.py        # écriture du zip OOXML
    docx_writer.py    # IR → document.xml
    drawing.py        # DrawingML : anchors, textbox, picture, custGeom
    fonts_embed.py    # obfuscation .odttf, fontTable.xml
  fallback/
    rasterize.py      # get_pixmap(clip=rect) → PNG
  geometry.py         # conversions d'unités, utilitaires de bbox
  report.py           # collecte et restitution des avertissements
```

### Dépendances

Runtime : PyMuPDF (extraction et rendu), fontTools (conversion et réparation de polices),
Pillow (encodage PNG du repli raster). Python 3.10 — la version du venv existant.

Développement : LibreOffice headless (conversion docx → PDF pour les tests visuels),
scikit-image ou équivalent pour le calcul SSIM, pytest.

### Ancrage et système de coordonnées

Chaque page PDF devient une section Word dont la taille et les marges reprennent
exactement la MediaBox. La section contient un unique paragraphe vide. Tous les éléments
de la page sont des `<wp:anchor>` positionnés en absolu, `relativeFrom="page"` sur les
deux axes.

Conséquence recherchée : rien n'est dans le flux du document, donc rien ne peut refluer.

Unités : PyMuPDF donne des points (72 par pouce), origine en haut à gauche — même
convention que Word, aucune inversion d'axe nécessaire. Conversions :

- EMU = points × 12700 (914400 EMU par pouce)
- twips = points × 20 (utilisé pour la taille de section et l'interligne)

La conversion se fait une seule fois, à la sortie des extracteurs. L'IR est entièrement en
EMU. Aucun point ne circule au-delà de cette frontière.

### Ordre de superposition

Chaque page porte une liste d'éléments unique et ordonnée, dans l'ordre du flux de contenu
PDF. Cet ordre se traduit en `relativeHeight` croissant sur les ancres. Les éléments de
fond (aplats de couleur, filigranes) reçoivent `behindDoc="1"`.

## 4. Représentation intermédiaire

```python
Page(index, width_emu, height_emu, elements: list[Element])

TextBox(bbox, lines: list[Line], rotation)
Line(bbox, baseline, spans: list[Span], target_width, line_height)
Span(text, font_ref, size_pt, color, bold, italic, char_spacing, link)

ImageEl(bbox, media_ref, rotation)
ShapeEl(bbox, paths: list[Path], fill, stroke, stroke_width, dash, alpha)
RasterEl(bbox, media_ref)
LinkZone(bbox, uri, page_target)

FontRef(family, embedded_font, fallback_name, ascent, descent)
Path(commands: list[PathCommand])
```

`Element` est l'union de `TextBox`, `ImageEl`, `ShapeEl`, `RasterEl` et `LinkZone`.

`RasterEl` n'est jamais produit par un extracteur : il naît uniquement du mécanisme de
repli décrit en section 6.

Deux formes de liens coexistent, et le partage est net : `Span.link` porte les liens
ancrés sur du texte, `LinkZone` les liens couvrant une zone sans texte (image, bouton).
L'extracteur de liens attribue chaque lien à l'une ou l'autre selon qu'il recouvre ou non
des spans de texte.

Une seule grandeur échappe aux EMU : `size_pt`, le corps de police, exprimé en points
parce que Word l'attend en demi-points (`<w:sz>`). Toutes les autres coordonnées et
dimensions de l'IR sont en EMU.

`Path` est une suite de `PathCommand`, chacune étant un couple (type, points) où le type
vaut `move`, `line`, `cubic`, `quad` ou `close`.

### Décision : une zone de texte par ligne

Le texte est découpé au niveau de la ligne, pas du bloc. Chaque `Line` devient une zone de
texte OOXML distincte, positionnée sur sa baseline exacte.

Motif : dès qu'une zone contient plusieurs lignes, c'est Word qui calcule les retours à la
ligne et l'interligne, avec ses propres métriques. L'écart s'accumule verticalement et la
fin du bloc dérive. Une ligne par zone supprime ce calcul.

Coût : environ quarante formes par page de texte dense. Le volume est acceptable et Word
le gère sans ralentissement notable.

### Décision : correction de largeur par espacement

Word ne restitue pas exactement les mêmes largeurs de glyphes que le PDF, même à police
identique. La ligne serait trop courte ou trop longue, et son alignement à droite faux.

Correction : pour chaque ligne, on compare la largeur rendue attendue à `target_width`
mesuré dans le PDF, et on répartit l'écart en `<w:spacing>` sur les runs — l'espacement
inter-caractères de Word, exprimé en vingtièmes de point. La ligne retombe sur sa largeur
d'origine.

## 5. Génération OOXML

Le package est écrit à la main via `zipfile` et des gabarits XML. python-docx est écarté :
il ne sait produire ni ancres flottantes ni `custGeom`, qui sont le cœur de l'approche.

Parties écrites : `[Content_Types].xml`, `_rels/.rels`, `word/document.xml`,
`word/_rels/document.xml.rels`, `word/styles.xml`, `word/settings.xml`,
`word/fontTable.xml`, `word/media/*`.

### Zone de texte

Une forme `<wps:wsp>` contenant `<wps:txbx><w:txbxContent>`, avec `noFill` et `noStroke`.
Le `<wps:bodyPr>` porte des marges internes nulles, `anchor="t"`, sans ajustement
automatique. L'ancre porte `<wp:wrapNone/>`.

Le paragraphe interne fixe `spacing` avant et après à zéro, et `lineRule="exact"` à la
hauteur de ligne relevée dans le PDF. Sans cette contrainte, Word applique son propre
interligne et tout le contenu descend.

### Image

`<wp:anchor>` avec `blipFill` et `<wp:wrapNone/>`. Les images sont dédupliquées par xref :
une image répétée cinquante fois dans le PDF ne produit qu'une seule entrée dans `media/`,
référencée autant de fois que nécessaire.

### Forme vectorielle

`<a:custGeom>`. Les primitives de `get_drawings()` se transposent directement :

| PyMuPDF | DrawingML |
|---|---|
| `"l"` (ligne) | `<a:lnTo>` |
| `"c"` (Bézier cubique) | `<a:cubicBezTo>` |
| `"qu"` (quadrilatère) | suite de `<a:lnTo>` fermée |
| `"re"` (rectangle) | suite de `<a:lnTo>` fermée |

Les coordonnées des chemins sont exprimées relativement à la bbox de la forme. Le
remplissage passe par `<a:solidFill>`, le contour par `<a:ln>` avec `prstDash` pour les
pointillés, la transparence par `<a:alpha>`.

### Liens

Un lien portant sur du texte devient un `<w:hyperlink>` enveloppant les runs concernés.
Un lien portant sur une zone (image, bouton) devient une forme rectangulaire invisible
portant `<a:hlinkClick>`.

## 6. Vectoriel complexe et repli raster

Certaines constructions PDF n'ont pas d'équivalent DrawingML fiable. Plutôt que de
produire un rendu faux, on rastérise la zone concernée — et elle seule.

Les chemins sont d'abord regroupés en clusters par chevauchement de bbox. Chaque cluster
reçoit un score, et bascule en repli si :

- il contient un dégradé ou un shading
- il est soumis à un masque de clipping non rectangulaire
- il utilise un mode de fusion autre que Normal
- il compte plus de chemins que le seuil configuré (défaut : 300)

Le repli produit `page.get_pixmap(clip=cluster_bbox, dpi=<--dpi>)` puis un `RasterEl`
ancré à la place du cluster.

Le texte n'est jamais rastérisé. Il est écrit après le raster dans l'ordre de
superposition, et reste réel, sélectionnable et cherchable même au-dessus d'une zone
d'image.

## 7. Interface en ligne de commande

```
pdfexact convertir ENTREE.pdf SORTIE.docx [options]
```

| Option | Défaut | Effet |
|---|---|---|
| `--pages` | toutes | Sélection de pages, ex. `1-5,8` |
| `--dpi` | 300 | Résolution des zones rastérisées |
| `--raster-threshold` | 300 | Nombre de chemins déclenchant le repli |
| `--no-embed-fonts` | désactivé | Force le mode police système + correction de largeur |
| `--strict` | désactivé | Échoue au lieu de dégrader une page |
| `--report` | — | Écrit le rapport de conversion en JSON dans le fichier indiqué |

L'API Python expose la même chose : `pdfexact.convert(src, dst, **options) -> Report`.

## 8. Polices

Le PDF n'embarque que des sous-ensembles de police, souvent privés de leur table `cmap` :
inexploitables pour mesurer du texte. Mesure sur 19 polices de trois PDF réels — seul le
cas TrueType + WinAnsiEncoding porte un cmap utilisable ; MacRomanEncoding, Type0/Identity-H
et Type1 échouent, et Type0 domine les PDF modernes.

En revanche le PDF **nomme** toujours ses polices. C'est ce nom qui sert.

### Bibliothèque de reconnaissance

`pdfexact/fontlib.py` indexe les polices disponibles et résout un nom PostScript en
cascade :

1. nom exact, préfixe de sous-ensemble retiré
2. famille + style
3. équivalence métrique via `pdfexact/data/alias_polices.json` — table de **données**,
   éditable sans toucher au code
4. famille seule, en Regular
5. échec → substitution approchante, signalée dans le rapport

Sources, par priorité croissante : polices système (`fc-list`), bibliothèque embarquée
dans le paquet, dossier `fonts/` du projet, puis chaque `--font-dir`. Le dernier gagne.

`pdfexact/fonts/` embarque 444 polices à licence libre vérifiée, suivies par git : un
clone du dépôt convertit à l'identique sur n'importe quelle machine. `scripts/auditer_licences.py`
lit `OS/2.fsType` et les mentions de licence de chaque fichier et refuse tout ce qu'il ne
reconnaît pas — une licence non identifiée n'est jamais présumée permissive.

### Ce que la reconnaissance apporte, mesuré

La police retrouvée fournit les métriques réelles, qui gouvernent le placement :
ascendante pour le sommet de la zone de texte, avances de glyphes pour la correction de
largeur.

| Cas | dx | dy | largeur |
|---|---|---|---|
| Police exactement retrouvée | 0,000 pt | 0,000 pt | 0,000 % |
| Police réelle (Raleway, document complexe) | +0,09 pt | −0,04 pt | −0,09 % |
| Police substituée (HelveticaNeue → Nimbus Sans) | +0,12 pt | +0,62 pt | +1,7 % |

L'écart entre la dernière ligne et les deux premières est exactement ce que la
reconnaissance évite.

### Embarquement dans le docx

Le `.docx` référence la police par son nom. `--embed-fonts` l'embarquera : on embarquerait
alors la police **de la bibliothèque**, complète et pourvue d'un cmap, jamais le
sous-ensemble cassé du PDF. `pdfexact/render/fonts_embed.py` fournit déjà l'obfuscation
`.odttf` attendue par Word, testée mais non branchée.

## 9. Gestion des erreurs

Aucune page ne peut faire échouer la conversion entière. Chaque page est traitée dans un
bloc protégé : en cas d'échec, elle est remplacée par un raster pleine page et un
avertissement est collecté.

La conversion se termine sur un rapport : nombre de pages traitées, pages dégradées avec
leur motif, polices non embarquées, clusters rastérisés. Le rapport est affiché en fin de
commande et sérialisable via `--report`.

`--strict` renverse ce comportement : la première erreur interrompt la conversion.

## 10. Stratégie de test

La fidélité se mesure ; elle ne s'affirme pas. Quatre niveaux :

**Régression visuelle — le test qui décide.** Le `.docx` produit est converti en PDF par
LibreOffice headless, les deux PDF sont rendus en images page par page, et comparés par
SSIM. Le seuil de départ est 0,95 par page, ajusté à la hausse une fois la chaîne stable ;
il est déclaré par document de référence, pour qu'un PDF réputé difficile puisse être
suivi sans bloquer la suite. Le corpus de PDF de référence est versionné avec le projet et
couvre les cas de la section 2.

**Tests unitaires des extracteurs.** De petits PDF fabriqués à la main, dont on connaît le
contenu exact, alimentent chaque extracteur ; on vérifie l'IR produit.

**Tests golden du writer.** Un IR fixe en entrée, un fragment `document.xml` attendu en
sortie. Détecte immédiatement toute régression de génération XML.

**Tests de contrat.** Chaque `.docx` produit est validé contre le schéma OOXML et doit
s'ouvrir sans réparation.

LibreOffice n'est requis que pour le premier niveau, en développement. Il n'est pas une
dépendance d'exécution.

## 11. Ordre d'implémentation

L'ordre suit le risque, du plus incertain au plus mécanique :

1. Prototype polices : extraction, réparation du cmap, embarquement, ouverture dans Word.
   Décide si l'embarquement est retenu ou si l'on livre le mode repli.
2. IR et geometry — le contrat, avec ses tests unitaires.
3. Squelette du package OOXML : un docx vide valide, aux bonnes dimensions de page.
4. Chaîne texte de bout en bout : extraction, zones de texte par ligne, correction de
   largeur. Premier score SSIM mesurable.
5. Images, avec déduplication.
6. Vectoriel `custGeom`.
7. Clustering, scoring et repli raster.
8. Liens.
9. CLI, rapport, gestion des erreurs par page.
