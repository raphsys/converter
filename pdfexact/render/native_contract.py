"""Contrat de sortie pour le mode Word natif page-exact.

Le texte et les tableaux restent éditables, mais leur bbox PDF prime sur le flux Word :
les zones de texte ancrées et les tableaux positionnés sont donc autorisés.
"""
import re
import zipfile
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from pdfexact.geometry import BBox, pt_vers_emu, se_chevauchent, union
from pdfexact.ir import Document, FlowParagraph, FontRef, ImageEl, Line, RasterEl, ShapeEl, Span, TableEl, TextBox
from pdfexact.layout.text_comprehension import comprendre_groupe_lignes, comprendre_ligne_texte
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.semantic import (
    calculer_features_continuite,
    detecter_colonnes_textuelles,
    detecter_marqueur_liste,
    est_continuation_de_ligne,
    est_texte_de_corps,
    regrouper_paragraphes,
    text_of,
)
from pdfexact.render.render_plan import RenderPlan, build_document_render_plan


@dataclass(frozen=True)
class DiagnosticWordNative:
    paragraphes: int = 0
    tableaux: int = 0
    images: int = 0
    ancres: int = 0
    ancres_derriere: int = 0
    frames: int = 0
    textboxes: int = 0
    tableaux_positionnes: int = 0
    runs_compresses: int = 0
    element_ids: tuple[str, ...] = ()
    modes: tuple[str, ...] = ()
    losses: tuple[str, ...] = ()
    divergences: tuple[str, ...] = ()

    @property
    def conforme(self) -> bool:
        return self.frames == 0


@dataclass(frozen=True)
class CorrectionWordNative:
    pages_corrigees: int = 0
    textboxes_converties: int = 0
    lignes_converties: int = 0

    @property
    def appliquee(self) -> bool:
        return self.textboxes_converties > 0 or self.lignes_converties > 0


@dataclass(frozen=True)
class NativeContractReport:
    """Verdict structurel sans mutation de l'IR.

    ``corriger_document_word_native`` est conservé pour les appelants historiques,
    mais le pipeline nouveau utilise ce rapport avant l'écriture. Une validation ne
    réécrit donc jamais silencieusement les paragraphes ou les frames.
    """

    planned_element_ids: tuple[str, ...] = ()
    plan_errors: tuple[str, ...] = ()
    missing_bbox: tuple[str, ...] = ()
    unsupported_modes: tuple[str, ...] = ()
    nonrepresentable_sources: tuple[tuple[str, str], ...] = ()

    @property
    def errors(self) -> tuple[str, ...]:
        return (
            self.plan_errors
            + tuple(f"missing-bbox:{element_id}" for element_id in self.missing_bbox)
            + tuple(f"unsupported-mode:{mode}" for mode in self.unsupported_modes)
        )

    @property
    def conforme(self) -> bool:
        return not self.errors


