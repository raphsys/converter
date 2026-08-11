# Plan d'implémentation — pdfexact

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire `pdfexact`, une bibliothèque Python et une commande en ligne de commande qui convertissent un PDF natif en `.docx` visuellement fidèle, par positionnement absolu de chaque élément.

**Architecture:** Pipeline en trois temps — les extracteurs lisent le PDF via PyMuPDF et produisent une représentation intermédiaire (IR) entièrement en EMU ; le writer transforme l'IR en package OOXML écrit à la main. L'IR est le seul contrat entre les deux moitiés : aucun extracteur ne connaît OOXML, aucun module de rendu ne connaît PyMuPDF. Chaque page devient une section Word contenant un paragraphe vide et des formes ancrées en position absolue, de sorte que rien ne soit dans le flux et que rien ne puisse refluer.

**Tech Stack:** Python 3.10, PyMuPDF (extraction et rendu), fontTools (métriques et réparation de polices), Pillow (encodage PNG). Tests : pytest, LibreOffice headless (`/usr/bin/soffice`, déjà présent) et scikit-image pour la comparaison SSIM.

## Global Constraints

- Python 3.10 — la version du venv existant `.converter/` (3.10.20).
- Toutes les coordonnées et dimensions de l'IR sont en EMU (entiers). Seule exception : `Span.size_pt`, en points, parce que Word attend des demi-points.
- Constantes de conversion : `EMU_PER_PT = 12700`, `TWIPS_PER_PT = 20`.
- Aucun élément dans le flux du document : tout est `<wp:anchor>` positionné `relativeFrom="page"`.
- Le texte n'est jamais rastérisé, même au-dessus d'une zone rastérisée.
- Aucune page ne peut faire échouer la conversion, sauf sous `--strict`.
- Les couleurs circulent en chaînes hexadécimales `"RRGGBB"` majuscules, sans `#`.
- Nom du paquet : `pdfexact`. Les tests vivent dans `tests/`, en miroir de l'arborescence source.
- Un commit par tâche, message en anglais, format Conventional Commits.

---

## Contexte pour l'implémenteur

Trois choses à savoir avant de commencer, qui ne se devinent pas en lisant le code.

**Le réseau est bloqué dans l'environnement où ce plan a été écrit.** `pip install` échoue par timeout. La Task 1 doit être exécutée depuis un environnement disposant d'un accès à PyPI. Tant qu'elle n'est pas passée, aucune autre tâche n'est exécutable.

**Les signatures exactes de l'API PyMuPDF doivent être vérifiées, pas supposées.** Ce plan cite les appels tels qu'ils existent dans les versions récentes (`page.get_text("dict")`, `page.get_drawings()`, `doc.extract_font()`), mais les structures retournées ont évolué entre versions. La Task 2 est une sonde qui imprime ce que la version installée retourne réellement. Si elle contredit ce plan, la sonde a raison — signale l'écart et adapte.

**La Task 3 est un point de décision, pas seulement du code.** Elle détermine si l'embarquement de polices est retenu. Si elle échoue, le projet continue en mode police système ; ce n'est pas un échec du projet.

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `pdfexact/geometry.py` | Conversions d'unités, `BBox` et opérations sur les boîtes |
| `pdfexact/ir.py` | Les dataclasses de l'IR — le contrat |
| `pdfexact/report.py` | Collecte des avertissements, sérialisation JSON |
| `pdfexact/extract/document.py` | Ouverture du PDF, boucle sur les pages, assemblage du `Document` |
| `pdfexact/extract/fonts.py` | Extraction des polices, métriques, mesure de largeur |
| `pdfexact/extract/text.py` | `page.get_text("dict")` → `TextBox` / `Line` / `Span` |
| `pdfexact/extract/images.py` | Images bitmap, rectangles de placement, déduplication |
| `pdfexact/extract/vector.py` | `page.get_drawings()` → `ShapeEl`, regroupement en clusters |
| `pdfexact/extract/links.py` | `page.get_links()` → liens de span ou `LinkZone` |
| `pdfexact/render/package.py` | Écriture du zip OOXML, gestion des relations |
| `pdfexact/render/docx_writer.py` | `Document` → `document.xml` |
| `pdfexact/render/drawing.py` | Fragments DrawingML : zone de texte, image, forme |
| `pdfexact/render/fonts_embed.py` | Obfuscation `.odttf`, `fontTable.xml` |
| `pdfexact/fallback/rasterize.py` | Rendu d'une région en PNG |
| `pdfexact/cli.py` | Analyse des arguments, orchestration |
| `tests/conftest.py` | Fabriques de PDF de test |
| `tests/visual/harness.py` | Conversion docx → PDF, rendu, comparaison SSIM |

---

### Task 1 : squelette du projet et dépendances

**Files:**
- Create: `pyproject.toml`
- Create: `pdfexact/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: rien.
- Produces: le paquet importable `pdfexact`, et `pytest` exécutable depuis la racine.

**Prérequis : accès réseau à PyPI.** Cette tâche est la seule qui en dépend.

- [ ] **Step 1 : créer `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "pdfexact"
version = "0.1.0"
description = "Convertisseur PDF natif vers DOCX à fidélité visuelle"
requires-python = ">=3.10"
dependencies = [
    "pymupdf>=1.24",
    "fonttools>=4.50",
    "pillow>=10.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "scikit-image>=0.22",
    "numpy>=1.26",
]

[project.scripts]
pdfexact = "pdfexact.cli:main"

