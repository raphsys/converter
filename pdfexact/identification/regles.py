"""Identificateurs intégrés : zones PaddleX, texte, formules, visuels, formes, objets natifs."""
from __future__ import annotations

import re
from statistics import median

from pdfexact.geometry import BBox, emu_vers_pt
from pdfexact.identification.base import Candidat, ContextePage, Decision, Registre, decider
from pdfexact.identification.formules import est_formule_bloc
from pdfexact.ir import FlowParagraph, ImageEl, LinkZone, RasterEl, ShapeEl, TableEl, TextBox

__all__ = ["Candidat", "contexte_page", "decider", "decider_element", "nature", "registre_par_defaut"]

# An element belongs to a layout zone covering this share of it.
RECOUVREMENT_ZONE = 0.5
# Top and bottom bands of the page (share of its height).
BANDE_HAUTE, BANDE_BASSE = 0.08, 0.92
BANDE_NUMERO = 0.12
# Font size ratios to the page body.
RATIO_INTERTITRE, RATIO_TITRE = 1.25, 1.6
LIGNES_MAX_TITRE = 3
# Geometry, in points.
EPAISSEUR_FILET_PT, LONGUEUR_FILET_PT = 3.0, 10.0
COTE_ICONE_PT = 24.0
COUVERTURE_PAGE = 0.8
COUVERTURE_CADRE = 0.85
RATIO_MONOSPACE = 0.6

LABEL_TEXTE = {
    "doc_title": "titre_document", "paragraph_title": "intertitre", "text": "paragraphe", "abstract": "resume",
    "content": "entree_sommaire", "reference": "entree_bibliographique", "reference_content": "entree_bibliographique",
    "footnote": "note_bas_page", "header": "en_tete", "footer": "pied_de_page", "number": "numero_page",
    "figure_title": "legende", "table_title": "legende", "chart_title": "legende", "aside_text": "note_marginale",
    "algorithm": "bloc_code", "formula": "formule_bloc", "formula_number": "numero_formule", "table": "cellule",
    "image": "etiquette", "chart": "etiquette", "seal": "etiquette",
}
# (type, weight): a generic "image" zone only establishes the family.
LABEL_VISUEL = {
    "image": ("image_generique", 0.6), "figure": ("image_generique", 0.6), "chart": ("graphique", 1.0),
    "seal": ("sceau", 1.0), "table": ("tableau", 0.8), "formula": ("formule_bloc", 1.0), "header": ("logo", 0.5),
}
ROLE_TEXTE = {
    "body": "paragraphe", "title": "titre_document", "heading": "intertitre", "header": "en_tete", "footer": "pied_de_page",
    "caption": "legende", "table-of-contents": "entree_sommaire", "reference": "entree_bibliographique",
    "footnote": "note_bas_page", "page-number": "numero_page", "abstract": "resume", "aside": "note_marginale",
    "algorithm": "bloc_code", "formula-number": "numero_formule", "list": "element_liste",
}
_LEGENDE = re.compile(r"^\s*(fig(ure)?\.?|tab(le|leau)?\.?|graph(ique|e)?|chart|sch[ée]ma|photo|carte|map|plate)\s*[\dIVXivx]",
                      re.IGNORECASE)
_NUMERO_PAGE = re.compile(r"^\s*(page\s*)?(\d{1,4}|[ivxlcdm]{1,6})\s*$", re.IGNORECASE)
_NUMERO_FORMULE = re.compile(r"^\s*\(\s*\d+(?:\.\d+)*[a-z]?\s*\)\s*$")
_MONOSPACE = ("mono", "courier", "consolas", "menlo", "code")


def nature(element) -> str | None:
    if isinstance(element, (TextBox, FlowParagraph)):
        return "text"
    if isinstance(element, (ImageEl, RasterEl)):
        return "image"
    if isinstance(element, ShapeEl):
        return "shape"
    if isinstance(element, TableEl):
        return "table"
    if isinstance(element, LinkZone):
        return "link"
    return None


def texte(element) -> str:
    """Text of a text element, lines joined by a newline (as in the catalogue)."""
    return "\n".join("".join(span.texte for span in ligne.spans) for ligne in getattr(element, "lignes", ()))


def _spans(element):
    return [span for ligne in getattr(element, "lignes", ()) for span in ligne.spans if span.texte.strip()]


def _taille_dominante(element) -> float:
    poids: dict[float, int] = {}
    for span in _spans(element):
        poids[span.size_pt] = poids.get(span.size_pt, 0) + len(span.texte.strip())
    return max(poids, key=poids.get) if poids else 0.0


def _polices(element) -> list[tuple[str, int]]:
    return [(span.police.famille, len(span.texte.strip())) for span in _spans(element)]


