"""identifier(): the IDENTIFICATION step of the pipeline, and its catalogue."""
from __future__ import annotations

import json
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from pdfexact.geometry import BBox, emu_vers_pt
from pdfexact.identification.base import Decision
from pdfexact.identification.doclayout import creer_identificateur_doclayout
from pdfexact.identification.expressions import detecteurs_par_defaut, trouver
from pdfexact.identification.formulenet import creer_identificateur_formulenet
from pdfexact.identification.identificateurs import contexte_page, decider_element, nature, registre_par_defaut, texte
from pdfexact.identification.referentiel import CHEMIN, famille
from pdfexact.identification.vision import creer_identificateur_vision

SCHEMA = "pdfexact.identification/1"
# Resolutions of what the vision model is shown: a zone, or the page with the element framed.
DPI_ZONE = 150
DPI_PAGE = 100
CADRE_ROUGE_PX = 3


@dataclass(frozen=True)
class ElementIdentifie:
    id: str
    page_index: int
    element_index: int
    ligne_index: int | None
    bbox: tuple[float, float, float, float]
    type: str
    famille: str
    statut: str
    confiance: float
    alternatives: tuple[tuple[str, float], ...]
    indices: tuple[str, ...]


@dataclass(frozen=True)
class ExpressionIdentifiee:
    id: str
    element_id: str
    page_index: int
    element_index: int
    debut: int
    fin: int
    texte: str
    type: str
    famille: str
    confiance: float
    indice: str


@dataclass(frozen=True)
class ResultatIdentification:
    segmentation: object
    elements: tuple[ElementIdentifie, ...]
    expressions: tuple[ExpressionIdentifiee, ...]
    identificateurs: tuple[str, ...]
    detecteurs: tuple[str, ...]


def _bbox_pt(bbox: BBox) -> tuple[float, float, float, float]:
    """[x, y, width, height] in points, origin top-left."""
    return tuple(round(emu_vers_pt(value), 3) for value in (bbox.x0, bbox.y0, bbox.largeur, bbox.hauteur))