[tool.setuptools.packages.find]
include = ["pdfexact*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2 : installer**

```bash
.converter/bin/pip install -e ".[dev]"
```

Attendu : installation réussie. En cas d'échec réseau, s'arrêter ici et le signaler — aucune tâche suivante n'est exécutable.

- [ ] **Step 3 : écrire le test de fumée**

```python
# tests/test_smoke.py
def test_dependances_importables():
    import pymupdf
    import fontTools
    import PIL

    assert pymupdf.__doc__


def test_paquet_importable():
    import pdfexact

    assert pdfexact.__name__ == "pdfexact"
```

- [ ] **Step 4 : créer les fichiers de paquet vides**

`pdfexact/__init__.py` et `tests/__init__.py`, tous deux vides.

- [ ] **Step 5 : lancer les tests**

Run: `.converter/bin/pytest tests/test_smoke.py -v`
Attendu : 2 passed.

- [ ] **Step 6 : commit**

```bash
git add pyproject.toml pdfexact/ tests/
git commit -m "chore: scaffold pdfexact package and pin dependencies"
```

---

### Task 2 : sonde de l'API PyMuPDF et corpus de test

**Files:**
- Create: `tests/conftest.py`
- Create: `scripts/probe_pymupdf.py`
- Create: `docs/superpowers/notes/pymupdf-api.md`

**Interfaces:**
- Consumes: le paquet de la Task 1.
- Produces: les fixtures pytest `pdf_texte`, `pdf_vectoriel`, `pdf_image`, `pdf_liens` — chacune renvoie un `pathlib.Path` vers un PDF généré ; et une note documentant les structures réellement retournées par la version installée.

- [ ] **Step 1 : écrire les fabriques de PDF de test**

```python
# tests/conftest.py
import pymupdf
import pytest


@pytest.fixture
def pdf_texte(tmp_path):
    """Une page A4, deux lignes de texte de polices et corps différents."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Ligne en Helvetica douze", fontname="helv", fontsize=12)
    page.insert_text((72, 200), "Ligne en Times dix-huit", fontname="tiro", fontsize=18)
    chemin = tmp_path / "texte.pdf"
    doc.save(chemin)
    doc.close()
    return chemin


@pytest.fixture
def pdf_vectoriel(tmp_path):
    """Un rectangle rempli, une ligne, une courbe."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    forme = page.new_shape()
    forme.draw_rect(pymupdf.Rect(50, 50, 200, 150))
    forme.finish(color=(0, 0, 0), fill=(1, 0, 0), width=2)
    forme.draw_line(pymupdf.Point(50, 200), pymupdf.Point(300, 260))
    forme.finish(color=(0, 0, 1), width=3)
    forme.commit()
    chemin = tmp_path / "vectoriel.pdf"
    doc.save(chemin)
    doc.close()
    return chemin


@pytest.fixture
def pdf_image(tmp_path):
    """Une image PNG 4x4 placée deux fois — vérifie la déduplication."""
    import io

    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 128, 255)).save(tampon, format="PNG")
    octets = tampon.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=octets)
    page.insert_image(pymupdf.Rect(200, 50, 300, 150), stream=octets)
    chemin = tmp_path / "image.pdf"
    doc.save(chemin)
    doc.close()
    return chemin


@pytest.fixture
def pdf_liens(tmp_path):
    """Un lien externe posé sur une zone rectangulaire."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Site officiel", fontname="helv", fontsize=12)
    page.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": pymupdf.Rect(72, 88, 200, 104),
        "uri": "https://example.org/",
    })
    chemin = tmp_path / "liens.pdf"
    doc.save(chemin)
    doc.close()
    return chemin
```

- [ ] **Step 2 : vérifier que les fixtures produisent des PDF valides**

```python
# tests/test_fixtures.py
import pymupdf


def test_les_fixtures_produisent_des_pdf_ouvrables(pdf_texte, pdf_vectoriel, pdf_image, pdf_liens):
    for chemin in (pdf_texte, pdf_vectoriel, pdf_image, pdf_liens):
        doc = pymupdf.open(chemin)
        assert doc.page_count == 1
        doc.close()
```

Run: `.converter/bin/pytest tests/test_fixtures.py -v`
Attendu : PASS.

- [ ] **Step 3 : écrire la sonde**

```python
# scripts/probe_pymupdf.py
"""Imprime les structures réellement retournées par la version installée de PyMuPDF.

Sert de vérification : le plan d'implémentation cite ces API de mémoire, cette sonde
dit ce qu'elles renvoient vraiment. En cas de divergence, la sonde a raison.
"""
import json
import sys

import pymupdf


def main(chemin_pdf):
    print("version PyMuPDF :", pymupdf.version)
    doc = pymupdf.open(chemin_pdf)
    page = doc[0]

    print("\n--- page.rect ---")
    print(page.rect)

    print("\n--- get_text('dict') : premier span ---")
    donnees = page.get_text("dict")
    for bloc in donnees["blocks"]:
        if bloc.get("type") == 0:
            print(json.dumps(bloc["lines"][0]["spans"][0], default=str, indent=2))
            break

    print("\n--- get_drawings() : premier dessin ---")
    dessins = page.get_drawings()
    if dessins:
        print(json.dumps(dessins[0], default=str, indent=2))

    print("\n--- get_images(full=True) ---")
    print(page.get_images(full=True))

    print("\n--- get_links() ---")
    print(page.get_links())

    print("\n--- get_fonts(full=True) et extract_font ---")
    for police in page.get_fonts(full=True):
        print(police)
        resultat = doc.extract_font(police[0])
        print("  extract_font ->", resultat[0], resultat[1], resultat[2], "octets:", len(resultat[3]))

    print("\n--- xref_get_key(page, 'Resources/Shading') ---")
    print(doc.xref_get_key(page.xref, "Resources/Shading"))

    doc.close()


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 4 : exécuter la sonde sur un PDF réel**

```bash
.converter/bin/python scripts/probe_pymupdf.py <un-vrai-pdf.pdf>
```

Attendu : une sortie complète, sans exception. Noter en particulier les clés exactes du dictionnaire de span (`size`, `flags`, `font`, `color`, `origin`, `bbox`, `text`) et la forme des items de `get_drawings()`.

- [ ] **Step 5 : consigner les résultats**

Écrire `docs/superpowers/notes/pymupdf-api.md` avec la version installée, la sortie de la sonde, et une section « Divergences avec le plan » listant tout écart constaté. Si aucune divergence : le dire explicitement.

- [ ] **Step 6 : commit**

```bash
git add tests/conftest.py tests/test_fixtures.py scripts/probe_pymupdf.py docs/superpowers/notes/
git commit -m "test: add PDF fixtures and PyMuPDF API probe"
```

---

### Task 3 : prototype d'embarquement de polices — point de décision

**Files:**
- Create: `pdfexact/render/fonts_embed.py`
- Create: `pdfexact/render/__init__.py`
- Create: `tests/render/test_fonts_embed.py`
- Create: `tests/render/__init__.py`
- Create: `docs/superpowers/notes/decision-polices.md`

**Interfaces:**
- Consumes: le paquet de la Task 1.
- Produces: `obfusquer_police(octets: bytes, guid: str) -> bytes` et `nouveau_guid() -> str`, utilisés par la Task 6.

Cette tâche décide si l'embarquement de polices est retenu pour le reste du projet. Elle est délibérément placée en premier parce que c'est le risque technique principal identifié dans la spec.

- [ ] **Step 1 : écrire le test de l'obfuscation**

```python
# tests/render/test_fonts_embed.py
from pdfexact.render.fonts_embed import nouveau_guid, obfusquer_police


def test_obfuscation_est_son_propre_inverse():
    original = bytes(range(64))
    guid = "12345678-1234-5678-1234-567812345678"

    une_fois = obfusquer_police(original, guid)
    deux_fois = obfusquer_police(une_fois, guid)

    assert deux_fois == original


def test_obfuscation_ne_touche_que_les_32_premiers_octets():
    original = bytes(64)
    guid = "12345678-1234-5678-1234-567812345678"

    resultat = obfusquer_police(original, guid)

    assert resultat[32:] == original[32:]
    assert resultat[:32] != original[:32]


def test_guid_a_le_format_attendu():
    guid = nouveau_guid()

    assert len(guid) == 38
    assert guid.startswith("{") and guid.endswith("}")
    assert guid.count("-") == 4
```

- [ ] **Step 2 : lancer le test pour le voir échouer**

Run: `.converter/bin/pytest tests/render/test_fonts_embed.py -v`
Attendu : FAIL, `ModuleNotFoundError: No module named 'pdfexact.render'`.

- [ ] **Step 3 : implémenter**

```python
# pdfexact/render/fonts_embed.py
"""Embarquement de polices dans un package OOXML.

Word attend les polices embarquées sous forme obfusquée (extension .odttf) : les 32
premiers octets du fichier sont combinés par XOR avec une clé de 16 octets dérivée du
GUID déclaré dans fontTable.xml. L'opération est involutive.
"""
import uuid


def nouveau_guid() -> str:
    """Retourne un GUID au format attendu par w:fontKey, accolades comprises."""
    return "{" + str(uuid.uuid4()).upper() + "}"


def _cle_depuis_guid(guid: str) -> bytes:
    hexa = guid.strip("{}").replace("-", "")
    if len(hexa) != 32:
        raise ValueError(f"GUID malformé : {guid!r}")
    return bytes.fromhex(hexa)[::-1]


def obfusquer_police(octets: bytes, guid: str) -> bytes:
    """Obfusque (ou désobfusque — l'opération est involutive) une police pour Word."""
    cle = _cle_depuis_guid(guid)
    donnees = bytearray(octets)
    for i in range(min(32, len(donnees))):
        donnees[i] ^= cle[i % 16]
    return bytes(donnees)
```

- [ ] **Step 4 : lancer le test**

Run: `.converter/bin/pytest tests/render/test_fonts_embed.py -v`
Attendu : 3 passed.

- [ ] **Step 5 : valider l'algorithme contre un vrai docx**

Le test ci-dessus prouve l'involution, pas la conformité à Word. Vérification réelle :

```bash
# Produire dans Word (ou LibreOffice avec embarquement activé) un .docx avec police embarquée,
# puis extraire son fontTable.xml et le .odttf correspondant :
unzip -o reference.docx -d /tmp/ref
cat /tmp/ref/word/fontTable.xml     # relever le w:fontKey
ls /tmp/ref/word/fonts/             # le fichier .odttf
```

Puis désobfusquer le `.odttf` avec `obfusquer_police(octets, cle_relevee)` et vérifier que le résultat commence par une signature de police valide : `\x00\x01\x00\x00` (TrueType) ou `OTTO` (CFF).

Si la signature n'apparaît pas, l'algorithme est faux — ne pas continuer sans l'avoir corrigé.

- [ ] **Step 6 : évaluer la réparation du cmap sur des PDF réels**

Sur trois PDF réels différents, pour chaque police embarquée :

```bash
.converter/bin/python scripts/probe_pymupdf.py <pdf>   # relever l'extension retournée par extract_font
```

Consigner, par police : l'extension (`ttf`, `otf`, `cff`, `pfb`, `n/a`), et si la police a une table `cmap` exploitable — à vérifier en chargeant les octets dans `fontTools.ttLib.TTFont` et en lisant `font.getBestCmap()`.

- [ ] **Step 7 : rendre la décision**

Écrire `docs/superpowers/notes/decision-polices.md` avec : le tableau des polices observées, si l'obfuscation est validée contre un docx de référence, et la décision finale — `EMBARQUEMENT_RETENU = True/False`.

Si `False`, toutes les tâches suivantes utilisent uniquement le mode police système, et l'option `--no-embed-fonts` devient le comportement par défaut. Le reste du plan reste valable : la mesure de largeur de la Task 6 fonctionne à l'identique sur une police système.

- [ ] **Step 8 : commit**

```bash
git add pdfexact/render/ tests/render/ docs/superpowers/notes/decision-polices.md
git commit -m "feat: add OOXML font obfuscation and decide on font embedding"
```

---

### Task 4 : géométrie et conversions d'unités

**Files:**
- Create: `pdfexact/geometry.py`
- Create: `tests/test_geometry.py`

**Interfaces:**
- Consumes: rien.
- Produces: `EMU_PER_PT`, `TWIPS_PER_PT`, `pt_vers_emu(float) -> int`, `pt_vers_twips(float) -> int`, `emu_vers_pt(int) -> float`, `BBox(x0, y0, x1, y1)` avec `.largeur` / `.hauteur`, `bbox_depuis_rect(rect) -> BBox`, `union(BBox, BBox) -> BBox`, `se_chevauchent(BBox, BBox) -> bool`.

- [ ] **Step 1 : écrire le test**

```python
# tests/test_geometry.py
import pymupdf
import pytest

from pdfexact.geometry import (
    EMU_PER_PT,
    BBox,
    bbox_depuis_rect,
    emu_vers_pt,
    pt_vers_emu,
    pt_vers_twips,
    se_chevauchent,
    union,
)


def test_un_pouce_vaut_914400_emu():
    assert pt_vers_emu(72) == 914400


def test_conversion_en_twips():
    assert pt_vers_twips(12) == 240


def test_conversion_retour_en_points():
    assert emu_vers_pt(EMU_PER_PT) == pytest.approx(1.0)


def test_conversion_arrondit_au_lieu_de_tronquer():
    assert pt_vers_emu(0.00005) == 1


def test_bbox_expose_largeur_et_hauteur():
    boite = BBox(100, 200, 400, 600)

    assert boite.largeur == 300
    assert boite.hauteur == 400


def test_bbox_depuis_rect_convertit_en_emu():
    boite = bbox_depuis_rect(pymupdf.Rect(0, 0, 72, 144))

    assert boite.x1 == 914400
    assert boite.y1 == 1828800


def test_union_englobe_les_deux_boites():
    resultat = union(BBox(0, 0, 10, 10), BBox(5, 5, 20, 30))

    assert resultat == BBox(0, 0, 20, 30)


def test_chevauchement_detecte():
    assert se_chevauchent(BBox(0, 0, 10, 10), BBox(5, 5, 15, 15))


def test_boites_disjointes_ne_se_chevauchent_pas():
    assert not se_chevauchent(BBox(0, 0, 10, 10), BBox(20, 20, 30, 30))


def test_boites_qui_se_touchent_ne_se_chevauchent_pas():
    assert not se_chevauchent(BBox(0, 0, 10, 10), BBox(10, 0, 20, 10))
```

- [ ] **Step 2 : lancer le test pour le voir échouer**

Run: `.converter/bin/pytest tests/test_geometry.py -v`
Attendu : FAIL, `ModuleNotFoundError: No module named 'pdfexact.geometry'`.

- [ ] **Step 3 : implémenter**

```python
# pdfexact/geometry.py
"""Conversions d'unités et boîtes englobantes.

Toute la chaîne travaille en EMU (English Metric Units) : 914400 par pouce, 12700 par
point. La conversion depuis les points de PyMuPDF se fait ici et nulle part ailleurs,
pour qu'il n'existe qu'un seul endroit où se tromper d'unité.
"""
from dataclasses import dataclass

EMU_PER_PT = 12700
TWIPS_PER_PT = 20


def pt_vers_emu(valeur: float) -> int:
    return round(valeur * EMU_PER_PT)


def pt_vers_twips(valeur: float) -> int:
    return round(valeur * TWIPS_PER_PT)


def emu_vers_pt(valeur: int) -> float:
    return valeur / EMU_PER_PT


@dataclass(frozen=True)
class BBox:
    """Boîte englobante en EMU, origine en haut à gauche — même convention que Word."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def largeur(self) -> int:
        return self.x1 - self.x0

    @property
    def hauteur(self) -> int:
        return self.y1 - self.y0


def bbox_depuis_rect(rect) -> BBox:
    """Convertit un pymupdf.Rect exprimé en points vers une BBox en EMU."""
    return BBox(
        pt_vers_emu(rect.x0),
        pt_vers_emu(rect.y0),
        pt_vers_emu(rect.x1),
        pt_vers_emu(rect.y1),
    )


def union(a: BBox, b: BBox) -> BBox:
    return BBox(min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1))


def se_chevauchent(a: BBox, b: BBox) -> bool:
    """Vrai si les deux boîtes ont une intersection d'aire non nulle."""
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1
```

- [ ] **Step 4 : lancer le test**

Run: `.converter/bin/pytest tests/test_geometry.py -v`
Attendu : 10 passed.

- [ ] **Step 5 : commit**

```bash
git add pdfexact/geometry.py tests/test_geometry.py
git commit -m "feat: add EMU geometry primitives"
```

---

### Task 5 : la représentation intermédiaire

**Files:**
- Create: `pdfexact/ir.py`
- Create: `tests/test_ir.py`

**Interfaces:**
- Consumes: `pdfexact.geometry.BBox`.
- Produces: `FontRef`, `FontAsset`, `MediaItem`, `Span`, `Line`, `TextBox`, `ImageEl`, `ShapeEl`, `RasterEl`, `LinkZone`, `Page`, `Document`, et l'alias `Element`. Toutes les tâches suivantes construisent ou consomment ces types.

- [ ] **Step 1 : écrire le test**

```python
# tests/test_ir.py
from pdfexact.geometry import BBox
from pdfexact.ir import (
    Document,
    FontAsset,
    FontRef,
    Line,
    MediaItem,
    Page,
    Span,
    TextBox,
)


def _span_minimal():
    return Span(
        texte="bonjour",
        police=FontRef(font_id="f0", famille="Arial", gras=False, italique=False),
        size_pt=12.0,
        couleur="000000",
    )


def test_span_a_un_espacement_nul_par_defaut():
    assert _span_minimal().espacement_twips == 0


def test_span_na_pas_de_lien_par_defaut():
    assert _span_minimal().lien is None


def test_une_page_porte_ses_elements_en_ordre_de_superposition():
    boite = BBox(0, 0, 100, 100)
    ligne = Line(bbox=boite, spans=[_span_minimal()], hauteur_ligne_emu=100, largeur_cible_emu=100)
    bloc = TextBox(bbox=boite, lignes=[ligne])
    page = Page(index=0, largeur_emu=7560000, hauteur_emu=10692000, elements=[bloc])

    assert page.elements[0] is bloc


def test_le_document_expose_ses_registres():
    doc = Document(
        pages=[],
        media={"m0": MediaItem(media_ref="m0", donnees=b"\x89PNG", extension="png")},
        polices={"f0": FontAsset(font_id="f0", famille="Arial", donnees=None, extension="", embarquee=False)},
    )

    assert doc.media["m0"].extension == "png"
    assert doc.polices["f0"].embarquee is False


def test_document_vide_est_constructible():
    doc = Document(pages=[], media={}, polices={})

    assert doc.pages == []
```

- [ ] **Step 2 : lancer le test pour le voir échouer**

Run: `.converter/bin/pytest tests/test_ir.py -v`
Attendu : FAIL, `ModuleNotFoundError: No module named 'pdfexact.ir'`.

- [ ] **Step 3 : implémenter**

```python
# pdfexact/ir.py
"""Représentation intermédiaire — le contrat entre extraction et rendu.

Les extracteurs produisent ces objets, le writer les consomme. Aucun des deux côtés ne
connaît l'autre. Toutes les dimensions sont en EMU, à l'exception de Span.size_pt, en
points, parce que Word exprime les corps de police en demi-points.
"""
from dataclasses import dataclass, field
from typing import Union

from pdfexact.geometry import BBox

# Une commande de chemin : un opérateur et ses points, en EMU absolus.
# Opérateurs : "move", "line", "cubic", "quad", "close".
PathCommand = tuple[str, tuple[tuple[int, int], ...]]
Path = list[PathCommand]


@dataclass(frozen=True)
class FontAsset:
    """Une police du document, embarquée ou substituée par une police système."""

    font_id: str
    famille: str
    donnees: bytes | None
    extension: str
    embarquee: bool


@dataclass(frozen=True)
class FontRef:
    """Référence d'un span vers une police, avec son style."""

    font_id: str
    famille: str
    gras: bool
    italique: bool


@dataclass(frozen=True)
class MediaItem:
    """Un binaire à écrire dans word/media/."""

    media_ref: str
    donnees: bytes
    extension: str


@dataclass
class Span:
    texte: str
    police: FontRef
    size_pt: float
    couleur: str
    espacement_twips: int = 0
    lien: str | None = None


@dataclass
class Line:
    """Une ligne de texte. Devient une zone de texte OOXML à elle seule."""

    bbox: BBox
    spans: list[Span]
    hauteur_ligne_emu: int
    largeur_cible_emu: int


@dataclass
class TextBox:
    """Bloc logique de texte. Regroupement seulement — le writer rend ligne par ligne."""

    bbox: BBox
    lignes: list[Line]


@dataclass
class ImageEl:
    bbox: BBox
    media_ref: str


@dataclass
class ShapeEl:
    bbox: BBox
    chemins: list[Path]
    remplissage: str | None
    contour: str | None
    epaisseur_emu: int
    pointilles: str | None = None
    alpha: float = 1.0


@dataclass
class RasterEl:
    """Région rastérisée en repli. Jamais produit par un extracteur."""

    bbox: BBox
    media_ref: str


@dataclass
class LinkZone:
    """Lien couvrant une zone sans texte. Les liens sur du texte vivent dans Span.lien."""

    bbox: BBox
    uri: str | None = None
    page_cible: int | None = None


Element = Union[TextBox, ImageEl, ShapeEl, RasterEl, LinkZone]


@dataclass
class Page:
    index: int
    largeur_emu: int
    hauteur_emu: int
    elements: list[Element] = field(default_factory=list)


@dataclass
class Document:
    pages: list[Page] = field(default_factory=list)
    media: dict[str, MediaItem] = field(default_factory=dict)
    polices: dict[str, FontAsset] = field(default_factory=dict)
```

- [ ] **Step 4 : lancer le test**

Run: `.converter/bin/pytest tests/test_ir.py -v`
Attendu : 5 passed.

- [ ] **Step 5 : commit**

```bash
git add pdfexact/ir.py tests/test_ir.py
git commit -m "feat: define the intermediate representation"
```

---

### Task 6 : package OOXML minimal — un docx vide et valide

**Files:**
- Create: `pdfexact/render/package.py`
- Create: `pdfexact/render/docx_writer.py`
- Create: `tests/render/test_package.py`

**Interfaces:**
- Consumes: `pdfexact.ir.Document`, `pdfexact.geometry.pt_vers_twips`.
- Produces: `ecrire_docx(document: Document, chemin) -> None`, `GestionnaireRelations` avec `.ajouter(cible: str, type_rel: str) -> str`, et `construire_document_xml(document: Document) -> str`.

Cette tâche produit un docx qui s'ouvre, aux bonnes dimensions de page, mais vide. C'est le socle : toutes les tâches de rendu suivantes ajoutent du contenu dans `construire_document_xml`.

- [ ] **Step 1 : écrire le test**

```python
# tests/render/test_package.py
import subprocess
import zipfile
from xml.etree import ElementTree

from pdfexact.ir import Document, Page
from pdfexact.render.package import GestionnaireRelations, ecrire_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _document_deux_pages():
    return Document(
        pages=[
            Page(index=0, largeur_emu=7560000, hauteur_emu=10692000),
            Page(index=1, largeur_emu=7560000, hauteur_emu=10692000),
        ]
    )


def test_le_zip_contient_les_parties_obligatoires(tmp_path):
    sortie = tmp_path / "vide.docx"

    ecrire_docx(_document_deux_pages(), sortie)

    with zipfile.ZipFile(sortie) as z:
        noms = set(z.namelist())
    assert "[Content_Types].xml" in noms
    assert "_rels/.rels" in noms
    assert "word/document.xml" in noms
    assert "word/_rels/document.xml.rels" in noms


def test_le_document_xml_est_bien_forme(tmp_path):
    sortie = tmp_path / "vide.docx"

    ecrire_docx(_document_deux_pages(), sortie)

    with zipfile.ZipFile(sortie) as z:
        ElementTree.fromstring(z.read("word/document.xml"))


def test_la_taille_de_page_est_en_twips(tmp_path):
    sortie = tmp_path / "vide.docx"

    ecrire_docx(_document_deux_pages(), sortie)

    with zipfile.ZipFile(sortie) as z:
        racine = ElementTree.fromstring(z.read("word/document.xml"))
    tailles = racine.iter(f"{W}pgSz")
    premiere = next(tailles)
    # 7560000 EMU = 595.28 pt = 11906 twips
    assert premiere.get(f"{W}w") == "11906"


def test_une_section_par_page(tmp_path):
    sortie = tmp_path / "vide.docx"

    ecrire_docx(_document_deux_pages(), sortie)

    with zipfile.ZipFile(sortie) as z:
        racine = ElementTree.fromstring(z.read("word/document.xml"))
    assert len(list(racine.iter(f"{W}sectPr"))) == 2


def test_libreoffice_ouvre_le_fichier(tmp_path):
    sortie = tmp_path / "vide.docx"
    ecrire_docx(_document_deux_pages(), sortie)

    resultat = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(sortie)],
        capture_output=True,
        timeout=120,
    )

    assert resultat.returncode == 0
    assert (tmp_path / "vide.pdf").exists()


