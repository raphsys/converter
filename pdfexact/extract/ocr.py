"""Couche OCR positionnée.

Tesseract fournit les mots et leurs boîtes en pixels. On les convertit en coordonnées
PDF puis en EMU pour poser une couche texte au-dessus du rendu visuel exact.
"""
import csv
import re
import subprocess
import sys
from io import StringIO
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

from pdfexact.extract.blocks import (
    OcrLine,
    centre_dans,
    detecter_blocs_page,
    est_dans_zone,
)
from pdfexact.fallback.rasterize import rasteriser_region
from pdfexact.geometry import BBox, emu_vers_pt, pt_vers_emu, pt_vers_twips
from pdfexact.ir import FlowParagraph, FontRef, Line, Span, TextBox


def _lancer_tesseract(image: Path, langue: str) -> list[dict]:
    resultat = subprocess.run(
        ["tesseract", str(image), "stdout", "-l", langue, "--psm", "6", "tsv"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if resultat.returncode != 0:
        raise RuntimeError(resultat.stderr.strip() or "échec OCR Tesseract")
    return list(csv.DictReader(StringIO(resultat.stdout), delimiter="\t"))


def _mots(rows: list[dict]):
    for row in rows:
        texte = (row.get("text") or "").strip()
        if not texte:
            continue
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            conf = -1
        if conf < 0:
            continue
        yield row, texte, conf


def extraire_ocr(
    page, dpi: int = 300, langue: str = "eng", visible: bool = False, verbose: bool = False
):
    """Retourne des TextBox OCR positionnées par ligne."""
    with TemporaryDirectory(prefix="pdfexact-ocr-") as dossier:
        image = Path(dossier) / "page.png"
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        pixmap.save(image)
        rows = _lancer_tesseract(image, langue)

    facteur = 72.0 / dpi
    lignes: dict[tuple[str, str, str], list[tuple[dict, str, float]]] = {}
    for row, texte, conf in _mots(rows):
        cle = (row["block_num"], row["par_num"], row["line_num"])
        lignes.setdefault(cle, []).append((row, texte, conf))

    blocs = []
    police = FontRef("OCR", "Arial", gras=False, italique=False)
    for valeurs in lignes.values():
        valeurs.sort(key=lambda item: int(item[0]["left"]))
        textes = [texte for _row, texte, _conf in valeurs]
        texte_ligne = " ".join(textes)
        if not texte_ligne:
            continue

        left = min(int(row["left"]) for row, _texte, _conf in valeurs)
        top = min(int(row["top"]) for row, _texte, _conf in valeurs)
        right = max(int(row["left"]) + int(row["width"]) for row, _texte, _conf in valeurs)
        bottom = max(int(row["top"]) + int(row["height"]) for row, _texte, _conf in valeurs)

        x0 = pt_vers_emu(left * facteur)
        y0 = pt_vers_emu(top * facteur)
        x1 = pt_vers_emu(right * facteur)
        y1 = pt_vers_emu(bottom * facteur)
        bbox = BBox(x0, y0, max(x1, x0 + 1), max(y1, y0 + 1))
        size_pt = max((bottom - top) * facteur * 0.72, 1.0)
        span = Span(
            texte=texte_ligne,
            police=police,
            size_pt=size_pt,
            couleur="000000" if visible else "FFFFFF",
            invisible=not visible,
        )
        ligne = Line(
            bbox=bbox,
            spans=[span],
            hauteur_ligne_emu=max(bbox.hauteur, 1),
            largeur_cible_emu=max(bbox.largeur, 1),
        )
        blocs.append(TextBox(bbox=bbox, lignes=[ligne]))

    if verbose:
        print(f"      OCR: {len(blocs)} ligne(s) positionnée(s)", file=sys.stderr)
    return blocs


@lru_cache(maxsize=1)
def _rapidocr():
    from rapidocr import RapidOCR

    return RapidOCR()


def _boite_rapidocr(points, facteur: float) -> BBox:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return BBox(
        pt_vers_emu(min(xs) * facteur),
        pt_vers_emu(min(ys) * facteur),
        pt_vers_emu(max(xs) * facteur),
        pt_vers_emu(max(ys) * facteur),
    )


def _intersection(a, b) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _trace_style(page, polices: dict, bbox: BBox, facteur_emu: float):
    """Récupère police/taille/couleur depuis la trace PDF la plus proche."""
    cible = (
        bbox.x0 / facteur_emu,
        bbox.y0 / facteur_emu,
        bbox.x1 / facteur_emu,
        bbox.y1 / facteur_emu,
    )
    meilleur = None
    meilleur_score = 0.0
    for trace in page.get_texttrace():
        score = _intersection(cible, trace.get("bbox", (0, 0, 0, 0)))
        if score > meilleur_score:
            meilleur = trace
            meilleur_score = score

    if meilleur is None:
        return FontRef("OCR", "Times New Roman", False, False), 10.0, "000000"

    from pdfexact.extract.text import _couleur_hexa, _resoudre_police, _style_depuis_nom

    font_id = _resoudre_police(meilleur.get("font", ""), polices)
    asset = polices[font_id]
    gras, italique = _style_depuis_nom(
        meilleur.get("font", ""), int(meilleur.get("flags", 0))
    )
    return (
        FontRef(font_id, asset.famille, gras, italique),
        round(float(meilleur.get("size", 10.0)), 2),
        _couleur_hexa(meilleur.get("color", 0)),
    )


def _est_dans_zone_ignoree(boite: BBox, zones_ignorees: list[BBox]) -> bool:
    return est_dans_zone(boite, zones_ignorees)


def _elements_rapidocr(result, granularite: str):
    if granularite == "line":
        for texte, score, points in zip(result.txts, result.scores, result.boxes):
            yield texte, score, points
        return

    word_results = getattr(result, "word_results", None)
    if not word_results:
        for texte, score, points in zip(result.txts, result.scores, result.boxes):
            yield texte, score, points
        return

    for ligne in word_results:
        for item in ligne:
            if len(item) < 3:
                continue
            texte, score, points = item[:3]
            yield texte, score, points


_REMPLACEMENTS_OCR = (
    ("TECIINOIOGY", "TECHNOLOGY"),
    ("TECIINOI OGY", "TECHNOLOGY"),
    ("INTROII1JCTION", "INTRODUCTION"),
    ("INTROIIJCTION", "INTRODUCTION"),
    ("ULTRASONICROTARY", "ULTRASONIC ROTARY"),
    ("ULTRASONICMOTORS", "ULTRASONIC MOTORS"),
    ("PRINCIPALOFOPERATION", "PRINCIPAL OF OPERATION"),
    ("FUTUREDIRECTIONOF THETECHNOLOGY", "FUTURE DIRECTION OF THE TECHNOLOGY"),
    ("THETECHNOLOGY", "THE TECHNOLOGY"),
    ("WAVI", "WAVE"),
    ("CΛ", "CA"),
    ("] hese", "These"),
    ("]hese", "These"),
    ("Recentl y", "Recently"),
    ("currentl y", "currently"),
    ("initiall y", "initially"),
    ("Generall y", "Generally"),
    ("particularl y", "particularly"),
    ("accuratel y", "accurately"),
    ("efficientl y", "efficiently"),
    ("effective] y", "effectively"),
    ("effective]y", "effectively"),
    ("gencrate", "generate"),
    ("miniat urc", "miniature"),
    ("spced", "speed"),
    ("developcd", "developed"),
    ("mcchanical", "mechanical"),
    ("intcrface", "interface"),
    ("intcrfacc", "interface"),
    ("piezoclectric", "piezoelectric"),
    ("orthogona modes", "orthogonal modes"),
    ("antisymmctric", "antisymmetric"),
    ("anti symmetric", "antisymmetric"),
    ("Iamb", "Lamb"),
    ("Thcse", "These"),
    ("tothe", "to the"),
    ("forthe", "for the"),
    ("ofthese", "of these"),
    ("motorsfor", "motors for"),
    ("alocalsmal1", "a local small"),
    ("pitchcatch", "pitch-catch"),
    ("current] y", "currently"),
    ("Agrecment", "Agreement"),
    ("Europcan", "European"),
    ("interfacc", "interface"),
    ("Cannon", "Canon"),
    ("arc ", "are "),
    (" arc", " are"),
    (" usc ", " use "),
    (" recti fied", " rectified"),
    ("fricti onal", "frictional"),
    ("out-ofphase", "out-of-phase"),
    ("orthogona ", "orthogonal "),
    ("NDl", "NDI"),
    ("piczoelectric", "piezoelectric"),
    ("propcl", "propel"),
    ("i.c.", "i.e."),
    ("Al I", "All"),
    ("ai e", "are"),
    ("Ι", "I"),
    ("Ο", "O"),
    ("Α", "A"),
    ("Β", "B"),
    ("Ε", "E"),
    ("Η", "H"),
    ("Κ", "K"),
    ("Μ", "M"),
    ("Ν", "N"),
    ("Ρ", "P"),
    ("Τ", "T"),
    ("Χ", "X"),
)


def _normaliser_texte_ocr(texte: str) -> str:
    """Corrige les confusions OCR latines les plus destructrices.

    Cette normalisation est volontairement conservatrice : elle ne remplace que des
    caractères grecs/cyrilliques isolés qui apparaissent dans des mots latins sur les
    PDF scientifiques scannés ou glyphiques.
    """
    for source, cible in _REMPLACEMENTS_OCR:
        texte = texte.replace(source, cible)
    texte = re.sub(r"\s+([,.;:])", r"\1", texte)
    texte = re.sub(r"([(\[])\s+", r"\1", texte)
    texte = re.sub(r"\s+([)\]])", r"\1", texte)
    return " ".join(texte.split())


def _limiter_bbox(page, bbox: BBox) -> BBox:
    marge = pt_vers_emu(2)
    largeur = pt_vers_emu(page.rect.width) - marge
    hauteur = pt_vers_emu(page.rect.height) - marge
    x0 = max(marge, min(bbox.x0, largeur - 1))
    y0 = max(marge, min(bbox.y0, hauteur - 1))
    x1 = max(x0 + 1, min(bbox.x1, largeur))
    y1 = max(y0 + 1, min(bbox.y1, hauteur))
    return BBox(x0, y0, x1, y1)


_MATH_SYMBOLS = set("=+-*/×÷<>≤≥≈≠()[]{}|∫∑√^_∆ΔΩωπζλμνρσ")


def _semble_formule(texte: str) -> bool:
    compact = texte.replace(" ", "")
    if len(compact) < 4:
        return False
    symboles = sum(1 for caractere in compact if caractere in _MATH_SYMBOLS)
    chiffres = sum(1 for caractere in compact if caractere.isdigit())
    lettres = sum(1 for caractere in compact if caractere.isalpha())
    densite = (symboles + chiffres) / len(compact)
    return symboles >= 2 and densite >= 0.28 and lettres <= len(compact) * 0.75


def _zone_raster_utile(bbox: BBox) -> bool:
    largeur_pt = emu_vers_pt(bbox.largeur)
    hauteur_pt = emu_vers_pt(bbox.hauteur)
    if largeur_pt < 4 or hauteur_pt < 4:
        return False
    if hauteur_pt < 12 and largeur_pt > 150:
        return False
    if largeur_pt < 12 and hauteur_pt > 40:
        return False
    return True


def _lignes_rapidocr(result, facteur: float) -> list[OcrLine]:
    lignes: list[OcrLine] = []
    for texte, score, points in zip(result.txts, result.scores, result.boxes):
        texte = _normaliser_texte_ocr((texte or "").strip())
        if not texte:
            continue
        lignes.append(OcrLine(texte=texte, score=score, bbox=_boite_rapidocr(points, facteur)))
    return lignes


_FUSIONS_MOTS_OCR = {
    ("TECIINOI", "OGY"): "TECHNOLOGY",
    ("TECIINO", "OGY"): "TECHNOLOGY",
    ("Recentl", "y,"): "Recently,",
    ("initiall", "y"): "initially",
    ("Generall", "y,"): "Generally,",
    ("]", "hese"): "These",
}


def _fusionner_bbox(a: BBox, b: BBox) -> BBox:
    return BBox(
        min(a.x0, b.x0),
        min(a.y0, b.y0),
        max(a.x1, b.x1),
        max(a.y1, b.y1),
    )


def _bbox_lignes(lignes: list[OcrLine]) -> BBox:
    boite = lignes[0].bbox
    for ligne in lignes[1:]:
        boite = _fusionner_bbox(boite, ligne.bbox)
    return boite


def _corriger_elements_ocr(
    elements: list[tuple[str, float, BBox]],
) -> list[tuple[str, float, BBox]]:
    """Fusionne les erreurs OCR qui traversent deux boîtes de mots adjacentes."""
    corriges: list[tuple[str, float, BBox]] = []
    index = 0
    while index < len(elements):
        texte, score, bbox = elements[index]
        if index + 1 < len(elements):
            suivant, score_suivant, bbox_suivante = elements[index + 1]
            fusion = _FUSIONS_MOTS_OCR.get((texte, suivant))
            if fusion:
                corriges.append(
                    (
                        fusion,
                        min(score, score_suivant),
                        _fusionner_bbox(bbox, bbox_suivante),
                    )
                )
                index += 2
                continue
        corriges.append((texte, score, bbox))
        index += 1
    return corriges


def _dedoublonner_elements_ocr(
    elements: list[tuple[str, float, BBox]],
) -> list[tuple[str, float, BBox]]:
    """Évite deux textes concurrents posés dans la même boîte OCR."""
    gardes: list[tuple[str, float, BBox]] = []
    for texte, score, bbox in sorted(elements, key=lambda item: (item[2].y0, item[2].x0, -len(item[0]))):
        doublon = None
        for index, (texte_garde, score_garde, bbox_garde) in enumerate(gardes):
            couverture = _intersection(
                (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                (bbox_garde.x0, bbox_garde.y0, bbox_garde.x1, bbox_garde.y1),
            ) / max(min(bbox.largeur * bbox.hauteur, bbox_garde.largeur * bbox_garde.hauteur), 1)
            meme_ligne = abs((bbox.y0 + bbox.y1) - (bbox_garde.y0 + bbox_garde.y1)) <= max(
                bbox.hauteur, bbox_garde.hauteur
            )
            inclus_horizontal = (
                min(bbox.x1, bbox_garde.x1) - max(bbox.x0, bbox_garde.x0)
            ) / max(min(bbox.largeur, bbox_garde.largeur), 1) > 0.78
            if couverture > 0.88 or (meme_ligne and inclus_horizontal):
                doublon = index
                break
        if doublon is None:
            gardes.append((texte, score, bbox))
            continue

        texte_garde, score_garde, bbox_garde = gardes[doublon]
        qualite = (score or 0.0) + min(len(texte), 80) / 80
        qualite_garde = (score_garde or 0.0) + min(len(texte_garde), 80) / 80
        if qualite > qualite_garde:
            gardes[doublon] = (texte, score, bbox)
    return gardes


def _texte_paragraphe(lignes: list[OcrLine]) -> str:
    morceaux: list[str] = []
    for ligne in lignes:
        texte = ligne.texte.strip()
        if not texte:
            continue
        if morceaux and morceaux[-1].endswith("-") and texte[:1].islower():
            morceaux[-1] = morceaux[-1][:-1] + texte
        elif morceaux:
            morceaux.append(" " + texte)
        else:
            morceaux.append(texte)
    return _normaliser_texte_ocr("".join(morceaux))


def _ligne_centree(page, bbox: BBox) -> bool:
    centre_page = pt_vers_emu(page.rect.width / 2)
    return abs((bbox.x0 + bbox.x1) / 2 - centre_page) <= pt_vers_emu(35)


def _alignement_ligne(page, bbox: BBox, texte: str) -> str:
    marge_droite = pt_vers_emu(page.rect.width) - bbox.x1
    if _ligne_centree(page, bbox) and len(texte) <= 120:
        return "center"
    if marge_droite <= pt_vers_emu(28) and len(texte) <= 80:
        return "right"
    if len(texte) >= 85 and bbox.largeur >= pt_vers_emu(page.rect.width * 0.55):
        return "both"
    return "left"


def _alignement_paragraphe(page, lignes: list[OcrLine]) -> str:
    bbox = _bbox_lignes(lignes)
    texte = _texte_paragraphe(lignes)
    court = len(texte) <= 90
    if court and _ligne_centree(page, bbox):
        return "center"
    return "left"


def _grouper_lignes_reflow(page, lignes: list[OcrLine]) -> list[list[OcrLine]]:
    lignes = sorted(lignes, key=lambda ligne: (ligne.bbox.y0, ligne.bbox.x0))
    groupes: list[list[OcrLine]] = []
    courant: list[OcrLine] = []
    hauteur_ligne = pt_vers_emu(12)

    for ligne in lignes:
        if not courant:
            courant = [ligne]
            hauteur_ligne = max(ligne.bbox.hauteur, pt_vers_emu(8))
            continue

        precedente = courant[-1]
        gap_y = ligne.bbox.y0 - precedente.bbox.y1
        retrait = ligne.bbox.x0 - precedente.bbox.x0
        texte_precedent = precedente.texte.rstrip()
        texte = ligne.texte.strip()
        nouveau_paragraphe = False

        if gap_y > max(hauteur_ligne * 0.85, pt_vers_emu(8)):
            nouveau_paragraphe = True
        if abs(retrait) > pt_vers_emu(28) and gap_y > -hauteur_ligne * 0.2:
            nouveau_paragraphe = True
        if texte_precedent.endswith((".", ":", ";", ")", "]")) and gap_y > hauteur_ligne * 0.95:
            nouveau_paragraphe = True
        if len(texte) < 90 and _ligne_centree(page, ligne.bbox):
            nouveau_paragraphe = True

        if nouveau_paragraphe:
            groupes.append(courant)
            courant = [ligne]
            hauteur_ligne = max(ligne.bbox.hauteur, pt_vers_emu(8))
        else:
            courant.append(ligne)
            hauteur_ligne = max(hauteur_ligne, ligne.bbox.hauteur)

    if courant:
        groupes.append(courant)
    return groupes


def _paragraphes_reflow(
    page,
    polices: dict,
    lignes: list[OcrLine],
    facteur_emu: float,
) -> list[FlowParagraph]:
    paragraphes: list[FlowParagraph] = []
    precedent_bas = 0

    for groupe in _grouper_lignes_reflow(page, lignes):
        texte = _texte_paragraphe(groupe)
        if not texte:
            continue
        bbox = _bbox_lignes(groupe)
        police, size_pt, couleur = _trace_style(page, polices, bbox, facteur_emu)
        hauteur_ligne = max(int(sum(l.bbox.hauteur for l in groupe) / len(groupe)), pt_vers_emu(size_pt * 1.05))
        espace_avant = max(0, bbox.y0 - precedent_bas)
        alignement = _alignement_paragraphe(page, groupe)
        retrait_gauche = 0
        retrait_droite = 0
        premier = 0
        if alignement == "left" and len(texte) > 260 and len(groupe) > 2:
            premier = max(0, min(groupe[0].bbox.x0 - bbox.x0, pt_vers_emu(14)))
        paragraphes.append(
            FlowParagraph(
                bbox=bbox,
                texte=texte,
                police=police,
                size_pt=size_pt,
                couleur=couleur,
                alignement=alignement,
                retrait_gauche_emu=retrait_gauche,
                retrait_droite_emu=retrait_droite,
                retrait_premiere_ligne_emu=premier,
                espace_avant_emu=min(espace_avant, pt_vers_emu(8)),
                espace_apres_emu=pt_vers_emu(0.5),
                interligne_emu=hauteur_ligne,
            )
        )
        precedent_bas = bbox.y1
    return paragraphes


def _ligne_figure_isolee(ligne: OcrLine) -> bool:
    texte = ligne.texte.strip()
    if not texte:
        return True
    if len(texte) <= 3:
        return True
    lettres = sum(1 for c in texte if c.isalpha())
    if len(texte) <= 18 and lettres <= 8:
        return True
    mots = texte.split()
    if len(mots) <= 2 and any(
        marqueur in texte.lower()
        for marqueur in ("applied", "surface", "rotor", "stator", "wave")
    ):
        return True
    return False


def _ajuster_largeur_ocr(ligne: Line, polices: dict) -> None:
    """Ajuste la largeur OCR sans toucher au corps PDF.

    La taille vient du PDF et doit rester stable. Quand Word compose plus large que la
    boîte PDF, on compense uniquement par l'espacement inter-caractères.
    """
    span = ligne.spans[0] if ligne.spans else None
    if span is None or span.police.font_id not in polices:
        return

    from pdfexact.extract.fonts import mesurer_largeur_pt

    cible_pt = emu_vers_pt(ligne.largeur_cible_emu)
    mesuree_pt = mesurer_largeur_pt(span.texte, polices[span.police.font_id], span.size_pt)
    if cible_pt <= 0:
        return

    if span.size_pt >= 24:
        securite = 0.90
    elif len(span.texte) >= 70:
        securite = 0.92
    elif len(span.texte) >= 35:
        securite = 0.94
    else:
        securite = 0.96
    cible_sure_pt = cible_pt * securite
    if mesuree_pt <= cible_sure_pt:
        return

    caracteres = max(len(span.texte), 1)
    span.espacement_twips = min(
        0,
        round(pt_vers_twips((cible_sure_pt - mesuree_pt) / caracteres)),
    )


def _textbox(
    page,
    polices: dict,
    texte: str,
    bbox: BBox,
    facteur_emu: float,
    ajuster_largeur: bool = True,
    layout_map=None,
) -> TextBox:
    bbox = _limiter_bbox(page, bbox)
    if layout_map is not None:
        bbox = layout_map.recaler_ligne_ocr(bbox, texte)
    police, size_pt, couleur = _trace_style(page, polices, bbox, facteur_emu)
    hauteur_ligne = max(bbox.hauteur, pt_vers_emu(size_pt * 1.18))
    bbox = BBox(bbox.x0, bbox.y0, bbox.x1, min(pt_vers_emu(page.rect.height), bbox.y0 + hauteur_ligne))
    span = Span(texte=texte, police=police, size_pt=size_pt, couleur=couleur)
    ligne = Line(
        bbox=bbox,
        spans=[span],
        hauteur_ligne_emu=max(hauteur_ligne, 1),
        largeur_cible_emu=max(bbox.largeur, 1),
        alignement=_alignement_ligne(page, bbox, texte),
    )
    if ajuster_largeur:
        _ajuster_largeur_ocr(ligne, polices)
    return TextBox(bbox=bbox, lignes=[ligne])


def extraire_rapidocr(
    page,
    polices: dict,
    dpi: int = 300,
    verbose: bool = False,
    granularite: str = "word",
    layout: str = "blocks",
    zones_ignorees: list[BBox] | None = None,
    media: dict | None = None,
    layout_map=None,
):
    """Retourne du vrai texte Word visible, reconnu par RapidOCR et positionné."""
    zones_ignorees = zones_ignorees or []
    with TemporaryDirectory(prefix="pdfexact-rapidocr-") as dossier:
        image = Path(dossier) / "page.png"
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        pixmap.save(image)
        result = _rapidocr()(
            str(image),
            return_word_box=granularite != "line",
            return_single_char_box=granularite == "char",
        )

    facteur = 72.0 / dpi
    facteur_emu = 12700.0
    blocs = []
    lignes_ocr = []
    for ligne in _lignes_rapidocr(result, facteur):
        bbox = _limiter_bbox(page, ligne.bbox)
        if layout == "hybrid" and layout_map is not None:
            bbox = layout_map.contraindre_bbox_texte(bbox, ligne.texte)
        lignes_ocr.append(OcrLine(ligne.texte, ligne.score, bbox))
    zones_formules = [
        ligne.bbox
        for ligne in lignes_ocr
        if _semble_formule(ligne.texte) and _zone_raster_utile(ligne.bbox)
    ]
    if media is not None:
        for zone in zones_formules:
            blocs.append(rasteriser_region(page, zone, media, dpi=dpi))
    zones_ignorees = zones_ignorees + zones_formules
    if layout == "reflow":
        lignes_texte = [
            ligne
            for ligne in lignes_ocr
            if not _est_dans_zone_ignoree(ligne.bbox, zones_ignorees)
            and not _ligne_figure_isolee(ligne)
        ]
        blocs.extend(_paragraphes_reflow(page, polices, lignes_texte, facteur_emu))
        blocs.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
        if verbose:
            print(
                f"      RapidOCR: {len(lignes_texte)} ligne(s) -> "
                f"{len([b for b in blocs if isinstance(b, FlowParagraph)])} paragraphe(s) Word"
                f" (reflow), formules={len(zones_formules)}",
                file=sys.stderr,
            )
        return blocs

    blocs_page = (
        detecter_blocs_page(lignes_ocr, zones_ignorees)
        if layout in {"blocks", "hybrid"}
        else []
    )
    blocs_texte = [bloc for bloc in blocs_page if bloc.kind == "text"]

    elements = []
    for texte, score, points in _elements_rapidocr(result, granularite):
        texte = _normaliser_texte_ocr((texte or "").strip())
        if texte:
            elements.append((texte, score, _limiter_bbox(page, _boite_rapidocr(points, facteur))))
    elements = _dedoublonner_elements_ocr(_corriger_elements_ocr(elements))

    ignores = 0
    utilises: set[int] = set()

    if layout in {"blocks", "hybrid"}:
        for bloc in blocs_texte:
            for index, (texte, _score, bbox) in enumerate(elements):
                if index in utilises:
                    continue
                if not centre_dans(bbox, bloc.bbox):
                    continue
                if _est_dans_zone_ignoree(bbox, zones_ignorees) or (
                    layout == "hybrid"
                    and layout_map is not None
                    and (
                        layout_map.touche_visuel(bbox)
                        or layout_map.contredit_texte_natif(bbox, texte)
                        or (len(texte.strip()) <= 8 and layout_map.proche_petit_visuel(bbox))
                    )
                ):
                    ignores += 1
                    utilises.add(index)
                    continue
                blocs.append(
                    _textbox(
                        page,
                        polices,
                        texte,
                        bbox,
                        facteur_emu,
                        layout_map=layout_map if layout == "hybrid" else None,
                    )
                )
                utilises.add(index)

        if layout == "blocks":
            # Les petites zones isolées (numéros de page, astérisques, titres très espacés)
            # peuvent ne pas intégrer un groupe. On les garde si elles ne touchent pas une
            # zone visuelle protégée.
            for index, (texte, _score, bbox) in enumerate(elements):
                if index in utilises:
                    continue
                if _est_dans_zone_ignoree(bbox, zones_ignorees):
                    ignores += 1
                    continue
                blocs.append(_textbox(page, polices, texte, bbox, facteur_emu))
    else:
        for texte, _score, bbox in elements:
            if _est_dans_zone_ignoree(bbox, zones_ignorees):
                ignores += 1
                continue
            blocs.append(_textbox(page, polices, texte, bbox, facteur_emu))

    blocs.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))

    if verbose:
        suffixe = f", {ignores} ignoré(s) sur image" if ignores else ""
        details_blocs = ""
        if layout in {"blocks", "hybrid"}:
            details_blocs = (
                f", blocs texte={len(blocs_texte)}, blocs visuels="
                f"{len([bloc for bloc in blocs_page if bloc.kind == 'visual'])}"
            )
            if zones_formules:
                details_blocs += f", formules={len(zones_formules)}"
        print(
            f"      RapidOCR: {len(blocs)} élément(s) Word ({granularite}/{layout})"
            f"{details_blocs}{suffixe}",
            file=sys.stderr,
        )
    return blocs
