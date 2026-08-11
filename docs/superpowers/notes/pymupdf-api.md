# Sonde de l'API PyMuPDF

Version installée : **PyMuPDF 1.28.2** (MuPDF 1.28.2), Python 3.10.20.
Le plan d'implémentation a été écrit contre 1.24. Cette note dit ce que 1.28.2 retourne
réellement. En cas de contradiction, cette note fait foi.

Sonde : `scripts/probe_pymupdf.py <fichier.pdf> [numero_page]`.
Exécutée sur un PDF composite généré (texte deux polices, rectangle rempli, ligne, courbe
de Bézier, une image placée deux fois, un lien URI).

## Divergences avec le plan

### 1. `import fitz` est déprécié

L'alias historique fonctionne toujours mais émet un avertissement à chaque import.
Tout le code utilise `import pymupdf`. Le plan a été corrigé (69 occurrences).

### 2. Le dictionnaire de span ne contient PAS de clé `xref`

Clés réellement présentes :

```
size, flags, bidi, char_flags, font, color, alpha, ascender, descender, text, origin, bbox
```

Le plan proposait `span.get("xref", 0)` comme chemin principal pour relier un span à sa
police, avec une correspondance par nom en repli. Le chemin principal est mort : il
retourne toujours 0. **La correspondance par nom est le seul chemin.** La clé `font`
porte le nom PostScript (`"Helvetica"`), à rapprocher du champ `basefont` de
`get_fonts(full=True)`.

### 3. Le span porte `ascender` et `descender` — le plan les recalculait

Valeurs observées pour Helvetica 12 : `ascender = 1.075`, `descender = -0.299`, exprimées
en fraction de cadratin. L'ascendante en points est donc `span["ascender"] * span["size"]`.

C'est mieux que la valeur reconstruite via fontTools que prévoyait le plan : c'est
exactement la métrique que MuPDF a utilisée pour poser le texte, donc la baseline retombe
juste par construction. `pdfexact.extract.fonts.ascendante_pt` reste utile comme repli
quand la clé est absente, mais n'est plus le chemin principal.

### 4. `get_images(full=True)` liste les références, pas les images

Une image placée deux fois produit **deux entrées portant le même xref**, ne différant
que par leur nom de ressource (`fzImg0`, `fzImg1`) :

```
(10, 0, 4, 4, 8, 'ICCBased', '', 'fzImg0', '', 0)
(10, 0, 4, 4, 8, 'ICCBased', '', 'fzImg1', '', 0)
```

`get_image_rects(10)` retourne les 2 placements — une seule fois, pour le xref.
Itérer sur `get_images()` sans dédupliquer les xrefs compte donc chaque placement autant
de fois qu'il y a d'entrées : 4 au lieu de 2 ici. Le plan a été corrigé.

## Conforme au plan

| API | Constat |
|---|---|
| `page.rect` | `Rect(0, 0, 595, 842)`, `.width` / `.height` en points |
| `get_drawings()` items | opérateurs `l`, `c`, `re` observés ; `re` porte `(op, Rect, orientation)` |
| `get_drawings()` couleurs | `fill` et `color` en triplets 0..1 ; `width` en points |
| `dashes` | `"[] 0"` quand plein — le test `dashes != "[] 0"` du plan est correct |
| `get_links()` | `kind=2` pour URI, clés `from` (Rect), `uri`, `xref`, `id` |
| `extract_font(xref)` | retourne `(nom, extension, type, octets)` |
| `xref_get_key(page.xref, "Resources/Shading")` | `('null', 'null')` en l'absence de shading — la détection du plan est correcte |

Clés supplémentaires disponibles, non exploitées pour l'instant : `alpha` sur les spans
(transparence du texte), `lineCap` / `lineJoin` sur les dessins, `type` (`"f"`, `"s"`,
`"fs"`) qui dit si un dessin est rempli, contouré, ou les deux.

## Non vérifié

**L'embarquement de polices reste entièrement à valider.** Les PDF de test sont générés
par PyMuPDF et n'utilisent que les polices base-14, non embarquées :

```
(5, 'n/a', 'Type1', 'Helvetica', 'helv', 'WinAnsiEncoding', 0)  -> ext='n/a' octets=0
(7, 'n/a', 'Type1', 'Times-Roman', 'tiro', 'WinAnsiEncoding', 0) -> ext='n/a' octets=0
```

La Task 3 exige des PDF réels portant des polices embarquées pour trancher. La sonde
imprime déjà le nombre d'entrées du cmap de chaque police extraite : c'est la mesure qui
décide.