def test_le_gestionnaire_de_relations_numerote_a_partir_de_un():
    gestionnaire = GestionnaireRelations()

    premier = gestionnaire.ajouter("media/image1.png", "image")
    second = gestionnaire.ajouter("media/image2.png", "image")

    assert premier == "rId1"
    assert second == "rId2"
```

- [ ] **Step 2 : lancer le test pour le voir échouer**

Run: `.converter/bin/pytest tests/render/test_package.py -v`
Attendu : FAIL, `ModuleNotFoundError: No module named 'pdfexact.render.package'`.

- [ ] **Step 3 : implémenter le gestionnaire de relations et l'écriture du zip**

```python
# pdfexact/render/package.py
"""Écriture du package OOXML.

Le docx est un zip de parties XML. On l'écrit à la main plutôt qu'avec python-docx :
cette bibliothèque ne sait produire ni ancres flottantes ni géométries personnalisées,
qui sont exactement ce dont l'approche a besoin.
"""
import zipfile
from pathlib import Path as CheminFS

from pdfexact.ir import Document
from pdfexact.render.docx_writer import construire_document_xml

TYPES_RELATIONS = {
    "image": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "hyperlink": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    "font": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
}

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS_RACINE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


class GestionnaireRelations:
    """Attribue les identifiants rId et collecte les relations de document.xml."""

    def __init__(self):
        self._entrees: list[tuple[str, str, str]] = []

    def ajouter(self, cible: str, type_rel: str, externe: bool = False) -> str:
        identifiant = f"rId{len(self._entrees) + 1}"
        self._entrees.append((identifiant, TYPES_RELATIONS[type_rel], cible))
        if externe:
            self._entrees[-1] = (identifiant, TYPES_RELATIONS[type_rel], cible + "\x00externe")
        return identifiant

    def vers_xml(self) -> str:
        lignes = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        ]
        for identifiant, type_rel, cible in self._entrees:
            if cible.endswith("\x00externe"):
                cible_reelle = cible[: -len("\x00externe")]
                lignes.append(
                    f'<Relationship Id="{identifiant}" Type="{type_rel}" '
                    f'Target="{cible_reelle}" TargetMode="External"/>'
                )
            else:
                lignes.append(
                    f'<Relationship Id="{identifiant}" Type="{type_rel}" Target="{cible}"/>'
                )
        lignes.append("</Relationships>")
        return "".join(lignes)


def ecrire_docx(document: Document, chemin) -> None:
    """Écrit le package complet à l'emplacement indiqué."""
    relations = GestionnaireRelations()
    corps = construire_document_xml(document, relations)

    with zipfile.ZipFile(CheminFS(chemin), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS_RACINE)
        z.writestr("word/document.xml", corps)
        z.writestr("word/_rels/document.xml.rels", relations.vers_xml())
        for item in document.media.values():
            z.writestr(f"word/media/{item.media_ref}.{item.extension}", item.donnees)
```

- [ ] **Step 4 : implémenter la génération de document.xml**

```python
# pdfexact/render/docx_writer.py
"""Transformation de l'IR en word/document.xml.

Chaque page devient une section : taille exacte, marges nulles, un paragraphe vide qui
sert uniquement de point d'ancrage. Tous les éléments sont des formes flottantes
positionnées par rapport à la page, donc hors du flux.
"""
from pdfexact.geometry import emu_vers_pt, pt_vers_twips
from pdfexact.ir import Document, Page

_ENTETE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document '
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'mc:Ignorable="wps">'
    "<w:body>"
)

_PIED = "</w:body></w:document>"


def _section_xml(page: Page) -> str:
    largeur = pt_vers_twips(emu_vers_pt(page.largeur_emu))
    hauteur = pt_vers_twips(emu_vers_pt(page.hauteur_emu))
    return (
        "<w:sectPr>"
        f'<w:pgSz w:w="{largeur}" w:h="{hauteur}"/>'
        '<w:pgMar w:top="0" w:right="0" w:bottom="0" w:left="0" '
        'w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr>"
    )


def construire_document_xml(document: Document, relations) -> str:
    """Assemble document.xml. `relations` est un GestionnaireRelations."""
    morceaux = [_ENTETE]

    for position, page in enumerate(document.pages):
        derniere = position == len(document.pages) - 1
        contenu_ancres = ""  # rempli par les tâches suivantes

        if derniere:
            # La dernière section se déclare au niveau du corps, pas dans un paragraphe.
            morceaux.append(f"<w:p><w:pPr></w:pPr>{contenu_ancres}</w:p>")
            morceaux.append(_section_xml(page))
        else:
            morceaux.append(
                f"<w:p><w:pPr>{_section_xml(page)}</w:pPr>{contenu_ancres}</w:p>"
            )

    morceaux.append(_PIED)
    return "".join(morceaux)
```

- [ ] **Step 5 : lancer les tests**

Run: `.converter/bin/pytest tests/render/test_package.py -v`
Attendu : 6 passed. Le test LibreOffice peut prendre une minute au premier lancement.

- [ ] **Step 6 : commit**

```bash
git add pdfexact/render/package.py pdfexact/render/docx_writer.py tests/render/test_package.py
git commit -m "feat: emit a minimal valid OOXML package with one section per page"
```

---

### Task 7 : harnais de régression visuelle

**Files:**
- Create: `tests/visual/__init__.py`
- Create: `tests/visual/harness.py`
- Create: `tests/visual/test_harness.py`

**Interfaces:**
- Consumes: rien du paquet ; utilise `soffice` et PyMuPDF.
- Produces: `docx_vers_pdf(chemin_docx, dossier_sortie) -> CheminFS`, `rendre_en_images(chemin_pdf, dpi=150) -> list[ndarray]`, `score_ssim(image_a, image_b) -> float`, `comparer(pdf_source, docx_produit, dpi=150) -> list[float]`.

Ce harnais est l'instrument de mesure du projet. Il est construit avant la première chaîne de rendu pour que celle-ci soit mesurable dès qu'elle existe.

- [ ] **Step 1 : écrire le test du harnais**

```python
# tests/visual/test_harness.py
import numpy as np
import pytest

from tests.visual.harness import comparer, docx_vers_pdf, rendre_en_images, score_ssim


def test_une_image_est_identique_a_elle_meme():
    image = np.random.default_rng(0).random((64, 64))

    assert score_ssim(image, image) == pytest.approx(1.0)


def test_deux_images_tres_differentes_ont_un_score_bas():
    noire = np.zeros((64, 64))
    blanche = np.ones((64, 64))

    assert score_ssim(noire, blanche) < 0.1


def test_images_de_tailles_differentes_sont_recadrees(pdf_texte, tmp_path):
    grande = np.zeros((100, 100))
    petite = np.zeros((80, 90))

    resultat = score_ssim(grande, petite)

    assert 0.0 <= resultat <= 1.0


def test_rendu_dun_pdf_donne_une_image_par_page(pdf_texte):
    images = rendre_en_images(pdf_texte, dpi=72)

    assert len(images) == 1
    assert images[0].ndim == 2


def test_conversion_docx_vers_pdf(tmp_path):
    from pdfexact.ir import Document, Page
    from pdfexact.render.package import ecrire_docx

    docx = tmp_path / "essai.docx"
    ecrire_docx(Document(pages=[Page(0, 7560000, 10692000)]), docx)

    resultat = docx_vers_pdf(docx, tmp_path)

    assert resultat.exists()
    assert resultat.suffix == ".pdf"


def test_comparer_retourne_un_score_par_page(pdf_texte, tmp_path):
    from pdfexact.ir import Document, Page
    from pdfexact.render.package import ecrire_docx

    docx = tmp_path / "essai.docx"
    ecrire_docx(Document(pages=[Page(0, 7560000, 10692000)]), docx)

    scores = comparer(pdf_texte, docx, dpi=72)

    assert len(scores) == 1
    assert 0.0 <= scores[0] <= 1.0
```

- [ ] **Step 2 : lancer le test pour le voir échouer**

Run: `.converter/bin/pytest tests/visual/test_harness.py -v`
Attendu : FAIL, `ModuleNotFoundError: No module named 'tests.visual.harness'`.

- [ ] **Step 3 : implémenter le harnais**

```python
# tests/visual/harness.py
"""Mesure de fidélité visuelle.

La fidélité se mesure, elle ne s'affirme pas. Le docx produit est reconverti en PDF par
LibreOffice, les deux PDF sont rendus en images, et comparés page à page par SSIM.

LibreOffice n'est requis qu'ici, en développement — jamais à l'exécution.
"""
import subprocess
from pathlib import Path as CheminFS

import pymupdf
import numpy as np
from skimage.metrics import structural_similarity

SEUIL_PAR_DEFAUT = 0.95


def docx_vers_pdf(chemin_docx, dossier_sortie) -> CheminFS:
    """Convertit un .docx en PDF via LibreOffice headless."""
    dossier_sortie = CheminFS(dossier_sortie)
    resultat = subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(dossier_sortie),
            str(chemin_docx),
        ],
        capture_output=True,
        timeout=180,
    )
    if resultat.returncode != 0:
        raise RuntimeError(f"LibreOffice a échoué : {resultat.stderr.decode(errors='replace')}")

    produit = dossier_sortie / (CheminFS(chemin_docx).stem + ".pdf")
    if not produit.exists():
        raise RuntimeError(f"PDF attendu absent : {produit}")
    return produit


def rendre_en_images(chemin_pdf, dpi: int = 150) -> list:
    """Rend chaque page en niveaux de gris, sous forme de tableau numpy."""
    doc = pymupdf.open(chemin_pdf)
    images = []
    try:
        for page in doc:
            pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            tableau = np.frombuffer(pixmap.samples, dtype=np.uint8)
            images.append(tableau.reshape(pixmap.height, pixmap.width).astype(np.float64) / 255.0)
    finally:
        doc.close()
    return images


def score_ssim(image_a, image_b) -> float:
    """Similarité structurelle entre deux images. Recadre à l'intersection si besoin."""
    hauteur = min(image_a.shape[0], image_b.shape[0])
    largeur = min(image_a.shape[1], image_b.shape[1])
    a = image_a[:hauteur, :largeur]
    b = image_b[:hauteur, :largeur]
    return float(structural_similarity(a, b, data_range=1.0))


def comparer(pdf_source, docx_produit, dpi: int = 150) -> list[float]:
    """Retourne un score SSIM par page, entre le PDF d'origine et le docx converti."""
    dossier = CheminFS(docx_produit).parent
    pdf_du_docx = docx_vers_pdf(docx_produit, dossier)

    images_source = rendre_en_images(pdf_source, dpi=dpi)
    images_produit = rendre_en_images(pdf_du_docx, dpi=dpi)

    nombre = min(len(images_source), len(images_produit))
    return [score_ssim(images_source[i], images_produit[i]) for i in range(nombre)]
```

- [ ] **Step 4 : lancer les tests**

Run: `.converter/bin/pytest tests/visual/test_harness.py -v`
Attendu : 6 passed. Les tests LibreOffice sont lents ; c'est normal.

- [ ] **Step 5 : commit**

```bash
git add tests/visual/
git commit -m "test: add SSIM-based visual regression harness"
```

---

### Task 8 : extraction et rendu du texte — première mesure de fidélité

**Files:**
- Create: `pdfexact/extract/__init__.py`
- Create: `pdfexact/extract/fonts.py`
- Create: `pdfexact/extract/text.py`
- Create: `pdfexact/extract/document.py`
- Modify: `pdfexact/render/docx_writer.py`
- Create: `pdfexact/render/drawing.py`
- Create: `tests/extract/__init__.py`
- Create: `tests/extract/test_fonts.py`
- Create: `tests/extract/test_text.py`
- Create: `tests/render/test_drawing.py`
- Create: `tests/visual/test_fidelite_texte.py`

**Interfaces:**
- Consumes: `BBox`, `bbox_depuis_rect`, `pt_vers_emu`, l'IR complet, `GestionnaireRelations`.
- Produces:
  - `pdfexact.extract.fonts.collecter_polices(doc) -> dict[str, FontAsset]`
  - `pdfexact.extract.fonts.mesurer_largeur_pt(texte: str, asset: FontAsset, size_pt: float) -> float`
  - `pdfexact.extract.fonts.ascendante_pt(asset: FontAsset, size_pt: float) -> float`
  - `pdfexact.extract.text.extraire_texte(page, polices) -> list[TextBox]`
  - `pdfexact.extract.document.extraire(chemin_pdf, pages=None) -> Document`
  - `pdfexact.render.drawing.zone_texte_xml(ligne: Line, identifiant: int, z: int) -> str`

C'est la tâche la plus dense du plan. Elle produit la première conversion mesurable de bout en bout.

- [ ] **Step 1 : écrire le test des polices**

```python
# tests/extract/test_fonts.py
import pymupdf