def _rendeurs(pdf, page) -> dict:
    """``rendre``: the zone; ``rendre_marque``: the page with the zone framed in red;
    ``rendre_page``: the whole page at a scale.

    ``cote_px`` renders the longest side at that size (a model's input size, so it is
    neither upscaled nor blurred); otherwise at a fixed resolution.
    """
    pdf_page = pdf[page.index]

    def _rect(bbox: BBox):
        # IR boxes and PyMuPDF clips are both in the displayed (rotated) space.
        return pymupdf.Rect(*(emu_vers_pt(v) for v in (bbox.x0, bbox.y0, bbox.x1, bbox.y1)))

    def _zoom(rect, cote_px, dpi) -> float:
        return cote_px / max(rect.width, rect.height, 1) if cote_px else dpi / 72.0

    def rendre(bbox: BBox, cote_px: int | None = None) -> Image.Image:
        rect = _rect(bbox)
        zoom = _zoom(rect, cote_px, DPI_ZONE)
        pixmap = pdf_page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    def rendre_marque(bbox: BBox, cote_px: int | None = None) -> Image.Image:
        echelle = _zoom(pdf_page.rect, cote_px, DPI_PAGE)
        pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(echelle, echelle), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        # IR boxes are in the displayed space, the space of the rendered page.
        x0, y0, x1, y1 = (emu_vers_pt(v) * echelle for v in (bbox.x0, bbox.y0, bbox.x1, bbox.y1))
        cadre = [x0 - CADRE_ROUGE_PX, y0 - CADRE_ROUGE_PX, x1 + CADRE_ROUGE_PX, y1 + CADRE_ROUGE_PX]
        ImageDraw.Draw(image).rectangle(cadre, outline=(255, 0, 0), width=CADRE_ROUGE_PX)
        return image

    def rendre_page(echelle: float) -> Image.Image:
        pixmap = pdf_page.get_pixmap(matrix=pymupdf.Matrix(echelle, echelle), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    return {"rendre": rendre, "rendre_marque": rendre_marque, "rendre_page": rendre_page}


def _identifiant(page_index: int, element_index: int, ligne_index: int | None) -> str:
    base = f"p{page_index}-e{element_index}"
    return base if ligne_index is None else f"{base}-l{ligne_index}"


def identifier(segmentation, source_pdf, *, doclayout="auto", vision="auto", formulenet="auto", identificateurs=(),
               detecteurs=None, model_root=None, progres=None) -> ResultatIdentification:
    """Say what every segmentation box is, and locate the expressions inside the texts.

    The AIs decide, in a cascade where each completes the previous ones: native PDF
    facts, the segmentation's PP-DocLayout zones, PP-DocLayout again at a low threshold
    for what they missed, SmolVLM on visuals still unsettled, PP-FormulaNet on suspected
    formulas. ``doclayout`` / ``vision`` / ``formulenet``: "auto" (when the model is
    present), None, or an identificateur. ``identificateurs``: extra sources plugged in.
    ``progres(fait, total)`` is called after each element is identified.
    """
    if doclayout == "auto":
        doclayout = creer_identificateur_doclayout(model_root)
    if vision == "auto":
        vision = creer_identificateur_vision(model_root)
    if formulenet == "auto":
        formulenet = creer_identificateur_formulenet(model_root)
    registre = registre_par_defaut(doclayout, vision, formulenet, *identificateurs)
    detecteurs = detecteurs if detecteurs is not None else detecteurs_par_defaut(model_root)
    document = segmentation.document
    premiere = min((page.index for page in document.pages), default=0)
    pages = {page.index: page for page in document.pages}
    boites = segmentation.boites()
    decisions: dict[tuple[int, int], Decision] = {}
    with ExitStack() as pile:
        rendu_utile = any(s is not None for s in (doclayout, vision, formulenet))
        pdf = pile.enter_context(pymupdf.open(source_pdf)) if rendu_utile else None
        contextes = {}
        for page in document.pages:
            contexte = contexte_page(page, page.index == premiere)
            if pdf is not None:
                contexte.extra.update(_rendeurs(pdf, page))
            contextes[page.index] = contexte
        cles = list(dict.fromkeys((b.page_index, b.element_index) for b in boites))
        for fait, (page_index, element_index) in enumerate(cles, start=1):
            page = pages[page_index]
            decisions[(page_index, element_index)] = decider_element(page.elements[element_index], page,
                                                                     contextes[page_index], registre)
            if progres is not None:
                progres(fait, len(cles))
    elements = []
    for boite in boites:
        decision = decisions[(boite.page_index, boite.element_index)]
        indices = decision.indices
        if boite.ligne_index is not None:
            indices = (f"ligne de {decision.type}", *indices)
        elements.append(ElementIdentifie(
            _identifiant(boite.page_index, boite.element_index, boite.ligne_index), boite.page_index,
            boite.element_index, boite.ligne_index, _bbox_pt(boite.bbox), decision.type, decision.famille,
            decision.statut, decision.confiance, decision.alternatives, indices))
    expressions = []
    for page in document.pages:
        for element_index, element in enumerate(page.elements):
            if nature(element) != "text":
                continue
            contenu, porteur = texte(element), _identifiant(page.index, element_index, None)
            for rang, trouvaille in enumerate(trouver(element, detecteurs)):
                expressions.append(ExpressionIdentifiee(
                    f"{porteur}-x{rang}", porteur, page.index, element_index, trouvaille.debut, trouvaille.fin,
                    contenu[trouvaille.debut:trouvaille.fin], trouvaille.type, famille(trouvaille.type),
                    trouvaille.confiance, trouvaille.indice))
    return ResultatIdentification(segmentation, tuple(elements), tuple(expressions), registre.noms, detecteurs.noms)


def enregistrer_identification(resultat: ResultatIdentification, source_pdf, destination) -> None:
    """Write the identification catalogue: every field present, null when not established."""
    elements = [asdict(e) for e in resultat.elements]
    for element in elements:
        element["alternatives"] = [list(a) for a in element["alternatives"]]
        element["indices"] = list(element["indices"])
        element["bbox"] = list(element["bbox"])
    data = {
        "schema": SCHEMA,
        "source_pdf": str(source_pdf),
        "granularite": getattr(resultat.segmentation, "granularite", None),
        "referentiel": str(CHEMIN),
        "convention_bbox": "[x, y, largeur, hauteur] en points, origine en haut à gauche",
        "identificateurs": list(resultat.identificateurs),
        "detecteurs_expressions": list(resultat.detecteurs),
        "totaux": {
            "elements": len(elements),
            "par_type": dict(Counter(e.type for e in resultat.elements)),
            "par_famille": dict(Counter(e.famille for e in resultat.elements)),
            "par_statut": dict(Counter(e.statut for e in resultat.elements)),
            "expressions": len(resultat.expressions),
            "expressions_par_type": dict(Counter(x.type for x in resultat.expressions)),
        },
        "elements": elements,
        "expressions": [asdict(x) for x in resultat.expressions],
    }
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