def _aire(b: BBox) -> int:
    return max(b.largeur, 0) * max(b.hauteur, 0)


def _intersection(a: BBox, b: BBox) -> int:
    return max(0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(0, min(a.y1, b.y1) - max(a.y0, b.y0))


def _zone(element, page):
    """Layout zone covering most of the element, if it covers enough of it."""
    aire = _aire(element.bbox) or 1
    meilleure = max(getattr(page, "zones_layout", ()) or (), key=lambda z: _intersection(element.bbox, z.bbox), default=None)
    if meilleure is None or _intersection(element.bbox, meilleure.bbox) / aire < RECOUVREMENT_ZONE:
        return None
    return meilleure


def contexte_page(page, premiere_page: bool) -> ContextePage:
    """Page facts shared by the rules: body size, largest size, text and OCR boxes."""
    tailles = [span.size_pt for element in page.elements for span in _spans(element) for _ in span.texte.strip()]
    textes = [e for e in page.elements if nature(e) == "text"]
    return ContextePage(
        page=page, premiere_page=premiere_page,
        corps_pt=median(tailles) if tailles else 0.0,
        taille_max_pt=max((_taille_dominante(e) for e in textes), default=0.0),
        boites_texte=tuple(e.bbox for e in textes),
        boites_ocr=tuple(e.bbox for e in textes if getattr(e, "source_kind", None) == "ocr"),
    )


class ZonesPaddleX:
    nom = "zones-paddlex"
    natures = frozenset({"text", "image", "shape"})

    def candidats(self, element, contexte):
        zone = _zone(element, contexte.page)
        if zone is None:
            return []
        confiance = zone.confidence if zone.confidence is not None else 0.7
        label = str(zone.label).casefold()
        if nature(element) == "text":
            type_ = LABEL_TEXTE.get(label)
            return [Candidat(type_, confiance, f"paddlex:{label}")] if type_ else []
        type_, poids = LABEL_VISUEL.get(label, (None, 0.0))
        return [Candidat(type_, confiance * poids, f"paddlex:{label}")] if type_ else []


class RolesSemantiques:
    """Role set by the segmentation; used only where no layout zone already speaks."""

    nom = "roles-semantiques"
    natures = frozenset({"text"})

    def candidats(self, element, contexte):
        type_ = ROLE_TEXTE.get(getattr(element, "semantic_role", None) or "")
        if type_ is None or _zone(element, contexte.page) is not None:
            return []
        return [Candidat(type_, 0.55, f"role:{element.semantic_role}")]


class ReglesTexte:
    nom = "regles-texte"
    natures = frozenset({"text"})

    def candidats(self, element, contexte):
        page = contexte.page
        contenu = texte(element).strip()
        hauteur = page.hauteur_emu or 1
        haut, bas = element.bbox.y1 / hauteur, element.bbox.y0 / hauteur
        resultat = [Candidat("paragraphe", 0.4, "texte")]
        if getattr(element, "list_marker", None):
            resultat.append(Candidat("element_liste", 0.7, "marqueur de liste"))
        if _LEGENDE.match(contenu):
            resultat.append(Candidat("legende", 0.7, "commence par Figure / Table"))
        if _NUMERO_PAGE.match(contenu) and (haut <= BANDE_NUMERO or bas >= 1 - BANDE_NUMERO):
            resultat.append(Candidat("numero_page", 0.75, "nombre seul en marge haute ou basse"))
        if haut <= BANDE_HAUTE:
            resultat.append(Candidat("en_tete", 0.45, "bande haute de la page"))
        elif bas >= BANDE_BASSE:
            resultat.append(Candidat("pied_de_page", 0.45, "bande basse de la page"))
        taille, corps = _taille_dominante(element), contexte.corps_pt
        lignes = len(getattr(element, "lignes", ()))
        if corps > 0 and taille >= RATIO_INTERTITRE * corps and lignes <= LIGNES_MAX_TITRE:
            if contexte.premiere_page and taille >= RATIO_TITRE * corps and taille >= contexte.taille_max_pt:
                resultat.append(Candidat("titre_document", 0.7, f"plus grand corps de la première page ({taille:g} pt)"))
            else:
                resultat.append(Candidat("intertitre", 0.6, f"corps {taille:g} pt > {corps:g} pt"))
        if len(contenu) == 1 and contenu.isalpha() and corps > 0 and emu_vers_pt(element.bbox.hauteur) >= 2 * corps:
            resultat.append(Candidat("lettrine", 0.75, "lettre seule sur plusieurs lignes"))
        polices = _polices(element)
        total = sum(n for _, n in polices) or 1
        mono = sum(n for nom, n in polices if any(m in nom.casefold() for m in _MONOSPACE))
        if mono / total >= RATIO_MONOSPACE and lignes >= 2:
            resultat.append(Candidat("bloc_code", 0.65, "police à chasse fixe"))
        return resultat


class FormulesBloc:
    nom = "formules-bloc"
    natures = frozenset({"text"})

    def candidats(self, element, contexte):
        contenu = texte(element)
        if _NUMERO_FORMULE.match(contenu):
            return [Candidat("numero_formule", 0.7, "numéro entre parenthèses")]
        if est_formule_bloc(contenu, _polices(element)):
            return [Candidat("formule_bloc", 0.75, "symboles ou polices mathématiques")]
        return []


class ReglesVisuels:
    nom = "regles-visuels"
    natures = frozenset({"image"})

    def candidats(self, element, contexte):
        page, boite = contexte.page, element.bbox
        largeur, hauteur = emu_vers_pt(boite.largeur), emu_vers_pt(boite.hauteur)
        resultat = []
        if boite.largeur >= COUVERTURE_PAGE * page.largeur_emu and boite.hauteur >= COUVERTURE_PAGE * page.hauteur_emu:
            if any(_intersection(boite, b) for b in contexte.boites_ocr):
                resultat.append(Candidat("page_numerisee", 0.8, "image pleine page portant du texte OCR"))
            else:
                resultat.append(Candidat("arriere_plan", 0.7, "image pleine page sans texte"))
        purpose = getattr(element, "purpose", None)
        if purpose == "formula":
            resultat.append(Candidat("formule_bloc", 0.75, "rendue comme formule"))
        elif purpose == "symbol":
            resultat.append(Candidat("icone", 0.5, "rendue comme symbole"))
        elif purpose == "shading":
            resultat.append(Candidat("bandeau", 0.55, "dégradé"))
        if min(largeur, hauteur) <= EPAISSEUR_FILET_PT and max(largeur, hauteur) >= LONGUEUR_FILET_PT:
            resultat.append(Candidat("separateur", 0.6, "image très fine"))
        elif max(largeur, hauteur) <= COTE_ICONE_PT:
            resultat.append(Candidat("icone", 0.45, f"petite image ({max(largeur, hauteur):.0f} pt)"))
        return resultat


class ReglesFormes:
    nom = "regles-formes"
    natures = frozenset({"shape"})

    def candidats(self, element, contexte):
        page, boite = contexte.page, element.bbox
        largeur, hauteur = emu_vers_pt(boite.largeur), emu_vers_pt(boite.hauteur)
        if min(largeur, hauteur) <= EPAISSEUR_FILET_PT and max(largeur, hauteur) >= LONGUEUR_FILET_PT:
            return [Candidat("separateur", 0.8, "trait fin"), Candidat("forme", 0.3, "forme")]
        resultat = []
        if element.remplissage is None and (boite.largeur >= COUVERTURE_CADRE * page.largeur_emu
                                            and boite.hauteur >= COUVERTURE_CADRE * page.hauteur_emu):
            resultat.append(Candidat("bordure_page", 0.8, "contour autour de la page"))
        if element.remplissage is not None:
            sous_texte = any(_intersection(boite, b) >= 0.5 * (_aire(b) or 1) for b in contexte.boites_texte)
            resultat.append(Candidat("bandeau", 0.7 if sous_texte else 0.45,
                                     "aplat sous du texte" if sous_texte else "aplat"))
        resultat.append(Candidat("forme", 0.55 if element.contour else 0.4, "forme vectorielle"))
        return resultat


class ObjetsNatifs:
    nom = "objets-natifs"
    natures = frozenset({"table", "link"})

    def candidats(self, element, contexte):
        if isinstance(element, TableEl):
            return [Candidat("tableau", 0.9, "tableau natif")]
        if element.page_cible is not None or (element.uri or "").startswith("#"):
            return [Candidat("renvoi", 0.9, "lien interne")]
        return [Candidat("lien", 0.9, "lien externe")]


def registre_par_defaut(vision=None) -> Registre:
    """Built-in identificateurs, plus an optional vision identificateur."""
    registre = Registre([ZonesPaddleX(), RolesSemantiques(), ReglesTexte(), FormulesBloc(), ReglesVisuels(),
                         ReglesFormes(), ObjetsNatifs()])
    if vision is not None:
        registre.enregistrer(vision)
    return registre


def decider_element(element, page, contexte: ContextePage, registre: Registre | None = None) -> Decision:
    """Ask every identificateur handling the element's nature, then decide."""
    nat = nature(element)
    registre = registre or registre_par_defaut()
    candidats = [c for identificateur in registre.pour(nat or "") for c in identificateur.candidats(element, contexte)]
    return decider(candidats, repli="image_generique" if nat == "image" else "inconnu")