from pdfexact.extract.fonts import ascendante_pt, collecter_polices, mesurer_largeur_pt


def test_collecte_les_polices_du_document(pdf_texte):
    doc = pymupdf.open(pdf_texte)
    try:
        polices = collecter_polices(doc)
    finally:
        doc.close()

    assert len(polices) >= 1
    for asset in polices.values():
        assert asset.famille
        assert asset.font_id


def test_mesure_de_largeur_croit_avec_le_texte(pdf_texte):
    doc = pymupdf.open(pdf_texte)
    try:
        asset = next(iter(collecter_polices(doc).values()))
    finally:
        doc.close()

    court = mesurer_largeur_pt("ab", asset, 12.0)
    long = mesurer_largeur_pt("abcdef", asset, 12.0)

    assert long > court


def test_mesure_de_largeur_est_proportionnelle_au_corps(pdf_texte):
    doc = pymupdf.open(pdf_texte)
    try:
        asset = next(iter(collecter_polices(doc).values()))
    finally:
        doc.close()

    douze = mesurer_largeur_pt("abcdef", asset, 12.0)
    vingt_quatre = mesurer_largeur_pt("abcdef", asset, 24.0)

    assert vingt_quatre == round(douze * 2, 6) or abs(vingt_quatre - douze * 2) < 0.01


def test_texte_vide_a_une_largeur_nulle(pdf_texte):
    doc = pymupdf.open(pdf_texte)
    try:
        asset = next(iter(collecter_polices(doc).values()))
    finally:
        doc.close()

    assert mesurer_largeur_pt("", asset, 12.0) == 0.0


def test_ascendante_est_positive_et_inferieure_au_corps(pdf_texte):
    doc = pymupdf.open(pdf_texte)
    try:
        asset = next(iter(collecter_polices(doc).values()))
    finally:
        doc.close()

    valeur = ascendante_pt(asset, 12.0)

    assert 0 < valeur <= 12.0 * 1.2
```

- [ ] **Step 2 : lancer pour voir échouer**

Run: `.converter/bin/pytest tests/extract/test_fonts.py -v`
Attendu : FAIL, `ModuleNotFoundError`.

- [ ] **Step 3 : implémenter l'extraction et la mesure de polices**

```python
# pdfexact/extract/fonts.py
"""Polices : extraction depuis le PDF, substitution, mesure.

Deux choses sont nécessaires au writer et à personne d'autre : la largeur rendue d'une
chaîne, pour corriger la dérive horizontale, et l'ascendante, pour poser la zone de texte
de sorte que la baseline tombe au bon endroit.
"""
import subprocess
from functools import lru_cache

from fontTools.ttLib import TTFont

from pdfexact.ir import FontAsset

SUBSTITUTIONS = {
    "helvetica": "Arial",
    "helv": "Arial",
    "times": "Times New Roman",
    "tiro": "Times New Roman",
    "times-roman": "Times New Roman",
    "courier": "Courier New",
    "cour": "Courier New",
    "symbol": "Symbol",
    "zapfdingbats": "Wingdings",
}


def _nom_normalise(nom_pdf: str) -> str:
    """Retire le préfixe de sous-ensemble « ABCDEF+ » et la partie style."""
    sans_prefixe = nom_pdf.split("+", 1)[-1]
    return sans_prefixe.split("-", 1)[0].split(",", 1)[0]


def famille_de_substitution(nom_pdf: str) -> str:
    return SUBSTITUTIONS.get(_nom_normalise(nom_pdf).lower(), _nom_normalise(nom_pdf))