_ESPACEMENT_RUN_RE = re.compile(r'<w:spacing w:val="(-?\d+)"/>')
_ITEM_LISTE_RE = re.compile(r"^\s*(?:\d{1,3}|[A-Za-z])[\.)]\s+\S")
_LEADER_LIGNE_RE = re.compile(
    r".*(?:[-._]\s*){6,}\s*(?:-?\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)


def inspecter_docx_word_native(chemin: str | Path) -> DiagnosticWordNative:
    """Lit document.xml et retourne les compteurs du contrat Word natif."""
    with zipfile.ZipFile(chemin) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")

    espacements = [int(valeur) for valeur in _ESPACEMENT_RUN_RE.findall(xml)]
    return DiagnosticWordNative(
        paragraphes=xml.count("<w:p"),
        tableaux=xml.count("<w:tbl>"),
        images=xml.count("<pic:pic>"),
        ancres=xml.count("<wp:anchor"),
        ancres_derriere=xml.count('behindDoc="1"'),
        frames=xml.count("<w:framePr"),
        textboxes=xml.count("wps:txbx"),
        tableaux_positionnes=xml.count("<w:tblpPr"),
        runs_compresses=sum(1 for valeur in espacements if valeur < 0),
    )


def valider_contrat_word_native(
    document: Document,
    render_plan: RenderPlan | None = None,
) -> NativeContractReport:
    """Valide le plan et ses éléments sans appliquer de correction destructive.

    Le plan fourni est toujours préféré. En son absence, le module central le
    construit sur une copie, sans initialiser ni modifier les objets appelants.
    """
    if render_plan is None:
        document = deepcopy(document)
        plan = build_document_render_plan(document)
    else:
        plan = render_plan
    plan_errors = tuple(plan.validate(document))
    planned = [item for page in plan.pages.values() for item in page]
    missing_bbox = tuple(
        item.element.element_id
        for item in planned
        if getattr(item.element, "bbox", None) is None
    )
    unsupported_modes = tuple(
        f"{item.element.element_id}:{item.decision.mode.value}"
        for item in planned
        if item.decision.mode.value == "unknown"
    )
    return NativeContractReport(
        planned_element_ids=tuple(item.element.element_id for item in planned),
        plan_errors=plan_errors,
        missing_bbox=missing_bbox,
        unsupported_modes=unsupported_modes,
        nonrepresentable_sources=tuple(
            (source_id, coverage.reason)
            for source_id, coverage in sorted((plan.source_coverage or {}).items())
            if coverage.relationship == "non-representable"
        ),
    )


def _texte_ligne(ligne: Line) -> str:
    return text_of(ligne).strip()


def _style_ligne(ligne: Line) -> Span:
    for span in ligne.spans:
        if span.texte.strip():
            return span
    if ligne.spans:
        return ligne.spans[0]
    police = FontRef("ArialMT", "Arial", False, False)
    return Span("", police, 10.0, "000000")


def _paragraphe_depuis_ligne(ligne: Line, largeur_page_emu: int) -> FlowParagraph | None:
    texte = _texte_ligne(ligne)
    if not texte:
        return None
    style = _style_ligne(ligne)
    return FlowParagraph(
        bbox=ligne.bbox,
        texte=texte,
        police=style.police,
        size_pt=style.size_pt,
        couleur=style.couleur,
        alignement=ligne.alignement,
        retrait_gauche_emu=max(0, ligne.bbox.x0),
        retrait_droite_emu=max(0, largeur_page_emu - ligne.bbox.x1),
        retrait_premiere_ligne_emu=0,
        espace_avant_emu=0,
        espace_apres_emu=0,
        interligne_emu=max(ligne.hauteur_ligne_emu, ligne.bbox.hauteur),
        souligne=style.souligne,
        barre=style.barre,
        capitales=style.capitales,
        surlignage=style.surlignage,
        espacement_twips=style.espacement_twips,
        spans=[replace(span) for span in ligne.spans],
        layout_frame_id=ligne.layout_frame_id,
        layout_frame_role=ligne.layout_frame_role,
        layout_frame_strategy=ligne.layout_frame_strategy,
        layout_frame_bbox=ligne.layout_frame_bbox,
        vertical_alignement=_alignement_vertical_groupe([ligne]),
        lignes=[
            replace(
                ligne,
                spans=[replace(span) for span in ligne.spans],
                hauteur_ligne_emu=max(ligne.hauteur_ligne_emu, ligne.bbox.hauteur),
            )
        ],
    )


def _paragraphe_depuis_groupe(lignes: list[Line], largeur_page_emu: int) -> FlowParagraph | None:
    if len(lignes) < 2:
        return None
    textes = [_texte_ligne(ligne) for ligne in lignes]
    texte = " ".join(texte for texte in textes if texte)
    bloc_detecte = _groupe_bloc_detecte(lignes)
    seuil_min = 12 if bloc_detecte else 45
    if len(texte) < seuil_min:
        return None
    autoriser_sans_frame = not any(ligne.layout_frame_id for ligne in lignes)
    if not _groupe_semantiquement_paragraphe(
        lignes,
        autoriser_sans_frame=autoriser_sans_frame,
    ) and not bloc_detecte:
        return None
    bbox = lignes[0].bbox
    for ligne in lignes[1:]:
        bbox = union(bbox, ligne.bbox)
    style = _style_ligne(lignes[0])
    spans: list[Span] = []
    for index, ligne in enumerate(lignes):
        if index:
            reference = spans[-1] if spans else _style_ligne(ligne)
            spans.append(
                Span(
                    "\n",
                    reference.police,
                    reference.size_pt,
                    reference.couleur,
                    espacement_twips=reference.espacement_twips,
                    souligne=reference.souligne,
                    barre=reference.barre,
                    capitales=reference.capitales,
                    exposant=reference.exposant,
                    indice=reference.indice,
                    surlignage=reference.surlignage,
                )
            )
        spans.extend(_copier_spans_ligne(ligne))
    interligne = _interligne_groupe(lignes)
    return FlowParagraph(
        bbox=bbox,
        texte=texte,
        police=style.police,
        size_pt=style.size_pt,
        couleur=style.couleur,
        alignement=_alignement_groupe(lignes),
        retrait_gauche_emu=max(0, bbox.x0),
        retrait_droite_emu=max(0, largeur_page_emu - bbox.x1),
        retrait_premiere_ligne_emu=0,
        espace_avant_emu=0,
        espace_apres_emu=0,
        interligne_emu=interligne,
        souligne=style.souligne,
        barre=style.barre,
        capitales=style.capitales,
        surlignage=style.surlignage,
        espacement_twips=style.espacement_twips,
        spans=spans,
        layout_frame_id=lignes[0].layout_frame_id,
        layout_frame_role=lignes[0].layout_frame_role,
        layout_frame_strategy=lignes[0].layout_frame_strategy,
        layout_frame_bbox=lignes[0].layout_frame_bbox,
        vertical_alignement=_alignement_vertical_groupe(lignes),
        lignes=[
            replace(
                ligne,
                spans=_copier_spans_ligne(ligne),
                hauteur_ligne_emu=max(ligne.hauteur_ligne_emu, ligne.bbox.hauteur),
            )
            for ligne in lignes
        ],
    )


def _copier_spans_ligne(ligne: Line) -> list[Span]:
    return [
        replace(
            span,
            texte=_texte_span_paragraphe(span.texte),
        )
        for span in ligne.spans
    ]


def _texte_span_paragraphe(texte: str) -> str:
    if not texte:
        return texte
    if "\t" in texte or "\n" in texte:
        return texte
    return re.sub(r"[ \u00a0\u2000-\u200a\u202f]+", " ", texte).strip()


def _interligne_groupe(lignes: list[Line]) -> int:
    if len(lignes) < 2:
        return max(lignes[0].hauteur_ligne_emu, lignes[0].bbox.hauteur)
    deltas = [
        max(lignes[index].bbox.y0 - lignes[index - 1].bbox.y0, 0)
        for index in range(1, len(lignes))
    ]
    deltas = sorted(delta for delta in deltas if delta > 0)
    if deltas:
        return max(deltas[len(deltas) // 2], max(ligne.bbox.hauteur for ligne in lignes))
    return max(ligne.hauteur_ligne_emu for ligne in lignes)


def _alignement_groupe(lignes: list[Line]) -> str:
    alignements = [ligne.alignement for ligne in lignes if ligne.alignement]
    if not alignements:
        return "left"
    total = len(alignements)
    if alignements.count("both") >= max(1, total // 2):
        return "both"
    if alignements.count("center") >= max(1, round(total * 0.65)):
        return "center"
    if alignements.count("right") >= max(1, round(total * 0.65)):
        return "right"
    return "left"


def _alignement_vertical_groupe(lignes: list[Line]) -> str:
    if not lignes:
        return "top"
    frame = lignes[0].layout_frame_bbox
    if frame is None:
        return "top"
    bbox = lignes[0].bbox
    for ligne in lignes[1:]:
        bbox = union(bbox, ligne.bbox)
    surplus = frame.hauteur - bbox.hauteur
    if surplus <= pt_vers_emu(4):
        return "top"
    haut = bbox.y0 - frame.y0
    bas = frame.y1 - bbox.y1
    if haut < 0 or bas < 0:
        return "top"
    tolerance = max(pt_vers_emu(3), int(surplus * 0.25))
    if abs(haut - bas) <= tolerance:
        return "center"
    if bas <= max(pt_vers_emu(2), int(haut * 0.45)):
        return "bottom"
    return "top"


def _lignes_textbox(element: TextBox) -> list[Line]:
    return list(element.lignes)


def _zones_visuelles_page(page) -> list[BBox]:
    return [
        element.bbox
        for element in page.elements
        if isinstance(element, (ImageEl, RasterEl, TableEl))
        or (isinstance(element, ShapeEl) and not _forme_fond_de_texte(element))
    ]


def _forme_fond_de_texte(element: ShapeEl) -> bool:
    if not element.remplissage:
        return False
    largeur_pt = element.bbox.largeur / 12700
    hauteur_pt = element.bbox.hauteur / 12700
    return largeur_pt >= 30 and hauteur_pt >= 8 and hauteur_pt <= 80


def _ligne_touche_zone(ligne: Line, zones: list[BBox]) -> bool:
    aire = max(ligne.bbox.largeur * ligne.bbox.hauteur, 1)
    for zone in zones:
        if not se_chevauchent(ligne.bbox, zone):
            continue
        intersection = (
            max(0, min(ligne.bbox.x1, zone.x1) - max(ligne.bbox.x0, zone.x0))
            * max(0, min(ligne.bbox.y1, zone.y1) - max(ligne.bbox.y0, zone.y0))
        )
        if intersection / aire >= 0.20:
            return True
    return False


def _ligne_eligible_paragraphe(
    ligne: Line,
    zones_visuelles: list[BBox],
    *,
    autoriser_sans_frame: bool = False,
) -> bool:
    texte = _texte_ligne(ligne)
    frame_role = ligne.layout_frame_role
    frame_strategy = ligne.layout_frame_strategy
    if autoriser_sans_frame and not ligne.layout_frame_id:
        frame_role = "text-column"
        frame_strategy = "word-text"
    decision = comprendre_ligne_texte(
        texte,
        frame_role=frame_role,
        frame_strategy=frame_strategy,
    )
    if decision.action != "candidate-paragraph-line":
        return False
    if not ligne.layout_frame_id and not autoriser_sans_frame:
        return False
    if len(texte) < 12:
        return False
    if _LEADER_LIGNE_RE.match(texte):
        return False
    if ligne.bbox.largeur < pt_vers_emu(85):
        return False
    if _ligne_touche_zone(ligne, zones_visuelles):
        return False
    style = _style_ligne(ligne)
    if style.size_pt >= 20:
        return False
    mots = texte.split()
    if len(mots) <= 3:
        return False
    lettres = [car for car in texte if car.isalpha()]
    if lettres and sum(1 for car in lettres if car.isupper()) / len(lettres) > 0.82:
        return False
    return True


def _ligne_dans_frame_texte_fiable(ligne: Line) -> bool:
    return (
        bool(ligne.layout_frame_id)
        and ligne.layout_frame_strategy == "word-text"
        and ligne.layout_frame_role in {"text-column", "caption", "heading", "list"}
    )


def _texte_ligne_semantique(texte: str) -> bool:
    return est_texte_de_corps(texte)


def _groupe_semantiquement_paragraphe(
    lignes: list[Line],
    *,
    autoriser_sans_frame: bool = False,
) -> bool:
    if not lignes:
        return False
    options = AnalysisOptions(
        extra={"semantic_ignore_frame_id": autoriser_sans_frame}
    )
    groups = regrouper_paragraphes(lignes, options)
    return len([group for group in groups if any(_texte_ligne(item) for item in group)]) == 1


def _memes_styles(a: Line, b: Line) -> bool:
    from pdfexact.analysis.semantic import styles_compatibles

    return styles_compatibles(a, b)


def _meme_paragraphe(
    precedente: Line,
    courante: Line,
    *,
    ignorer_frame_id: bool = False,
) -> bool:
    return est_continuation_de_ligne(
        precedente,
        courante,
        AnalysisOptions(extra={"semantic_ignore_frame_id": ignorer_frame_id}),
    )


def _commence_item_liste(ligne: Line) -> bool:
    return detecter_marqueur_liste(ligne) is not None


def _groupe_bloc_detecte(lignes: list[Line], *, ignorer_frame_id: bool = False) -> bool:
    if len(lignes) < 2:
        return False
    if len(lignes) > 4:
        return False
    frame_ids = {ligne.layout_frame_id for ligne in lignes}
    if not ignorer_frame_id and (len(frame_ids) != 1 or None in frame_ids):
        return False
    if any(ligne.layout_frame_strategy and ligne.layout_frame_strategy != "word-text" for ligne in lignes):
        return False
    if any(ligne.layout_frame_role not in {"text-column", "caption", "heading", "list"} for ligne in lignes):
        return False
    if any(_style_ligne(ligne).size_pt >= 20 for ligne in lignes):
        return False
    ordonnees = sorted(lignes, key=lambda ligne: (ligne.bbox.y0, ligne.bbox.x0))
    if any(_LEADER_LIGNE_RE.match(_texte_ligne(ligne)) for ligne in ordonnees):
        return False
    bbox_groupe = ordonnees[0].bbox
    for ligne in ordonnees[1:]:
        bbox_groupe = union(bbox_groupe, ligne.bbox)
    frame = ordonnees[0].layout_frame_bbox
    if (
        ordonnees[0].layout_frame_role == "text-column"
        and frame is not None
        and frame.hauteur > pt_vers_emu(90)
        and bbox_groupe.hauteur > pt_vers_emu(70)
    ):
        return False
    if any(not _memes_styles(a, b) for a, b in zip(ordonnees, ordonnees[1:])):
        return False
    for precedente, courante in zip(ordonnees, ordonnees[1:]):
        if _commence_item_liste(courante):
            return False
        hauteur = max(precedente.bbox.hauteur, courante.bbox.hauteur, pt_vers_emu(6))
        gap = courante.bbox.y0 - precedente.bbox.y1
        if gap < -hauteur * 0.30 or gap > hauteur * 1.75:
            return False
        fin = _texte_ligne(precedente)[-1:]
        if fin in {".", "!", "?", ":"} and gap > hauteur * 0.55:
            return False
        chevauchement_x = max(0, min(precedente.bbox.x1, courante.bbox.x1) - max(precedente.bbox.x0, courante.bbox.x0))
        ratio_x = chevauchement_x / max(min(precedente.bbox.largeur, courante.bbox.largeur), 1)
        retrait = abs(precedente.bbox.x0 - courante.bbox.x0) <= pt_vers_emu(34)
        if ratio_x < 0.35 and not retrait:
            return False
    return True


def _colonnes_lignes_sans_frame(items: list[tuple[int, TextBox, Line]]) -> list[list[tuple[int, TextBox, Line]]]:
    by_line = {id(item[2]): item for item in items}
    columns = detecter_colonnes_textuelles([item[2] for item in items], AnalysisOptions())
    return [
        [by_line[id(line)] for line in column if id(line) in by_line]
        for column in columns
    ]


def _groupes_paragraphes_sans_frame(
    items: list[tuple[int, TextBox, Line]],
    zones_visuelles: list[BBox],
) -> list[list[tuple[int, TextBox, Line]]]:
    groupes: list[list[tuple[int, TextBox, Line]]] = []
    for colonne in _colonnes_lignes_sans_frame(items):
        courant: list[tuple[int, TextBox, Line]] = []
        for item in colonne:
            ligne = item[2]
            if not _ligne_eligible_paragraphe(ligne, zones_visuelles, autoriser_sans_frame=True):
                if courant:
                    groupes.append(courant)
                    courant = []
                groupes.append([item])
                continue
            if courant and _meme_paragraphe(courant[-1][2], ligne):
                courant.append(item)
            else:
                if courant:
                    groupes.append(courant)
                courant = [item]
        if courant:
            groupes.append(courant)
    return groupes


def _groupes_paragraphes_frame(
    items: list[tuple[int, TextBox, Line]],
    zones_visuelles: list[BBox],
) -> list[list[tuple[int, TextBox, Line]]]:
    groupes: list[list[tuple[int, TextBox, Line]]] = []
    courant: list[tuple[int, TextBox, Line]] = []
    for item in items:
        ligne = item[2]
        if _ligne_touche_zone(ligne, zones_visuelles) and not _ligne_dans_frame_texte_fiable(ligne):
            if courant:
                groupes.append(courant)
                courant = []
            groupes.append([item])
            continue
        if not courant:
            courant = [item]
            continue
        lignes_candidat = [element[2] for element in courant] + [ligne]
        precedente = courant[-1][2]
        if _groupe_bloc_detecte(lignes_candidat) or (
            _ligne_eligible_paragraphe(precedente, zones_visuelles)
            and _ligne_eligible_paragraphe(ligne, zones_visuelles)
            and _meme_paragraphe(precedente, ligne)
        ):
            courant.append(item)
            continue
        groupes.append(courant)
        courant = [item]
    if courant:
        groupes.append(courant)
    return groupes


def _groupes_paragraphes_frame_par_colonne(
    items: list[tuple[int, TextBox, Line]],
    zones_visuelles: list[BBox],
) -> list[list[tuple[int, TextBox, Line]]]:
    groupes: list[list[tuple[int, TextBox, Line]]] = []
    for colonne in _colonnes_lignes_sans_frame(items):
        courant: list[tuple[int, TextBox, Line]] = []
        for item in sorted(colonne, key=lambda valeur: (valeur[2].bbox.y0, valeur[2].bbox.x0, valeur[2].bbox.x1)):
            ligne = item[2]
            if _ligne_touche_zone(ligne, zones_visuelles) and not _ligne_dans_frame_texte_fiable(ligne):
                if courant:
                    groupes.append(courant)
                    courant = []
                groupes.append([item])
                continue
            if not courant:
                courant = [item]
                continue
            lignes_candidat = [element[2] for element in courant] + [ligne]
            precedente = courant[-1][2]
            if _groupe_bloc_detecte(lignes_candidat, ignorer_frame_id=True) or (
                _ligne_eligible_paragraphe(precedente, zones_visuelles)
                and _ligne_eligible_paragraphe(ligne, zones_visuelles)
                and _meme_paragraphe(precedente, ligne, ignorer_frame_id=True)
            ):
                courant.append(item)
                continue
            groupes.append(courant)
            courant = [item]
        if courant:
            groupes.append(courant)
    return groupes


def _continuite_semantique(precedente: Line, courante: Line) -> bool:
    return est_continuation_de_ligne(precedente, courante, AnalysisOptions())


def _assembler_textboxes_page(page) -> tuple[list, int, int]:
    zones_visuelles = _zones_visuelles_page(page)
    lignes: list[tuple[int, TextBox, Line]] = []
    autres = []
    for index, element in enumerate(page.elements):
        if not isinstance(element, TextBox):
            autres.append((index, element))
            continue
        if getattr(element, "preserve_as_textbox", False):
            autres.append((index, element))
            continue
        for ligne in _lignes_textbox(element):
            lignes.append((index, element, ligne))

    if not lignes:
        return page.elements, 0, 0

    groupes: list[list[tuple[int, TextBox, Line]]] = []
    avec_frame: list[tuple[int, TextBox, Line]] = []
    sans_frame: list[tuple[int, TextBox, Line]] = []
    for item in lignes:
        frame_id = item[2].layout_frame_id
        if not frame_id:
            sans_frame.append(item)
        else:
            avec_frame.append(item)

    groupes.extend(_groupes_paragraphes_sans_frame(sans_frame, zones_visuelles))
    groupes.extend(_groupes_paragraphes_frame_par_colonne(avec_frame, zones_visuelles))

    textes_convertis: set[int] = set()
    remplacements: list[tuple[int, object]] = []
    textboxes_converties = 0
    lignes_converties = 0
    for groupe in groupes:
        lignes_groupe = [item[2] for item in groupe]
        paragraphe = _paragraphe_depuis_groupe(lignes_groupe, page.largeur_emu)
        if paragraphe is None:
            lignes_par_element: dict[int, tuple[int, TextBox, list[Line]]] = {}
            for index, element, ligne in groupe:
                entree = lignes_par_element.get(id(element))
                if entree is None:
                    lignes_par_element[id(element)] = (index, element, [ligne])
                else:
                    index_initial, element_initial, lignes = entree
                    lignes.append(ligne)
                    lignes_par_element[id(element)] = (index_initial, element_initial, lignes)
            for index, element, lignes_element in lignes_par_element.values():
                textbox = _textbox_depuis_lignes(element, lignes_element)
                if textbox is not None:
                    remplacements.append((index, textbox))
            continue
        index_min = min(item[0] for item in groupe)
        remplacements.append((index_min, paragraphe))
        for _index, element, _ligne in groupe:
            textes_convertis.add(id(element))
        textboxes_converties += len({id(item[1]) for item in groupe})
        lignes_converties += len(lignes_groupe)

    for index, element in autres:
        remplacements.append((index, element))
    remplacements.sort(key=lambda item: (item[0], 0 if not isinstance(item[1], FlowParagraph) else 1))
    nouveaux = [element for _index, element in remplacements]
    return nouveaux, textboxes_converties, lignes_converties


def _textbox_depuis_lignes(element: TextBox, lignes: list[Line]) -> TextBox | None:
    if not lignes:
        return None
    bbox = lignes[0].bbox
    for ligne in lignes[1:]:
        bbox = union(bbox, ligne.bbox)
    return TextBox(
        bbox=bbox,
        lignes=lignes,
        layout_frame_id=element.layout_frame_id,
        layout_frame_role=element.layout_frame_role,
        layout_frame_strategy=element.layout_frame_strategy,
        layout_frame_bbox=element.layout_frame_bbox,
    )


def corriger_document_word_native(document: Document) -> CorrectionWordNative:
    """Assemble uniquement les lignes qui ressemblent à de vrais paragraphes.

    Le mode word-native commence par des lignes positionnées. Cette étape ne fusionne
    que le texte courant ; les labels, schémas, captions et textes de cadres restent
    ancrés ligne par ligne.
    """
    pages_corrigees = 0
    textboxes_converties = 0
    lignes_converties = 0

    for page in document.pages:
        nouveaux, converties, lignes = _assembler_textboxes_page(page)
        if converties or lignes:
            page.elements = nouveaux
            pages_corrigees += 1
            textboxes_converties += converties
            lignes_converties += lignes

    return CorrectionWordNative(
        pages_corrigees=pages_corrigees,
        textboxes_converties=textboxes_converties,
        lignes_converties=lignes_converties,
    )