@lru_cache(maxsize=64)
def _fichier_police_systeme(famille: str) -> str | None:
    """Résout une famille vers un fichier via fontconfig. None si indisponible."""
    try:
        resultat = subprocess.run(
            ["fc-match", "-f", "%{file}", famille],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    chemin = resultat.stdout.decode(errors="replace").strip()
    return chemin or None


def collecter_polices(doc) -> dict[str, FontAsset]:
    """Recense toutes les polices du document, embarquées ou substituées."""
    assets: dict[str, FontAsset] = {}

    for numero_page in range(doc.page_count):
        for entree in doc[numero_page].get_fonts(full=True):
            xref, extension, _type, nom_base = entree[0], entree[1], entree[2], entree[3]
            # La clé est le nom PostScript, pas le xref : le dictionnaire de span retourné
            # par get_text("dict") ne porte aucun xref, seulement la clé `font`, qui
            # contient ce même nom. C'est le seul point de jonction entre les deux API.
            font_id = nom_base
            if font_id in assets:
                continue

            donnees = None
            extension_reelle = ""
            if extension not in ("n/a", "", None):
                try:
                    _nom, ext, _t, tampon = doc.extract_font(xref)
                    if tampon and ext in ("ttf", "otf"):
                        donnees = tampon
                        extension_reelle = ext
                except (RuntimeError, ValueError):
                    donnees = None

            assets[font_id] = FontAsset(
                font_id=font_id,
                famille=famille_de_substitution(nom_base),
                donnees=donnees,
                extension=extension_reelle,
                embarquee=donnees is not None,
            )

    return assets


@lru_cache(maxsize=64)
def _ttfont_depuis_octets(octets: bytes) -> TTFont | None:
    import io

    try:
        return TTFont(io.BytesIO(octets), fontNumber=0, lazy=True)
    except Exception:
        return None


def _ttfont_pour(asset: FontAsset) -> TTFont | None:
    if asset.donnees is not None:
        return _ttfont_depuis_octets(asset.donnees)
    chemin = _fichier_police_systeme(asset.famille)
    if chemin is None:
        return None
    try:
        return TTFont(chemin, fontNumber=0, lazy=True)
    except Exception:
        return None


def mesurer_largeur_pt(texte: str, asset: FontAsset, size_pt: float) -> float:
    """Largeur rendue de `texte`, en points, avec la police qui sera déclarée dans le docx.

    C'est cette largeur que la correction d'espacement compare à celle mesurée dans le PDF.
    """
    if not texte:
        return 0.0

    police = _ttfont_pour(asset)
    if police is None:
        # Sans métriques, une approximation vaut mieux qu'une exception : 0,5 em par glyphe.
        return len(texte) * size_pt * 0.5

    unites_par_em = police["head"].unitsPerEm
    hmtx = police["hmtx"]
    cmap = police.getBestCmap() or {}
    glyphes = police.getGlyphOrder()
    defaut = hmtx[glyphes[0]][0] if glyphes else unites_par_em // 2

    total = 0
    for caractere in texte:
        nom_glyphe = cmap.get(ord(caractere))
        total += hmtx[nom_glyphe][0] if nom_glyphe in hmtx.metrics else defaut

    return total / unites_par_em * size_pt


def ascendante_pt(asset: FontAsset, size_pt: float) -> float:
    """Distance entre le haut de la zone de texte et la baseline, en points."""
    police = _ttfont_pour(asset)
    if police is None:
        return size_pt * 0.8

    unites_par_em = police["head"].unitsPerEm
    try:
        ascendante = police["hhea"].ascent
    except KeyError:
        ascendante = int(unites_par_em * 0.8)
    return ascendante / unites_par_em * size_pt
```

- [ ] **Step 4 : lancer les tests de polices**

Run: `.converter/bin/pytest tests/extract/test_fonts.py -v`
Attendu : 5 passed.

- [ ] **Step 5 : écrire le test de l'extraction de texte**

```python
# tests/extract/test_text.py
import pymupdf

from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.text import extraire_texte


def _blocs(chemin):
    doc = pymupdf.open(chemin)
    try:
        return extraire_texte(doc[0], collecter_polices(doc))
    finally:
        doc.close()


def test_les_deux_lignes_sont_extraites(pdf_texte):
    blocs = _blocs(pdf_texte)

    textes = [span.texte for bloc in blocs for ligne in bloc.lignes for span in ligne.spans]
    assert any("Helvetica" in t for t in textes)
    assert any("Times" in t for t in textes)


def test_le_corps_de_police_est_conserve(pdf_texte):
    blocs = _blocs(pdf_texte)

    corps = {span.size_pt for bloc in blocs for ligne in bloc.lignes for span in ligne.spans}
    assert 12.0 in corps
    assert 18.0 in corps


def test_la_couleur_est_une_chaine_hexadecimale(pdf_texte):
    blocs = _blocs(pdf_texte)

    for bloc in blocs:
        for ligne in bloc.lignes:
            for span in ligne.spans:
                assert len(span.couleur) == 6
                int(span.couleur, 16)


def test_la_largeur_cible_est_positive(pdf_texte):
    blocs = _blocs(pdf_texte)

    for bloc in blocs:
        for ligne in bloc.lignes:
            assert ligne.largeur_cible_emu > 0


def test_lespacement_corrige_la_derive(pdf_texte):
    blocs = _blocs(pdf_texte)

    # Au moins un span porte une correction non nulle, sauf coïncidence parfaite.
    espacements = [
        span.espacement_twips for bloc in blocs for ligne in bloc.lignes for span in ligne.spans
    ]
    assert all(isinstance(valeur, int) for valeur in espacements)


def test_la_bbox_de_ligne_est_en_emu(pdf_texte):
    blocs = _blocs(pdf_texte)

    ligne = blocs[0].lignes[0]
    # 72 points de marge gauche = 914400 EMU ; tolérance large.
    assert ligne.bbox.x0 > 500_000
```

- [ ] **Step 6 : implémenter l'extraction de texte**

```python
# pdfexact/extract/text.py
"""Extraction du texte : dictionnaire PyMuPDF vers TextBox / Line / Span.

Le découpage se fait à la ligne, pas au bloc. Une ligne devient une zone de texte OOXML à
elle seule, positionnée sur sa baseline : c'est ce qui empêche Word de recalculer les
retours à la ligne et de faire dériver le bas du bloc.
"""
from pdfexact.geometry import BBox, bbox_depuis_rect, emu_vers_pt, pt_vers_emu, pt_vers_twips
from pdfexact.ir import FontRef, Line, Span, TextBox
from pdfexact.extract.fonts import ascendante_pt, mesurer_largeur_pt

_BIT_ITALIQUE = 1 << 1
_BIT_GRAS = 1 << 4


def _couleur_hexa(valeur: int) -> str:
    return f"{valeur & 0xFFFFFF:06X}"


def _bbox_depuis_liste(quadruplet) -> BBox:
    return BBox(
        pt_vers_emu(quadruplet[0]),
        pt_vers_emu(quadruplet[1]),
        pt_vers_emu(quadruplet[2]),
        pt_vers_emu(quadruplet[3]),
    )


def _resoudre_police(nom_du_span: str, polices: dict) -> str:
    """Relie un span à sa police par le nom PostScript.

    get_text("dict") ne donne pas de xref : la clé `font` du span et le champ `basefont`
    de get_fonts() sont le seul point de jonction. La correspondance est exacte dans le
    cas courant ; les deux replis couvrent les préfixes de sous-ensemble (« ABCDEF+ »).
    """
    if nom_du_span in polices:
        return nom_du_span

    sans_prefixe = nom_du_span.split("+", 1)[-1]
    if sans_prefixe in polices:
        return sans_prefixe

    for identifiant in polices:
        if identifiant.split("+", 1)[-1] == sans_prefixe:
            return identifiant

    return next(iter(polices))


def _ascendante_du_span(span: dict, asset) -> float:
    """Ascendante en points, depuis la métrique que MuPDF a lui-même utilisée.

    Le span porte `ascender` en fraction de cadratin. C'est exactement la valeur ayant
    servi à poser le texte dans le PDF, donc la baseline retombe juste par construction —
    mieux que la reconstruction par fontTools, qui reste le repli si la clé manque.
    """
    fraction = span.get("ascender")
    taille = float(span.get("size", 12.0))
    if fraction is None:
        return ascendante_pt(asset, taille)
    return float(fraction) * taille


def _corriger_espacement(ligne: Line, assets: dict) -> None:
    """Répartit l'écart de largeur sur les caractères, en vingtièmes de point.

    Word ne restitue pas exactement les largeurs de glyphes du PDF. Sans correction, la
    ligne est trop courte ou trop longue et son bord droit ne tombe pas au bon endroit.
    """
    caracteres = sum(len(span.texte) for span in ligne.spans)
    if caracteres < 2:
        return

    mesuree_pt = sum(
        mesurer_largeur_pt(span.texte, assets[span.police.font_id], span.size_pt)
        for span in ligne.spans
    )
    cible_pt = emu_vers_pt(ligne.largeur_cible_emu)
    ecart_pt = cible_pt - mesuree_pt

    espacement = round(pt_vers_twips(ecart_pt / (caracteres - 1)))
    for span in ligne.spans:
        span.espacement_twips = espacement


def extraire_texte(page, polices: dict) -> list[TextBox]:
    """Retourne les blocs de texte de la page, en EMU."""
    blocs_ir: list[TextBox] = []
    donnees = page.get_text("dict")

    for bloc in donnees.get("blocks", []):
        if bloc.get("type") != 0:
            continue

        lignes_ir: list[Line] = []
        for ligne in bloc.get("lines", []):
            spans_ir: list[Span] = []
            for span in ligne.get("spans", []):
                texte = span.get("text", "")
                if not texte:
                    continue

                font_id = _resoudre_police(span.get("font", ""), polices)

                drapeaux = span.get("flags", 0)
                asset = polices[font_id]
                spans_ir.append(
                    Span(
                        texte=texte,
                        police=FontRef(
                            font_id=font_id,
                            famille=asset.famille,
                            gras=bool(drapeaux & _BIT_GRAS),
                            italique=bool(drapeaux & _BIT_ITALIQUE),
                        ),
                        size_pt=round(float(span.get("size", 12.0)), 2),
                        couleur=_couleur_hexa(int(span.get("color", 0))),
                    )
                )

            if not spans_ir:
                continue

            boite_ligne = _bbox_depuis_liste(ligne["bbox"])
            premier_span = ligne["spans"][0]
            origine_y = premier_span.get("origin", (0, boite_ligne.y1))[1]
            ascendante = _ascendante_du_span(
                premier_span, polices[spans_ir[0].police.font_id]
            )

            haut = pt_vers_emu(origine_y - ascendante)
            ligne_ir = Line(
                bbox=BBox(boite_ligne.x0, haut, boite_ligne.x1, haut + boite_ligne.hauteur),
                spans=spans_ir,
                hauteur_ligne_emu=boite_ligne.hauteur,
                largeur_cible_emu=boite_ligne.largeur,
            )
            _corriger_espacement(ligne_ir, polices)
            lignes_ir.append(ligne_ir)

        if lignes_ir:
            blocs_ir.append(TextBox(bbox=_bbox_depuis_liste(bloc["bbox"]), lignes=lignes_ir))

    return blocs_ir
```

- [ ] **Step 7 : lancer les tests d'extraction**

Run: `.converter/bin/pytest tests/extract/test_text.py -v`
Attendu : 6 passed. Si le champ `xref` est absent du dictionnaire de span dans la version installée, la solution de repli par nom prend le relais — vérifier que la note de la Task 2 le confirme.

- [ ] **Step 8 : écrire le test du rendu de zone de texte**

```python
# tests/render/test_drawing.py
from xml.etree import ElementTree

from pdfexact.geometry import BBox
from pdfexact.ir import FontRef, Line, Span
from pdfexact.render.drawing import zone_texte_xml

NS = {
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}

ns_racine = "http://schemas.openxmlformats.org"

# L'enveloppe doit déclarer TOUS les espaces de noms utilisés par les fragments, y compris
# pic: et r:, sinon le parsing échoue avant même d'avoir testé quoi que ce soit.
ENVELOPPE = (
    f'<w:r xmlns:w="{ns_racine}/wordprocessingml/2006/main" '
    f'xmlns:wp="{ns_racine}/drawingml/2006/wordprocessingDrawing" '
    f'xmlns:a="{ns_racine}/drawingml/2006/main" '
    f'xmlns:pic="{ns_racine}/drawingml/2006/picture" '
    f'xmlns:r="{ns_racine}/officeDocument/2006/relationships" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">{}</w:r>'
)


def _ligne_simple():
    return Line(
        bbox=BBox(914400, 1828800, 2743200, 2057400),
        spans=[
            Span(
                texte="Bonjour",
                police=FontRef(font_id="f0", famille="Arial", gras=False, italique=False),
                size_pt=12.0,
                couleur="FF0000",
                espacement_twips=-3,
            )
        ],
        hauteur_ligne_emu=228600,
        largeur_cible_emu=1828800,
    )


def _analyser(fragment):
    return ElementTree.fromstring(ENVELOPPE.format(fragment))


def test_le_fragment_est_du_xml_bien_forme():
    _analyser(zone_texte_xml(_ligne_simple(), identifiant=1, z=5))


def test_la_position_reprend_la_bbox():
    racine = _analyser(zone_texte_xml(_ligne_simple(), identifiant=1, z=5))

    assert racine.find(".//wp:posOffset", NS) is not None
    decalages = [element.text for element in racine.findall(".//wp:posOffset", NS)]
    assert "914400" in decalages
    assert "1828800" in decalages


def test_le_corps_est_en_demi_points():
    racine = _analyser(zone_texte_xml(_ligne_simple(), identifiant=1, z=5))

    taille = racine.find(".//w:sz", NS)
    assert taille.get(f"{{{NS['w']}}}val") == "24"


def test_lespacement_est_reporte():
    racine = _analyser(zone_texte_xml(_ligne_simple(), identifiant=1, z=5))

    espacement = racine.find(".//w:spacing[@w:val='-3']", NS)
    assert espacement is not None


def test_linterligne_est_exact():
    racine = _analyser(zone_texte_xml(_ligne_simple(), identifiant=1, z=5))

    interligne = racine.find(".//w:pPr/w:spacing", NS)
    assert interligne.get(f"{{{NS['w']}}}lineRule") == "exact"


def test_le_texte_est_echappe():
    ligne = _ligne_simple()
    ligne.spans[0].texte = "a < b & c"

    fragment = zone_texte_xml(ligne, identifiant=1, z=5)

    assert "&lt;" in fragment and "&amp;" in fragment
    _analyser(fragment)


def test_lordre_de_superposition_est_reporte():
    fragment = zone_texte_xml(_ligne_simple(), identifiant=1, z=42)

    assert 'relativeHeight="42"' in fragment
```

- [ ] **Step 9 : implémenter le rendu de zone de texte**

```python
# pdfexact/render/drawing.py
"""Fragments DrawingML.

Chaque élément de page est une forme flottante ancrée en position absolue par rapport à
la page. Les marges internes sont nulles et l'habillage désactivé : rien ne doit pouvoir
décaler quoi que ce soit.
"""
from xml.sax.saxutils import escape

from pdfexact.geometry import emu_vers_pt, pt_vers_twips
from pdfexact.ir import Line

_GABARIT_ANCRE = (
    '<w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
    'relativeHeight="{z}" behindDoc="{derriere}" locked="0" layoutInCell="1" '
    'allowOverlap="1">'
    '<wp:simplePos x="0" y="0"/>'
    '<wp:positionH relativeFrom="page"><wp:posOffset>{x}</wp:posOffset></wp:positionH>'
    '<wp:positionV relativeFrom="page"><wp:posOffset>{y}</wp:posOffset></wp:positionV>'
    '<wp:extent cx="{largeur}" cy="{hauteur}"/>'
    '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
    "<wp:wrapNone/>"
    '<wp:docPr id="{identifiant}" name="{nom}"/>'
    "{contenu}"
    "</wp:anchor></w:drawing>"
)


def _ancre(bbox, identifiant: int, z: int, nom: str, contenu: str, derriere: bool = False) -> str:
    return _GABARIT_ANCRE.format(
        z=z,
        derriere=1 if derriere else 0,
        x=bbox.x0,
        y=bbox.y0,
        largeur=max(bbox.largeur, 1),
        hauteur=max(bbox.hauteur, 1),
        identifiant=identifiant,
        nom=nom,
        contenu=contenu,
    )


def _run_xml(span, relations=None) -> str:
    # `relations` n'est utilisé qu'à partir de la tâche 12, pour les hyperliens.
    proprietes = [
        f'<w:rFonts w:ascii="{escape(span.police.famille)}" '
        f'w:hAnsi="{escape(span.police.famille)}" w:cs="{escape(span.police.famille)}"/>'
    ]
    if span.police.gras:
        proprietes.append("<w:b/>")
    if span.police.italique:
        proprietes.append("<w:i/>")
    proprietes.append(f'<w:color w:val="{span.couleur}"/>')
    proprietes.append(f'<w:sz w:val="{round(span.size_pt * 2)}"/>')
    proprietes.append(f'<w:szCs w:val="{round(span.size_pt * 2)}"/>')
    if span.espacement_twips:
        proprietes.append(f'<w:spacing w:val="{span.espacement_twips}"/>')

    texte = escape(span.texte)
    return (
        f'<w:r><w:rPr>{"".join(proprietes)}</w:rPr>'
        f'<w:t xml:space="preserve">{texte}</w:t></w:r>'
    )


def zone_texte_xml(ligne: Line, identifiant: int, z: int, relations=None) -> str:
    """Rend une ligne de texte comme forme flottante contenant une zone de texte.

    `relations` reste optionnel : il ne sert qu'aux hyperliens, branchés à la tâche 12.
    """
    interligne = pt_vers_twips(emu_vers_pt(ligne.hauteur_ligne_emu))
    runs = "".join(_run_xml(span, relations) for span in ligne.spans)

    paragraphe = (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="0" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        '<w:ind w:left="0" w:right="0" w:firstLine="0"/>'
        "</w:pPr>"
        f"{runs}</w:p>"
    )

    forme = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp><wps:cNvSpPr txBox=\"1\"/>"
        "<wps:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{max(ligne.bbox.largeur, 1)}" cy="{max(ligne.bbox.hauteur, 1)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        f"<wps:txbx><w:txbxContent>{paragraphe}</w:txbxContent></wps:txbx>"
        '<wps:bodyPr rot="0" spcFirstLastPara="0" vertOverflow="overflow" '
        'horzOverflow="overflow" vert="horz" wrap="none" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(ligne.bbox, identifiant, z, f"Ligne {identifiant}", forme)
```

- [ ] **Step 10 : lancer les tests de rendu**

Run: `.converter/bin/pytest tests/render/test_drawing.py -v`
Attendu : 7 passed.

- [ ] **Step 11 : brancher l'orchestration**

```python
# pdfexact/extract/document.py
"""Ouverture du PDF et assemblage du Document."""
import pymupdf

from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.text import extraire_texte
from pdfexact.geometry import pt_vers_emu
from pdfexact.ir import Document, Page


def extraire(chemin_pdf, pages=None) -> Document:
    """Construit l'IR complet à partir d'un PDF. `pages` : indices 0-based, ou None."""
    doc = pymupdf.open(chemin_pdf)
    try:
        polices = collecter_polices(doc)
        indices = range(doc.page_count) if pages is None else pages

        document = Document(polices=polices)
        for index in indices:
            page_pdf = doc[index]
            page_ir = Page(
                index=index,
                largeur_emu=pt_vers_emu(page_pdf.rect.width),
                hauteur_emu=pt_vers_emu(page_pdf.rect.height),
            )
            page_ir.elements.extend(extraire_texte(page_pdf, polices))
            document.pages.append(page_ir)

        return document
    finally:
        doc.close()
```

Puis modifier `pdfexact/render/docx_writer.py` : remplacer la ligne `contenu_ancres = ""` par un rendu réel.

```python
# dans pdfexact/render/docx_writer.py, en tête
from pdfexact.ir import ImageEl, LinkZone, RasterEl, ShapeEl, TextBox
from pdfexact.render.drawing import zone_texte_xml


def _ancres_de_page(page, compteur, relations) -> str:
    """Rend tous les éléments de la page, dans l'ordre de superposition."""
    morceaux = []
    for z, element in enumerate(page.elements, start=1):
        if isinstance(element, TextBox):
            for ligne in element.lignes:
                compteur[0] += 1
                morceaux.append(zone_texte_xml(ligne, compteur[0], z))
        # Les autres types d'élément sont branchés par les tâches 9 à 12.
    return "".join(morceaux)
```

Et dans `construire_document_xml`, remplacer :

```python
        contenu_ancres = ""  # rempli par les tâches suivantes
```

par :

```python
        contenu_ancres = _ancres_de_page(page, compteur, relations)
```

en initialisant `compteur = [0]` avant la boucle, et en enveloppant `contenu_ancres` dans un run : `<w:r>{contenu_ancres}</w:r>` — les ancres sont des `w:drawing`, qui doivent vivre dans un run.

- [ ] **Step 12 : écrire le test de fidélité de bout en bout**

```python
# tests/visual/test_fidelite_texte.py
import pytest

from pdfexact.extract.document import extraire
from pdfexact.render.package import ecrire_docx
from tests.visual.harness import comparer

SEUIL = 0.90  # relevé à 0,95 une fois images et vectoriel en place


def test_le_texte_est_visuellement_fidele(pdf_texte, tmp_path):
    document = extraire(pdf_texte)
    sortie = tmp_path / "texte.docx"
    ecrire_docx(document, sortie)

    scores = comparer(pdf_texte, sortie, dpi=150)

    assert scores, "aucune page comparée"
    for numero, score in enumerate(scores):
        assert score >= SEUIL, f"page {numero} : SSIM {score:.3f} < {SEUIL}"
```

- [ ] **Step 13 : lancer le test de fidélité**

Run: `.converter/bin/pytest tests/visual/test_fidelite_texte.py -v`
Attendu : PASS. En cas d'échec, le score exact est dans le message — c'est le point de départ du réglage. Consigner le score obtenu dans le message de commit.

- [ ] **Step 14 : commit**

```bash
git add pdfexact/extract/ pdfexact/render/ tests/extract/ tests/render/ tests/visual/
git commit -m "feat: extract text and render it as absolutely positioned text boxes"
```

---

### Task 9 : images bitmap

**Files:**
- Create: `pdfexact/extract/images.py`
- Modify: `pdfexact/render/drawing.py`
- Modify: `pdfexact/render/docx_writer.py`
- Modify: `pdfexact/extract/document.py`
- Create: `tests/extract/test_images.py`
- Modify: `tests/render/test_drawing.py`

**Interfaces:**
- Consumes: `Document.media`, `GestionnaireRelations.ajouter`.
- Produces: `pdfexact.extract.images.extraire_images(page, doc, media) -> list[ImageEl]` (enrichit `media` en place), `pdfexact.render.drawing.image_xml(element, identifiant, z, rel_id) -> str`.

- [ ] **Step 1 : écrire le test d'extraction**

```python
# tests/extract/test_images.py
import pymupdf

from pdfexact.extract.images import extraire_images


def test_les_deux_placements_sont_extraits(pdf_image):
    doc = pymupdf.open(pdf_image)
    media = {}
    try:
        elements = extraire_images(doc[0], doc, media)
    finally:
        doc.close()

    assert len(elements) == 2


def test_limage_repetee_nest_stockee_quune_fois(pdf_image):
    doc = pymupdf.open(pdf_image)
    media = {}
    try:
        elements = extraire_images(doc[0], doc, media)
    finally:
        doc.close()

    assert len(media) == 1
    assert elements[0].media_ref == elements[1].media_ref


def test_les_bbox_different(pdf_image):
    doc = pymupdf.open(pdf_image)
    media = {}
    try:
        elements = extraire_images(doc[0], doc, media)
    finally:
        doc.close()

    assert elements[0].bbox != elements[1].bbox


def test_le_media_porte_des_octets_et_une_extension(pdf_image):
    doc = pymupdf.open(pdf_image)
    media = {}
    try:
        extraire_images(doc[0], doc, media)
    finally:
        doc.close()

    item = next(iter(media.values()))
    assert len(item.donnees) > 0
    assert item.extension in ("png", "jpeg", "jpg")
```

- [ ] **Step 2 : lancer pour voir échouer**

Run: `.converter/bin/pytest tests/extract/test_images.py -v`
Attendu : FAIL, `ModuleNotFoundError`.

- [ ] **Step 3 : implémenter**

```python
# pdfexact/extract/images.py
"""Extraction des images bitmap.

Une même image peut être placée plusieurs fois dans une page ou un document. Elle n'est
stockée qu'une fois dans word/media/, et référencée autant de fois que nécessaire : c'est
la différence entre un docx de 2 Mo et un de 40 Mo.
"""
from pdfexact.geometry import bbox_depuis_rect
from pdfexact.ir import ImageEl, MediaItem

EXTENSIONS_SUPPORTEES = {"png", "jpeg", "jpg"}


def extraire_images(page, doc, media: dict) -> list[ImageEl]:
    """Retourne les placements d'images de la page et enrichit le registre `media`."""
    elements: list[ImageEl] = []

    # get_images() liste une entrée par référence dans les ressources de page, pas par
    # image unique : une image placée deux fois y apparaît deux fois, avec le même xref.
    # Sans cette déduplication, chaque placement serait compté une fois par entrée.
    for xref in sorted({entree[0] for entree in page.get_images(full=True)}):
        media_ref = f"image{xref}"

        if media_ref not in media:
            extrait = doc.extract_image(xref)
            octets = extrait["image"]
            extension = extrait["ext"].lower()

            if extension not in EXTENSIONS_SUPPORTEES:
                # Format exotique (jpx, jbig2…) : on repasse par un PNG.
                import pymupdf

                pixmap = pymupdf.Pixmap(doc, xref)
                if pixmap.n - pixmap.alpha >= 4:
                    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
                octets = pixmap.tobytes("png")
                extension = "png"

            media[media_ref] = MediaItem(
                media_ref=media_ref, donnees=octets, extension=extension
            )

        for rect in page.get_image_rects(xref):
            elements.append(ImageEl(bbox=bbox_depuis_rect(rect), media_ref=media_ref))

    return elements
```

- [ ] **Step 4 : lancer les tests**

Run: `.converter/bin/pytest tests/extract/test_images.py -v`
Attendu : 4 passed.

- [ ] **Step 5 : ajouter le test du rendu d'image**

```python
# à ajouter dans tests/render/test_drawing.py
from pdfexact.ir import ImageEl
from pdfexact.render.drawing import image_xml


def test_le_fragment_image_est_bien_forme():
    element = ImageEl(bbox=BBox(0, 0, 914400, 914400), media_ref="image7")

    fragment = image_xml(element, identifiant=3, z=2, rel_id="rId4")

    _analyser(fragment)
    assert 'r:embed="rId4"' in fragment


def test_limage_reprend_les_dimensions_de_la_bbox():
    element = ImageEl(bbox=BBox(100, 200, 1100, 1400), media_ref="image7")

    fragment = image_xml(element, identifiant=3, z=2, rel_id="rId4")

    assert 'cx="1000"' in fragment
    assert 'cy="1200"' in fragment
```

- [ ] **Step 6 : implémenter le rendu d'image**

```python
# à ajouter dans pdfexact/render/drawing.py
def image_xml(element, identifiant: int, z: int, rel_id: str) -> str:
    """Rend une image (ou une région rastérisée) comme image flottante ancrée."""
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic>"
        f'<pic:nvPicPr><pic:cNvPr id="{identifiant}" name="{element.media_ref}"/>'
        "<pic:cNvPicPr/></pic:nvPicPr>"
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic>"
    )

    return _ancre(element.bbox, identifiant, z, f"Image {identifiant}", contenu)
```

- [ ] **Step 7 : brancher dans le writer et l'orchestration**

Dans `pdfexact/render/docx_writer.py`, étendre `_ancres_de_page` :

```python
        elif isinstance(element, (ImageEl, RasterEl)):
            compteur[0] += 1
            item = document_media[element.media_ref]
            rel_id = relations.ajouter(f"media/{item.media_ref}.{item.extension}", "image")
            morceaux.append(image_xml(element, compteur[0], z, rel_id))
```

`_ancres_de_page` prend désormais `document_media` en paramètre ; `construire_document_xml` lui passe `document.media`.

Dans `pdfexact/extract/document.py`, après l'extraction du texte :

```python
            page_ir.elements.extend(extraire_images(page_pdf, doc, document.media))
```

- [ ] **Step 8 : lancer toute la suite**

Run: `.converter/bin/pytest -v`
Attendu : tout passe. Le test de fidélité texte ne doit pas régresser.

- [ ] **Step 9 : commit**

```bash
git add pdfexact/ tests/
git commit -m "feat: extract and render bitmap images with deduplication"
```

---

### Task 10 : graphiques vectoriels

**Files:**
- Create: `pdfexact/extract/vector.py`
- Modify: `pdfexact/render/drawing.py`
- Modify: `pdfexact/render/docx_writer.py`
- Modify: `pdfexact/extract/document.py`
- Create: `tests/extract/test_vector.py`
- Modify: `tests/render/test_drawing.py`

**Interfaces:**
- Consumes: `ShapeEl`, `Path`, `PathCommand`.
- Produces: `pdfexact.extract.vector.extraire_vectoriel(page) -> list[ShapeEl]`, `pdfexact.render.drawing.forme_xml(element, identifiant, z) -> str`.

- [ ] **Step 1 : écrire le test d'extraction**

```python
# tests/extract/test_vector.py
import pymupdf

from pdfexact.extract.vector import extraire_vectoriel


def _formes(chemin):
    doc = pymupdf.open(chemin)
    try:
        return extraire_vectoriel(doc[0])
    finally:
        doc.close()


def test_les_dessins_sont_extraits(pdf_vectoriel):
    formes = _formes(pdf_vectoriel)

    assert len(formes) >= 2


def test_le_rectangle_rouge_est_reconnu(pdf_vectoriel):
    formes = _formes(pdf_vectoriel)

    remplissages = {forme.remplissage for forme in formes if forme.remplissage}
    assert "FF0000" in remplissages


def test_les_chemins_sont_des_commandes_nommees(pdf_vectoriel):
    formes = _formes(pdf_vectoriel)

    for forme in formes:
        for chemin in forme.chemins:
            for operateur, points in chemin:
                assert operateur in ("move", "line", "cubic", "quad", "close")
                assert all(isinstance(coordonnee, int) for point in points for coordonnee in point)


def test_lepaisseur_de_contour_est_en_emu(pdf_vectoriel):
    formes = _formes(pdf_vectoriel)

    epaisseurs = [forme.epaisseur_emu for forme in formes if forme.contour]
    assert any(valeur > 0 for valeur in epaisseurs)


def test_la_bbox_englobe_les_points(pdf_vectoriel):
    formes = _formes(pdf_vectoriel)

    for forme in formes:
        for chemin in forme.chemins:
            for _operateur, points in chemin:
                for x, y in points:
                    assert forme.bbox.x0 <= x <= forme.bbox.x1
                    assert forme.bbox.y0 <= y <= forme.bbox.y1
```

- [ ] **Step 2 : lancer pour voir échouer**

Run: `.converter/bin/pytest tests/extract/test_vector.py -v`
Attendu : FAIL, `ModuleNotFoundError`.

- [ ] **Step 3 : implémenter**

```python
# pdfexact/extract/vector.py
"""Extraction des graphiques vectoriels.

Les primitives de PyMuPDF se transposent une à une en commandes de chemin DrawingML.
Rien n'est approximé ici : ce qui n'est pas transposable relève du repli raster, traité
séparément.
"""
from pdfexact.geometry import BBox, bbox_depuis_rect, pt_vers_emu
from pdfexact.ir import ShapeEl


def _couleur_hexa(composantes) -> str | None:
    if composantes is None:
        return None
    rouge, vert, bleu = (round(canal * 255) for canal in composantes[:3])
    return f"{rouge:02X}{vert:02X}{bleu:02X}"


def _point(couple) -> tuple[int, int]:
    return (pt_vers_emu(couple[0]), pt_vers_emu(couple[1]))


def _chemin_depuis_item(item) -> list:
    """Traduit une primitive PyMuPDF en commandes de chemin."""
    operateur = item[0]

    if operateur == "l":
        return [("move", (_point(item[1]),)), ("line", (_point(item[2]),))]

    if operateur == "c":
        return [
            ("move", (_point(item[1]),)),
            ("cubic", (_point(item[2]), _point(item[3]), _point(item[4]))),
        ]

    if operateur == "re":
        rect = item[1]
        coins = [
            (rect.x0, rect.y0),
            (rect.x1, rect.y0),
            (rect.x1, rect.y1),
            (rect.x0, rect.y1),
        ]
        commandes = [("move", (_point(coins[0]),))]
        commandes += [("line", (_point(coin),)) for coin in coins[1:]]
        commandes.append(("close", ()))
        return commandes

    if operateur == "qu":
        quad = item[1]
        sommets = [quad.ul, quad.ur, quad.lr, quad.ll]
        commandes = [("move", (_point((sommets[0].x, sommets[0].y)),))]
        commandes += [("line", (_point((s.x, s.y)),)) for s in sommets[1:]]
        commandes.append(("close", ()))
        return commandes

    return []


def extraire_vectoriel(page) -> list[ShapeEl]:
    """Retourne les formes vectorielles de la page, en EMU."""
    formes: list[ShapeEl] = []

    for dessin in page.get_drawings():
        chemins = []
        for item in dessin.get("items", []):
            commandes = _chemin_depuis_item(item)
            if commandes:
                chemins.append(commandes)

        if not chemins:
            continue

        boite = bbox_depuis_rect(dessin["rect"])
        if boite.largeur <= 0 or boite.hauteur <= 0:
            # Une ligne parfaitement horizontale ou verticale a une bbox plate :
            # on lui donne un EMU d'épaisseur pour que la forme reste rendable.
            boite = BBox(boite.x0, boite.y0, max(boite.x1, boite.x0 + 1), max(boite.y1, boite.y0 + 1))

        dashes = dessin.get("dashes")
        formes.append(
            ShapeEl(
                bbox=boite,
                chemins=chemins,
                remplissage=_couleur_hexa(dessin.get("fill")),
                contour=_couleur_hexa(dessin.get("color")),
                epaisseur_emu=pt_vers_emu(dessin.get("width") or 0),
                pointilles="dash" if dashes and dashes != "[] 0" else None,
                alpha=float(dessin.get("fill_opacity", 1.0) or 1.0),
            )
        )

    return formes
```

- [ ] **Step 4 : lancer les tests**

Run: `.converter/bin/pytest tests/extract/test_vector.py -v`
Attendu : 5 passed.

- [ ] **Step 5 : ajouter le test du rendu de forme**

```python
# à ajouter dans tests/render/test_drawing.py
from pdfexact.ir import ShapeEl
from pdfexact.render.drawing import forme_xml


def _forme_rectangle():
    return ShapeEl(
        bbox=BBox(0, 0, 100000, 50000),
        chemins=[[
            ("move", ((0, 0),)),
            ("line", ((100000, 0),)),
            ("line", ((100000, 50000),)),
            ("close", ()),
        ]],
        remplissage="00FF00",
        contour="000000",
        epaisseur_emu=12700,
    )


def test_le_fragment_de_forme_est_bien_forme():
    _analyser(forme_xml(_forme_rectangle(), identifiant=9, z=3))


def test_la_forme_utilise_une_geometrie_personnalisee():
    fragment = forme_xml(_forme_rectangle(), identifiant=9, z=3)

    assert "<a:custGeom>" in fragment
    assert "<a:lnTo>" in fragment


def test_les_coordonnees_sont_relatives_a_la_bbox():
    forme = _forme_rectangle()
    forme.bbox = BBox(500000, 700000, 600000, 750000)
    forme.chemins = [[("move", ((500000, 700000),)), ("line", ((600000, 750000),))]]

    fragment = forme_xml(forme, identifiant=9, z=3)

    assert '<a:pt x="0" y="0"/>' in fragment
    assert '<a:pt x="100000" y="50000"/>' in fragment


def test_le_remplissage_est_rendu():
    fragment = forme_xml(_forme_rectangle(), identifiant=9, z=3)

    assert 'val="00FF00"' in fragment


def test_une_forme_sans_remplissage_declare_nofill():
    forme = _forme_rectangle()
    forme.remplissage = None

    fragment = forme_xml(forme, identifiant=9, z=3)

    assert "<a:noFill/>" in fragment
```

- [ ] **Step 6 : implémenter le rendu de forme**

```python
# à ajouter dans pdfexact/render/drawing.py
def _commandes_xml(chemins, origine_x: int, origine_y: int) -> str:
    """Traduit les chemins en éléments de a:path, en coordonnées relatives à la bbox."""
    morceaux = []
    for chemin in chemins:
        for operateur, points in chemin:
            relatifs = [(x - origine_x, y - origine_y) for x, y in points]
            balises = "".join(f'<a:pt x="{x}" y="{y}"/>' for x, y in relatifs)

            if operateur == "move":
                morceaux.append(f"<a:moveTo>{balises}</a:moveTo>")
            elif operateur == "line":
                morceaux.append(f"<a:lnTo>{balises}</a:lnTo>")
            elif operateur == "cubic":
                morceaux.append(f"<a:cubicBezTo>{balises}</a:cubicBezTo>")
            elif operateur == "quad":
                morceaux.append(f"<a:quadBezTo>{balises}</a:quadBezTo>")
            elif operateur == "close":
                morceaux.append("<a:close/>")
    return "".join(morceaux)


def forme_xml(element, identifiant: int, z: int) -> str:
    """Rend une forme vectorielle en géométrie personnalisée DrawingML."""
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)

    if element.remplissage:
        alpha = ""
        if element.alpha < 1.0:
            alpha = f'<a:alpha val="{round(element.alpha * 100000)}"/>'
        remplissage = f'<a:solidFill><a:srgbClr val="{element.remplissage}">{alpha}</a:srgbClr></a:solidFill>'
    else:
        remplissage = "<a:noFill/>"

    if element.contour and element.epaisseur_emu > 0:
        pointilles = f'<a:prstDash val="{element.pointilles}"/>' if element.pointilles else ""
        trait = (
            f'<a:ln w="{element.epaisseur_emu}">'
            f'<a:solidFill><a:srgbClr val="{element.contour}"/></a:solidFill>'
            f"{pointilles}</a:ln>"
        )
    else:
        trait = "<a:ln><a:noFill/></a:ln>"

    commandes = _commandes_xml(element.chemins, element.bbox.x0, element.bbox.y0)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp><wps:cNvSpPr/>"
        "<wps:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        "<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>"
        f'<a:rect l="0" t="0" r="{largeur}" b="{hauteur}"/>'
        f'<a:pathLst><a:path w="{largeur}" h="{hauteur}">{commandes}</a:path></a:pathLst>'
        "</a:custGeom>"
        f"{remplissage}{trait}"
        "</wps:spPr>"
        '<wps:bodyPr rot="0" anchor="t"/>'
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(element.bbox, identifiant, z, f"Forme {identifiant}", contenu)
```

- [ ] **Step 7 : brancher**

Dans `_ancres_de_page` :

```python
        elif isinstance(element, ShapeEl):
            compteur[0] += 1
            morceaux.append(forme_xml(element, compteur[0], z))
```

Dans `extraire`, **avant** l'extraction du texte — le vectoriel est dessiné sous le texte :

```python
            page_ir.elements.extend(extraire_vectoriel(page_pdf))
```

Placer cet appel en premier dans la construction de `page_ir.elements`, avant images et texte.

- [ ] **Step 8 : test de fidélité vectorielle**

```python
# tests/visual/test_fidelite_vectoriel.py
from pdfexact.extract.document import extraire
from pdfexact.render.package import ecrire_docx
from tests.visual.harness import comparer

SEUIL = 0.90


def test_le_vectoriel_est_visuellement_fidele(pdf_vectoriel, tmp_path):
    document = extraire(pdf_vectoriel)
    sortie = tmp_path / "vectoriel.docx"
    ecrire_docx(document, sortie)

    scores = comparer(pdf_vectoriel, sortie, dpi=150)

    for numero, score in enumerate(scores):
        assert score >= SEUIL, f"page {numero} : SSIM {score:.3f} < {SEUIL}"
```

- [ ] **Step 9 : lancer toute la suite**

Run: `.converter/bin/pytest -v`
Attendu : tout passe.

- [ ] **Step 10 : commit**

```bash
git add pdfexact/ tests/
git commit -m "feat: extract vector graphics and render them as DrawingML custom geometry"
```

---

### Task 11 : regroupement en clusters et repli raster

**Files:**
- Create: `pdfexact/fallback/__init__.py`
- Create: `pdfexact/fallback/rasterize.py`
- Modify: `pdfexact/extract/vector.py`
- Modify: `pdfexact/extract/document.py`
- Create: `tests/fallback/__init__.py`
- Create: `tests/fallback/test_rasterize.py`
- Create: `tests/extract/test_clusters.py`

**Interfaces:**
- Consumes: `ShapeEl`, `MediaItem`, `BBox`, `union`, `se_chevauchent`.
- Produces:
  - `pdfexact.extract.vector.regrouper(formes: list[ShapeEl]) -> list[list[ShapeEl]]`
  - `pdfexact.extract.vector.doit_rasteriser(cluster, page_a_des_degrades: bool, seuil: int) -> bool`
  - `pdfexact.fallback.rasterize.rasteriser_region(page, bbox, media, dpi) -> RasterEl`
  - `pdfexact.fallback.rasterize.page_a_des_degrades(doc, page) -> bool`

- [ ] **Step 1 : écrire le test du regroupement**

```python
# tests/extract/test_clusters.py
from pdfexact.geometry import BBox
from pdfexact.ir import ShapeEl
from pdfexact.extract.vector import doit_rasteriser, regrouper


def _forme(x0, y0, x1, y1):
    return ShapeEl(
        bbox=BBox(x0, y0, x1, y1),
        chemins=[[("move", ((x0, y0),)), ("line", ((x1, y1),))]],
        remplissage=None,
        contour="000000",
        epaisseur_emu=12700,
    )


def test_des_formes_disjointes_font_des_clusters_distincts():
    clusters = regrouper([_forme(0, 0, 10, 10), _forme(100, 100, 110, 110)])

    assert len(clusters) == 2


def test_des_formes_qui_se_chevauchent_fusionnent():
    clusters = regrouper([_forme(0, 0, 20, 20), _forme(10, 10, 30, 30)])

    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_la_fusion_est_transitive():
    clusters = regrouper([_forme(0, 0, 20, 20), _forme(15, 15, 35, 35), _forme(30, 30, 50, 50)])

    assert len(clusters) == 1
    assert len(clusters[0]) == 3


def test_liste_vide_ne_produit_aucun_cluster():
    assert regrouper([]) == []


def test_un_petit_cluster_sans_degrade_nest_pas_rasterise():
    cluster = [_forme(0, 0, 10, 10)]

    assert not doit_rasteriser(cluster, page_a_des_degrades=False, seuil=300)


def test_un_degrade_sur_la_page_force_le_repli():
    cluster = [_forme(0, 0, 10, 10)]

    assert doit_rasteriser(cluster, page_a_des_degrades=True, seuil=300)


def test_un_cluster_trop_dense_est_rasterise():
    cluster = [_forme(i, i, i + 5, i + 5) for i in range(400)]

    assert doit_rasteriser(cluster, page_a_des_degrades=False, seuil=300)
```

- [ ] **Step 2 : lancer pour voir échouer**

Run: `.converter/bin/pytest tests/extract/test_clusters.py -v`
Attendu : FAIL, `ImportError: cannot import name 'regrouper'`.

- [ ] **Step 3 : implémenter le regroupement**

```python
# à ajouter dans pdfexact/extract/vector.py
from pdfexact.geometry import se_chevauchent, union


def regrouper(formes: list[ShapeEl]) -> list[list[ShapeEl]]:
    """Regroupe les formes dont les boîtes se chevauchent, transitivement.

    Le repli raster s'applique à un groupe visuel entier, pas à une forme isolée : ne
    rastériser qu'une moitié d'un graphique produirait une couture visible.
    """
    clusters: list[tuple[BBox, list[ShapeEl]]] = []

    for forme in formes:
        touches = [
            index
            for index, (boite, _membres) in enumerate(clusters)
            if se_chevauchent(boite, forme.bbox)
        ]

        if not touches:
            clusters.append((forme.bbox, [forme]))
            continue

        boite_fusionnee = forme.bbox
        membres_fusionnes = [forme]
        for index in sorted(touches, reverse=True):
            boite, membres = clusters.pop(index)
            boite_fusionnee = union(boite_fusionnee, boite)
            membres_fusionnes = membres + membres_fusionnes
        clusters.append((boite_fusionnee, membres_fusionnes))

    return [membres for _boite, membres in clusters]


def doit_rasteriser(cluster: list[ShapeEl], page_a_des_degrades: bool, seuil: int) -> bool:
    """Décide si un cluster dépasse ce que DrawingML restitue fidèlement."""
    if page_a_des_degrades:
        return True

    nombre_chemins = sum(len(forme.chemins) for forme in cluster)
    return nombre_chemins > seuil
```

- [ ] **Step 4 : lancer les tests de regroupement**

Run: `.converter/bin/pytest tests/extract/test_clusters.py -v`
Attendu : 7 passed.

- [ ] **Step 5 : écrire le test de rastérisation**

```python
# tests/fallback/test_rasterize.py
import pymupdf

from pdfexact.fallback.rasterize import page_a_des_degrades, rasteriser_region
from pdfexact.geometry import BBox, pt_vers_emu


def test_la_region_produit_un_element_raster(pdf_vectoriel):
    doc = pymupdf.open(pdf_vectoriel)
    media = {}
    boite = BBox(pt_vers_emu(50), pt_vers_emu(50), pt_vers_emu(200), pt_vers_emu(150))
    try:
        element = rasteriser_region(doc[0], boite, media, dpi=72)
    finally:
        doc.close()

    assert element.bbox == boite
    assert element.media_ref in media
    assert media[element.media_ref].extension == "png"
    assert media[element.media_ref].donnees.startswith(b"\x89PNG")


def test_deux_regions_produisent_des_references_distinctes(pdf_vectoriel):
    doc = pymupdf.open(pdf_vectoriel)
    media = {}
    try:
        premier = rasteriser_region(
            doc[0], BBox(0, 0, pt_vers_emu(100), pt_vers_emu(100)), media, dpi=72
        )
        second = rasteriser_region(
            doc[0], BBox(pt_vers_emu(100), 0, pt_vers_emu(200), pt_vers_emu(100)), media, dpi=72
        )
    finally:
        doc.close()

    assert premier.media_ref != second.media_ref
    assert len(media) == 2


def test_un_pdf_sans_degrade_est_detecte(pdf_vectoriel):
    doc = pymupdf.open(pdf_vectoriel)
    try:
        resultat = page_a_des_degrades(doc, doc[0])
    finally:
        doc.close()

    assert resultat is False
```

- [ ] **Step 6 : implémenter la rastérisation**

```python
# pdfexact/fallback/rasterize.py
"""Repli raster.

Certaines constructions PDF — dégradés, masques non rectangulaires, modes de fusion —
n'ont pas d'équivalent DrawingML fiable. Plutôt que de produire un rendu faux, on
rastérise la région concernée, et elle seule. Le texte n'est jamais rastérisé : il est
écrit par-dessus et reste réel.
"""
import itertools

import pymupdf

from pdfexact.geometry import emu_vers_pt
from pdfexact.ir import MediaItem, RasterEl

_compteur = itertools.count(1)


def page_a_des_degrades(doc, page) -> bool:
    """Vrai si les ressources de la page déclarent un shading."""
    try:
        valeur = doc.xref_get_key(page.xref, "Resources/Shading")
    except (RuntimeError, ValueError):
        return False
    return bool(valeur) and valeur[0] not in ("null", None)


def rasteriser_region(page, bbox, media: dict, dpi: int = 300) -> RasterEl:
    """Rend la région indiquée en PNG et retourne l'élément qui la remplace."""
    rect = pymupdf.Rect(
        emu_vers_pt(bbox.x0),
        emu_vers_pt(bbox.y0),
        emu_vers_pt(bbox.x1),
        emu_vers_pt(bbox.y1),
    )
    pixmap = page.get_pixmap(clip=rect, dpi=dpi, alpha=False)

    media_ref = f"raster{next(_compteur)}"
    media[media_ref] = MediaItem(
        media_ref=media_ref, donnees=pixmap.tobytes("png"), extension="png"
    )
    return RasterEl(bbox=bbox, media_ref=media_ref)
```

- [ ] **Step 7 : brancher dans l'orchestration**

Dans `pdfexact/extract/document.py`, remplacer l'appel direct à `extraire_vectoriel` :

```python
            formes = extraire_vectoriel(page_pdf)
            degrades = page_a_des_degrades(doc, page_pdf)
            for cluster in regrouper(formes):
                if doit_rasteriser(cluster, degrades, seuil_raster):
                    boite = cluster[0].bbox
                    for forme in cluster[1:]:
                        boite = union(boite, forme.bbox)
                    page_ir.elements.append(
                        rasteriser_region(page_pdf, boite, document.media, dpi=dpi)
                    )
                    rapport.clusters_rasterises += 1
                else:
                    page_ir.elements.extend(cluster)
```

`extraire` prend désormais les paramètres `dpi: int = 300`, `seuil_raster: int = 300`, et un `rapport` — introduit à la Task 13. Jusque-là, utiliser un compteur local.

- [ ] **Step 8 : lancer toute la suite**

Run: `.converter/bin/pytest -v`
Attendu : tout passe, y compris le test de fidélité vectorielle — les fixtures simples ne déclenchent pas le repli.

- [ ] **Step 9 : commit**

```bash
git add pdfexact/ tests/
git commit -m "feat: cluster vector paths and fall back to per-region rasterization"
```

---

### Task 12 : liens

**Files:**
- Create: `pdfexact/extract/links.py`
- Modify: `pdfexact/render/drawing.py`
- Modify: `pdfexact/render/docx_writer.py`
- Modify: `pdfexact/extract/document.py`
- Create: `tests/extract/test_links.py`

**Interfaces:**
- Consumes: `LinkZone`, `TextBox`, `GestionnaireRelations.ajouter` avec `externe=True`.
- Produces: `pdfexact.extract.links.appliquer_liens(page, blocs) -> list[LinkZone]` — pose `Span.lien` sur les spans recouverts et retourne les liens de zone restants ; `pdfexact.render.drawing.zone_lien_xml(element, identifiant, z, rel_id) -> str`.

- [ ] **Step 1 : écrire le test**

```python
# tests/extract/test_links.py
import pymupdf

from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.links import appliquer_liens
from pdfexact.extract.text import extraire_texte


def _extraire(chemin):
    doc = pymupdf.open(chemin)
    try:
        page = doc[0]
        blocs = extraire_texte(page, collecter_polices(doc))
        zones = appliquer_liens(page, blocs)
        return blocs, zones
    finally:
        doc.close()


def test_le_lien_est_pose_sur_le_span_recouvert(pdf_liens):
    blocs, _zones = _extraire(pdf_liens)

    liens = [span.lien for bloc in blocs for ligne in bloc.lignes for span in ligne.spans]
    assert "https://example.org/" in liens


def test_aucune_zone_residuelle_quand_le_lien_couvre_du_texte(pdf_liens):
    _blocs, zones = _extraire(pdf_liens)

    assert zones == []


def test_un_lien_sans_texte_devient_une_zone(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_link({
        "kind": pymupdf.LINK_URI,
        "from": pymupdf.Rect(400, 400, 500, 450),
        "uri": "https://exemple.test/zone",
    })
    chemin = tmp_path / "zone.pdf"
    doc.save(chemin)
    doc.close()

    blocs, zones = _extraire(chemin)

    assert blocs == []
    assert len(zones) == 1
    assert zones[0].uri == "https://exemple.test/zone"


def test_un_lien_interne_porte_la_page_cible(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    doc[0].insert_link({
        "kind": pymupdf.LINK_GOTO,
        "from": pymupdf.Rect(100, 100, 200, 120),
        "page": 1,
    })
    chemin = tmp_path / "interne.pdf"
    doc.save(chemin)
    doc.close()

    _blocs, zones = _extraire(chemin)

    assert zones[0].page_cible == 1
    assert zones[0].uri is None
```

- [ ] **Step 2 : lancer pour voir échouer**

Run: `.converter/bin/pytest tests/extract/test_links.py -v`
Attendu : FAIL, `ModuleNotFoundError`.

- [ ] **Step 3 : implémenter**

```python
# pdfexact/extract/links.py
"""Liens.

Deux formes coexistent, et le partage est net : un lien qui recouvre du texte est porté
par les spans concernés et devient un w:hyperlink ; un lien qui ne recouvre aucun texte
devient une forme rectangulaire invisible cliquable.
"""
import pymupdf

from pdfexact.geometry import bbox_depuis_rect, se_chevauchent
from pdfexact.ir import LinkZone


def appliquer_liens(page, blocs) -> list[LinkZone]:
    """Pose les liens sur les spans recouverts, retourne les liens de zone restants."""
    zones: list[LinkZone] = []

    for lien in page.get_links():
        boite = bbox_depuis_rect(pymupdf.Rect(lien["from"]))
        uri = lien.get("uri")
        page_cible = lien.get("page") if lien.get("kind") == pymupdf.LINK_GOTO else None

        if page_cible is not None and page_cible < 0:
            page_cible = None

        recouvre_du_texte = False
        for bloc in blocs:
            if not se_chevauchent(bloc.bbox, boite):
                continue
            for ligne in bloc.lignes:
                if not se_chevauchent(ligne.bbox, boite):
                    continue
                for span in ligne.spans:
                    if uri:
                        span.lien = uri
                        recouvre_du_texte = True

        if not recouvre_du_texte:
            zones.append(LinkZone(bbox=boite, uri=uri, page_cible=page_cible))

    return zones
```

- [ ] **Step 4 : lancer les tests**

Run: `.converter/bin/pytest tests/extract/test_links.py -v`
Attendu : 4 passed.

- [ ] **Step 5 : rendre les liens de span**

Modifier `_run_xml` dans `pdfexact/render/drawing.py` pour envelopper le run quand `span.lien` est posé. `zone_texte_xml` reçoit un nouvel argument `relations` :

```python
def _run_xml(span, relations=None) -> str:
    # ... construction inchangée jusqu'au run ...
    run = (
        f'<w:r><w:rPr>{"".join(proprietes)}</w:rPr>'
        f'<w:t xml:space="preserve">{texte}</w:t></w:r>'
    )
    if span.lien and relations is not None:
        rel_id = relations.ajouter(span.lien, "hyperlink", externe=True)
        return f'<w:hyperlink r:id="{rel_id}">{run}</w:hyperlink>'
    return run
```

Et ajouter le rendu de zone :

```python
def zone_lien_xml(element, identifiant: int, z: int, rel_id: str) -> str:
    """Rend un lien de zone comme rectangle invisible cliquable."""
    largeur = max(element.bbox.largeur, 1)
    hauteur = max(element.bbox.hauteur, 1)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp>"
        f'<wps:cNvSpPr/><wps:spPr>'
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        f'<a:hlinkClick xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{rel_id}"/>'
        "</wps:spPr><wps:bodyPr/></wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(element.bbox, identifiant, z, f"Lien {identifiant}", contenu)
```

- [ ] **Step 6 : brancher**

Dans `_ancres_de_page` :

```python
        elif isinstance(element, LinkZone) and element.uri:
            compteur[0] += 1
            rel_id = relations.ajouter(element.uri, "hyperlink", externe=True)
            morceaux.append(zone_lien_xml(element, compteur[0], z, rel_id))
```

Dans `extraire`, après l'extraction du texte :

```python
            blocs = extraire_texte(page_pdf, polices)
            page_ir.elements.extend(blocs)
            page_ir.elements.extend(appliquer_liens(page_pdf, blocs))
```

Et propager `relations` jusqu'à `zone_texte_xml` puis `_run_xml`.

- [ ] **Step 7 : lancer toute la suite**

Run: `.converter/bin/pytest -v`
Attendu : tout passe. Vérifier manuellement qu'un docx produit depuis `pdf_liens` contient bien une relation de type hyperlink avec `TargetMode="External"`.

- [ ] **Step 8 : commit**

```bash
git add pdfexact/ tests/
git commit -m "feat: preserve text hyperlinks and area links"
```

---

### Task 13 : ligne de commande, rapport et robustesse par page

**Files:**
- Create: `pdfexact/report.py`
- Create: `pdfexact/cli.py`
- Modify: `pdfexact/extract/document.py`
- Modify: `pdfexact/__init__.py`
- Create: `tests/test_report.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces:
  - `pdfexact.report.Rapport` avec `pages_totales`, `pages_degradees: list[PageDegradee]`, `polices_non_embarquees: list[str]`, `clusters_rasterises: int`, `.vers_json() -> str`, `.resume() -> str`
  - `pdfexact.convertir(source, destination, **options) -> Rapport`
  - `pdfexact.cli.main(argv=None) -> int`

- [ ] **Step 1 : écrire le test du rapport**

```python
# tests/test_report.py
import json

from pdfexact.report import PageDegradee, Rapport


def test_un_rapport_neuf_est_vide():
    rapport = Rapport(pages_totales=10)

    assert rapport.pages_degradees == []
    assert rapport.clusters_rasterises == 0


def test_le_json_est_analysable():
    rapport = Rapport(pages_totales=3)
    rapport.pages_degradees.append(PageDegradee(index=1, motif="échec de l'extraction"))
    rapport.clusters_rasterises = 4

    donnees = json.loads(rapport.vers_json())

    assert donnees["pages_totales"] == 3
    assert donnees["pages_degradees"][0]["index"] == 1
    assert donnees["clusters_rasterises"] == 4


def test_le_resume_mentionne_les_pages_degradees():
    rapport = Rapport(pages_totales=40)
    rapport.pages_degradees.append(PageDegradee(index=7, motif="dégradé non transposable"))

    texte = rapport.resume()

    assert "40" in texte
    assert "1" in texte


def test_le_resume_dun_document_parfait_le_dit():
    texte = Rapport(pages_totales=5).resume()

    assert "5" in texte
```

- [ ] **Step 2 : implémenter le rapport**

```python
# pdfexact/report.py
"""Collecte des avertissements de conversion.

Aucune page ne fait échouer la conversion : une page qui pose problème est dégradée et
signalée ici. Le rapport est ce qui permet à l'utilisateur de savoir où regarder.
"""
import json
from dataclasses import asdict, dataclass, field


@dataclass
class PageDegradee:
    index: int
    motif: str


@dataclass
class Rapport:
    pages_totales: int = 0
    pages_degradees: list[PageDegradee] = field(default_factory=list)
    polices_non_embarquees: list[str] = field(default_factory=list)
    clusters_rasterises: int = 0

    def vers_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def resume(self) -> str:
        lignes = [f"{self.pages_totales} page(s) converties."]
        if self.pages_degradees:
            lignes.append(f"{len(self.pages_degradees)} page(s) dégradées :")
            for page in self.pages_degradees:
                lignes.append(f"  page {page.index + 1} : {page.motif}")
        if self.clusters_rasterises:
            lignes.append(f"{self.clusters_rasterises} zone(s) vectorielles rastérisées.")
        if self.polices_non_embarquees:
            lignes.append(
                f"{len(self.polices_non_embarquees)} police(s) substituées : "
                + ", ".join(sorted(set(self.polices_non_embarquees)))
            )
        return "\n".join(lignes)
```

- [ ] **Step 3 : lancer les tests du rapport**

Run: `.converter/bin/pytest tests/test_report.py -v`
Attendu : 4 passed.

- [ ] **Step 4 : rendre l'extraction tolérante aux pannes**

Dans `pdfexact/extract/document.py`, envelopper le traitement d'une page :

```python
        for index in indices:
            page_pdf = doc[index]
            page_ir = Page(
                index=index,
                largeur_emu=pt_vers_emu(page_pdf.rect.width),
                hauteur_emu=pt_vers_emu(page_pdf.rect.height),
            )
            try:
                _remplir_page(page_ir, page_pdf, doc, document, polices, dpi, seuil_raster, rapport)
            except Exception as erreur:
                if strict:
                    raise
                page_ir.elements = [
                    rasteriser_region(
                        page_pdf,
                        BBox(0, 0, page_ir.largeur_emu, page_ir.hauteur_emu),
                        document.media,
                        dpi=dpi,
                    )
                ]
                rapport.pages_degradees.append(PageDegradee(index=index, motif=str(erreur)))

            document.pages.append(page_ir)
```

où `_remplir_page` contient la logique existante — vectoriel, images, texte, liens, dans cet ordre.

- [ ] **Step 5 : écrire le test de la ligne de commande**

```python
# tests/test_cli.py
import json
import zipfile

from pdfexact.cli import main


def test_conversion_de_bout_en_bout(pdf_texte, tmp_path):
    sortie = tmp_path / "resultat.docx"

    code = main([str(pdf_texte), str(sortie)])

    assert code == 0
    assert sortie.exists()
    with zipfile.ZipFile(sortie) as z:
        assert "word/document.xml" in z.namelist()


def test_selection_de_pages(pdf_texte, tmp_path):
    sortie = tmp_path / "resultat.docx"

    code = main([str(pdf_texte), str(sortie), "--pages", "1"])

    assert code == 0


def test_le_rapport_est_ecrit_en_json(pdf_texte, tmp_path):
    sortie = tmp_path / "resultat.docx"
    rapport = tmp_path / "rapport.json"

    main([str(pdf_texte), str(sortie), "--report", str(rapport)])

    donnees = json.loads(rapport.read_text())
    assert donnees["pages_totales"] == 1


def test_un_fichier_introuvable_retourne_un_code_derreur(tmp_path):
    code = main([str(tmp_path / "absent.pdf"), str(tmp_path / "sortie.docx")])

    assert code != 0


def test_lanalyse_des_pages_accepte_les_intervalles():
    from pdfexact.cli import analyser_pages

    assert analyser_pages("1-3,7") == [0, 1, 2, 6]


def test_lanalyse_des_pages_rejette_le_desordre():
    import pytest

    from pdfexact.cli import analyser_pages

    with pytest.raises(ValueError):
        analyser_pages("5-2")
```

- [ ] **Step 6 : implémenter la ligne de commande**

```python
# pdfexact/cli.py
"""Interface en ligne de commande."""
import argparse
import sys
from pathlib import Path

from pdfexact.extract.document import extraire
from pdfexact.render.package import ecrire_docx
from pdfexact.report import Rapport


def analyser_pages(expression: str) -> list[int]:
    """Traduit « 1-3,7 » en indices 0-based [0, 1, 2, 6]."""
    indices: list[int] = []
    for morceau in expression.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if "-" in morceau:
            debut, fin = morceau.split("-", 1)
            premier, dernier = int(debut), int(fin)
            if premier > dernier:
                raise ValueError(f"intervalle inversé : {morceau}")
            indices.extend(range(premier - 1, dernier))
        else:
            indices.append(int(morceau) - 1)
    return indices


def convertir(source, destination, pages=None, dpi=300, seuil_raster=300, strict=False) -> Rapport:
    """Convertit un PDF en docx. Retourne le rapport de conversion."""
    rapport = Rapport()
    document = extraire(
        source, pages=pages, dpi=dpi, seuil_raster=seuil_raster, strict=strict, rapport=rapport
    )
    rapport.pages_totales = len(document.pages)
    rapport.polices_non_embarquees = [
        asset.famille for asset in document.polices.values() if not asset.embarquee
    ]
    ecrire_docx(document, destination)
    return rapport


def main(argv=None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="pdfexact",
        description="Convertit un PDF natif en DOCX visuellement fidèle.",
    )
    analyseur.add_argument("source", help="le PDF à convertir")
    analyseur.add_argument("destination", help="le .docx à produire")
    analyseur.add_argument("--pages", help="sélection de pages, par exemple 1-5,8")
    analyseur.add_argument("--dpi", type=int, default=300, help="résolution des zones rastérisées")
    analyseur.add_argument(
        "--raster-threshold",
        type=int,
        default=300,
        dest="seuil_raster",
        help="nombre de chemins déclenchant le repli raster",
    )
    analyseur.add_argument(
        "--strict", action="store_true", help="échoue au lieu de dégrader une page"
    )
    analyseur.add_argument("--report", help="écrit le rapport JSON dans ce fichier")

    arguments = analyseur.parse_args(argv)

    source = Path(arguments.source)
    if not source.exists():
        print(f"fichier introuvable : {source}", file=sys.stderr)
        return 2

    try:
        pages = analyser_pages(arguments.pages) if arguments.pages else None
    except ValueError as erreur:
        print(f"sélection de pages invalide : {erreur}", file=sys.stderr)
        return 2

    try:
        rapport = convertir(
            source,
            Path(arguments.destination),
            pages=pages,
            dpi=arguments.dpi,
            seuil_raster=arguments.seuil_raster,
            strict=arguments.strict,
        )
    except Exception as erreur:
        print(f"échec de la conversion : {erreur}", file=sys.stderr)
        return 1

    print(rapport.resume())
    if arguments.report:
        Path(arguments.report).write_text(rapport.vers_json(), encoding="utf-8")

    return 0
```

- [ ] **Step 7 : exposer l'API publique**

```python
# pdfexact/__init__.py
"""Conversion de PDF natifs en DOCX visuellement fidèles."""
from pdfexact.cli import convertir
from pdfexact.report import Rapport

__all__ = ["convertir", "Rapport"]
```

- [ ] **Step 8 : lancer toute la suite**

Run: `.converter/bin/pytest -v`
Attendu : tout passe.

- [ ] **Step 9 : vérifier la commande installée**

```bash
.converter/bin/pdfexact --help
.converter/bin/pdfexact <un-vrai-pdf.pdf> /tmp/resultat.docx --report /tmp/rapport.json
```

Attendu : la conversion aboutit, le résumé s'affiche, le JSON est écrit. Ouvrir le docx pour contrôle visuel.

- [ ] **Step 10 : commit**

```bash
git add pdfexact/ tests/
git commit -m "feat: add CLI, conversion report, and per-page error recovery"
```

---

## Écart assumé avec la spec

La spec §7 liste une option `--no-embed-fonts`. Ce plan ne l'implémente pas, et c'est délibéré : les treize tâches livrent le **mode police système** comme unique comportement. L'embarquement de polices n'est pas branché dans le writer — seule son infrastructure (obfuscation, décision) est produite, par la Task 3.

Ajouter un drapeau qui ne commute rien serait pire que de ne pas l'avoir. L'option apparaîtra en même temps que l'embarquement lui-même, dans le prolongement décrit ci-dessous. Toutes les autres options de la spec §7 sont présentes à la Task 13.

Conséquence sur la fidélité : les glyphes proviennent de la police système la plus proche, pas de celle du PDF. La mise en page reste exacte grâce à la correction d'espacement de la Task 8. C'est exactement le mode de repli que la spec §8 prévoit, et il est conforme aux critères de réussite.

## Après le plan

Une fois les treize tâches passées, le projet convertit, mesure sa fidélité et signale ses dégradations. Les suites naturelles, hors périmètre de ce plan :

- **Élargir le corpus de référence** avec de vrais documents (facture, rapport multi-colonnes, document avec filigrane) et relever le seuil SSIM de 0,90 à 0,95.
- **Embarquer les polices** dans le writer si la Task 3 a conclu favorablement — l'infrastructure d'obfuscation existe, il reste à écrire `fontTable.xml` et à brancher les parties `word/fonts/`.
- **Affiner la détection de complexité** : masques de clipping et modes de fusion, qui ne sont pour l'instant pas détectés (seuls les shadings et la densité de chemins le sont).
- **Rotation du texte et des images**, laissée de côté : l'IR ne porte pas de champ de rotation, et les PDF concernés sortiront droits.
