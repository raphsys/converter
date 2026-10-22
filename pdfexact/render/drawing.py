"""Fragments DrawingML.

Chaque élément de page est une forme flottante ancrée en position absolue par rapport à
la page. Marges internes nulles, habillage désactivé, aucun ajustement automatique : rien
ne doit pouvoir décaler quoi que ce soit.
"""
import re
from dataclasses import replace
from xml.sax.saxutils import escape

from pdfexact.geometry import BBox, emu_vers_pt, pt_vers_emu, pt_vers_twips, quantifier_bbox, quantifier_coord
from pdfexact.ir import FlowParagraph, Line, Span
from pdfexact.layout.paragraph_planner import lignes_du_bloc, planifier_paragraphe

_LEADER_RE = re.compile(
    r"^(?P<label>.+?)\s*(?P<leader>(?:[-._]\s*){6,})\s*(?P<page>-?\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)

_GABARIT_ANCRE = (
    '<w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
    'relativeHeight="{z}" behindDoc="{derriere}" locked="0" layoutInCell="0" '
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
    bbox = quantifier_bbox(bbox)
    return _GABARIT_ANCRE.format(
        z=z,
        derriere=1 if derriere else 0,
        x=max(bbox.x0, 0),
        y=max(bbox.y0, 0),
        largeur=max(bbox.largeur, 1),
        hauteur=max(bbox.hauteur, 1),
        identifiant=identifiant,
        nom=nom,
        contenu=contenu,
    )


def _bbox_ligne_word(ligne: Line, largeur_page_emu: int | None = None) -> BBox:
    """Garde l'origine PDF, mais evite une zone trop basse pour Word/LibreOffice."""
    taille = max((span.size_pt for span in ligne.spans if span.texte), default=0.0)
    hauteur_typo = pt_vers_emu(max(taille * (4 / 3), 1.0))
    hauteur = max(ligne.bbox.hauteur, ligne.hauteur_ligne_emu, hauteur_typo)
    y0 = ligne.bbox.y0
    if taille >= 24:
        y0 = max(0, y0 - pt_vers_emu(taille * 0.12))
    x1 = ligne.bbox.x1
    texte = "".join(span.texte for span in ligne.spans)
    if largeur_page_emu and _LEADER_RE.match(texte.strip()) and ligne.bbox.largeur < pt_vers_emu(360):
        marge_droite = max(ligne.bbox.x0, int(largeur_page_emu * 0.0833))
        x1 = max(x1, min(largeur_page_emu, largeur_page_emu - marge_droite))
    return quantifier_bbox(BBox(ligne.bbox.x0, y0, x1, y0 + hauteur))


def _run_xml(
    span,
    relations=None,
    *,
    autoriser_espacement_negatif: bool = False,
    largeur_pct: int = 100,
) -> str:
    """Un run avec sa police, son corps, sa couleur et sa correction d'espacement."""
    famille = escape(span.police.famille)
    proprietes = [
        f'<w:rFonts w:ascii="{famille}" w:hAnsi="{famille}" w:cs="{famille}"/>'
    ]
    if span.police.famille == "TeX Gyre Heros Cn":
        proprietes.append('<w:w w:val="75"/>')
    if span.police.gras:
        proprietes.append("<w:b/>")
    if span.police.italique:
        proprietes.append("<w:i/>")
    if getattr(span, "souligne", False):
        proprietes.append('<w:u w:val="single"/>')
    if getattr(span, "barre", False):
        proprietes.append("<w:strike/>")
    if getattr(span, "capitales", False):
        proprietes.append("<w:caps/>")
    if getattr(span, "exposant", False):
        proprietes.append('<w:vertAlign w:val="superscript"/>')
    elif getattr(span, "indice", False):
        proprietes.append('<w:vertAlign w:val="subscript"/>')
    if getattr(span, "invisible", False):
        proprietes.append("<w:vanish/>")
    proprietes.append(f'<w:color w:val="{span.couleur}"/>')
    if getattr(span, "surlignage", None):
        proprietes.append(f'<w:highlight w:val="{span.surlignage}"/>')
    demi_points = max(round(span.size_pt * 2), 1)
    proprietes.append(f'<w:sz w:val="{demi_points}"/>')
    proprietes.append(f'<w:szCs w:val="{demi_points}"/>')
    if largeur_pct != 100:
        # Horizontal scale keeps a substituted row at its source width, both
        # when the substitute face is wider and when it is narrower.
        proprietes.append(f'<w:w w:val="{max(50, min(200, int(largeur_pct)))}"/>')
    if span.espacement_twips and (span.espacement_twips > 0 or autoriser_espacement_negatif):
        proprietes.append(f'<w:spacing w:val="{span.espacement_twips}"/>')

    fragments = []
    lignes = str(span.texte).split("\n") or [""]
    for index, texte in enumerate(lignes):
        if index:
            fragments.append("<w:br/>")
        morceaux = texte.split("\t")
        for tab_index, morceau in enumerate(morceaux):
            if tab_index:
                fragments.append("<w:tab/>")
            if morceau:
                fragments.append(f'<w:t xml:space="preserve">{escape(morceau)}</w:t>')

    run = f'<w:r><w:rPr>{"".join(proprietes)}</w:rPr>{"".join(fragments)}</w:r>'

    if span.lien and relations is not None:
        rel_id = relations.ajouter(span.lien, "hyperlink", externe=True)
        return f'<w:hyperlink r:id="{rel_id}">{run}</w:hyperlink>'
    return run


def _runs_paragraphe(paragraphe: FlowParagraph, relations=None, polices=None) -> str:
    """Construit un seul flux de runs avec les jonctions decidees semantiquement."""
    lignes = list(lignes_du_bloc(paragraphe))
    if not lignes:
        return ""
    plan = planifier_paragraphe(paragraphe, polices=polices)
    morceaux: list[str] = []
    texte_precedent = ""
    for index, ligne in enumerate(lignes):
        spans = [span for span in ligne.spans if span.texte]
        if not spans:
            continue
        if index:
            action = plan.action_between(index - 1)
            courant = "".join(span.texte for span in spans)
            precedent = texte_precedent
            if action == "hyphen_join" and morceaux:
                morceaux[-1] = re.sub(r"(?:-|¬)(</w:t></w:r>)$", r"\1", morceaux[-1])
            elif action == "preserve_break":
                morceaux.append('<w:r><w:br/></w:r>')
            elif action == "paragraph_break":
                morceaux.append('<w:r><w:br/><w:br/></w:r>')
            elif (action != "no_space" and precedent and courant and not precedent[-1].isspace()
                  and not courant[0].isspace() and courant[0] not in ".,;:!?)]}%"):
                morceaux.append('<w:r><w:t xml:space="preserve"> </w:t></w:r>')
            if action in {"preserve_break", "paragraph_break"} and (
                ligne.bbox.x0 - paragraphe.bbox.x0 > pt_vers_emu(3)
            ):
                morceaux.append("<w:r><w:tab/></w:r>")
        if index == 0 and ligne.bbox.x0 - paragraphe.bbox.x0 > pt_vers_emu(3):
            morceaux.append("<w:r><w:tab/></w:r>")
        morceaux.extend(
            _run_xml(
                replace(
                    span,
                    espacement_twips=(
                        0
                        if (
                            index < len(plan.line_width_scale_percent)
                            and plan.line_width_scale_percent[index] < 100
                        )
                        else int(span.espacement_twips or 0)
                        + (
                            plan.line_spacing_twips[index]
                            if index < len(plan.line_spacing_twips)
                            else 0
                        )
                    ),
                ),
                relations,
                autoriser_espacement_negatif=True,
                largeur_pct=(
                    plan.line_width_scale_percent[index]
                    if index < len(plan.line_width_scale_percent)
                    else 100
                ),
            )
            for span in spans
            if span.texte
        )
        texte_precedent = "".join(span.texte for span in spans)
    return "".join(morceaux)


def _couleur_sombre(couleur: str | None) -> bool:
    if not couleur:
        return False
    hexa = couleur.strip().lstrip("#")
    if len(hexa) != 6:
        return False
    try:
        r = int(hexa[0:2], 16)
        g = int(hexa[2:4], 16)
        b = int(hexa[4:6], 16)
    except ValueError:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) < 96


def _rotation_ooxml(element) -> int:
    """Convertit l'angle IR en unites DrawingML, sans tourner le flux ordinaire."""
    angle = float(getattr(element, "angle_deg", 0.0) or 0.0)
    if abs(angle) <= 7.0:
        return 0
    return round(-angle * 60000)


def _copier_span(span, **changements):
    valeurs = {
        "texte": span.texte,
        "police": span.police,
        "size_pt": span.size_pt,
        "couleur": span.couleur,
        "espacement_twips": span.espacement_twips,
        "lien": span.lien,
        "invisible": span.invisible,
        "souligne": span.souligne,
        "barre": span.barre,
        "capitales": span.capitales,
        "exposant": span.exposant,
        "indice": span.indice,
        "surlignage": span.surlignage,
        "bbox": span.bbox,
    }
    valeurs.update(changements)
    return type(span)(**valeurs)


def _runs_ligne_avec_leader(
    ligne: Line,
    relations=None,
    *,
    autoriser_espacement_negatif: bool = False,
    largeur_ligne_emu: int | None = None,
) -> tuple[str, str] | None:
    texte = "".join(span.texte for span in ligne.spans)
    correspondance = _LEADER_RE.match(texte.strip())
    if correspondance is None or not ligne.spans:
        return None

    span_base = ligne.spans[0]
    leader_texte = correspondance.group("leader")
    leader = "dot" if "." in leader_texte else "underscore" if "_" in leader_texte else "hyphen"
    largeur = largeur_ligne_emu or ligne.bbox.largeur
    tab_pos = pt_vers_twips(max(emu_vers_pt(largeur) - 1.0, 1.0))
    label = _copier_span(
        span_base,
        texte=correspondance.group("label").rstrip(),
        espacement_twips=0,
    )
    page = _copier_span(
        span_base,
        texte=correspondance.group("page"),
        espacement_twips=0,
    )
    runs = (
        f"{_run_xml(label, relations, autoriser_espacement_negatif=autoriser_espacement_negatif)}"
        "<w:r><w:tab/></w:r>"
        f"{_run_xml(page, relations, autoriser_espacement_negatif=autoriser_espacement_negatif)}"
    )
    tabs = (
        "<w:tabs>"
        f'<w:tab w:val="right" w:leader="{leader}" w:pos="{tab_pos}"/>'
        "</w:tabs>"
    )
    return runs, tabs


def _largeur_texte_pt(texte: str, span: Span, polices: dict | None) -> float:
    if polices:
        try:
            from pdfexact.extract.fonts import mesurer_largeur_pt
        except Exception:  # noqa: BLE001
            mesurer_largeur_pt = None
        asset = polices.get(span.police.font_id) if mesurer_largeur_pt else None
        if asset is not None:
            try:
                return mesurer_largeur_pt(texte, asset, span.size_pt)
            except Exception:  # noqa: BLE001
                pass
    return len(texte) * max(float(span.size_pt), 1.0) * (0.54 if span.police.gras else 0.50)


def _ligne_leader_visuelle_xml(
    ligne: Line,
    identifiant: int,
    z: int,
    relations=None,
    largeur_page_emu: int | None = None,
    polices: dict | None = None,
) -> str | None:
    texte = "".join(span.texte for span in ligne.spans)
    correspondance = _LEADER_RE.match(texte.strip())
    if correspondance is None or not ligne.spans:
        return None
    leader_texte = correspondance.group("leader")
    if not re.search(r"(?:\.\s*){6,}", leader_texte):
        return None

    bbox_ancre = _bbox_ligne_word(ligne, largeur_page_emu)
    span_base = ligne.spans[0]
    label_texte = correspondance.group("label").rstrip()
    page_texte = correspondance.group("page")
    hauteur = bbox_ancre.hauteur
    marge = pt_vers_emu(1.0)

    page_w = pt_vers_emu(max(_largeur_texte_pt(page_texte, span_base, polices) + 2.0, 8.0))
    page_x0 = max(bbox_ancre.x0 + marge, bbox_ancre.x1 - page_w)
    label_w_mesuree = pt_vers_emu(_largeur_texte_pt(label_texte, span_base, polices) + 1.5)
    label_w = min(label_w_mesuree, max(page_x0 - bbox_ancre.x0 - 2 * marge, marge))
    label_bbox = BBox(bbox_ancre.x0, bbox_ancre.y0, bbox_ancre.x0 + label_w, bbox_ancre.y1)
    page_bbox = BBox(page_x0, bbox_ancre.y0, bbox_ancre.x1, bbox_ancre.y1)

    leader_x0 = min(label_bbox.x1 + marge, page_x0)
    leader_x1 = max(leader_x0 + 1, page_x0 - marge)
    leader_bbox = BBox(leader_x0, bbox_ancre.y0, leader_x1, bbox_ancre.y1)
    pas_pt = max(_largeur_texte_pt(". ", span_base, polices), 3.2)
    repetitions = max(1, int(emu_vers_pt(leader_bbox.largeur) / pas_pt) + 2)
    leader_visuel = (". " * repetitions).rstrip()

    label = _copier_span(span_base, texte=label_texte, espacement_twips=0)
    leader = _copier_span(span_base, texte=leader_visuel, espacement_twips=0)
    page = _copier_span(span_base, texte=page_texte, espacement_twips=0)

    return (
        _zone_texte_simple_xml(label_bbox, label, identifiant, z, relations, alignement="left")
        + _zone_texte_simple_xml(leader_bbox, leader, identifiant + 100000, z + 1, relations, alignement="left")
        + _zone_texte_simple_xml(page_bbox, page, identifiant + 200000, z + 2, relations, alignement="right")
    )


def _zone_texte_simple_xml(
    bbox_ancre: BBox,
    span: Span,
    identifiant: int,
    z: int,
    relations=None,
    *,
    alignement: str = "left",
) -> str:
    interligne = max(pt_vers_twips(emu_vers_pt(bbox_ancre.hauteur)), 1)
    paragraphe = (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="0" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        '<w:ind w:left="0" w:right="0" w:firstLine="0"/>'
        f'<w:jc w:val="{alignement}"/>'
        "</w:pPr>"
        f"{_run_xml(span, relations)}</w:p>"
    )
    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/>'
        "<wps:spPr>"
        '<a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{max(bbox_ancre.largeur, 1)}" cy="{max(bbox_ancre.hauteur, 1)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        f"<wps:txbx><w:txbxContent>{paragraphe}</w:txbxContent></wps:txbx>"
        '<wps:bodyPr rot="0" spcFirstLastPara="0" vertOverflow="clip" '
        'horzOverflow="clip" vert="horz" wrap="none" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )
    return _ancre(bbox_ancre, identifiant, z, f"Ligne {identifiant}", contenu)


def zone_texte_xml(
    ligne: Line,
    identifiant: int,
    z: int,
    relations=None,
    largeur_page_emu: int | None = None,
    polices: dict | None = None,
) -> str:
    """Rend une ligne de texte comme forme flottante contenant une zone de texte.

    Une zone par ligne, et non par bloc : dès qu'une zone contient plusieurs lignes, c'est
    Word qui calcule les retours à la ligne et l'interligne, avec ses propres métriques.
    L'écart s'accumule et le bas du bloc dérive. Une ligne par zone supprime ce calcul.

    `lineRule="exact"` fixe la hauteur de ligne : sans lui, Word applique son interligne
    et tout le contenu descend.
    """
    ligne_leader_visuelle = _ligne_leader_visuelle_xml(
        ligne,
        identifiant,
        z,
        relations,
        largeur_page_emu,
        polices,
    )
    if ligne_leader_visuelle is not None:
        return ligne_leader_visuelle

    bbox_ancre = _bbox_ligne_word(ligne, largeur_page_emu)
    interligne = max(pt_vers_twips(emu_vers_pt(bbox_ancre.hauteur)), 1)
    ligne_leader = _runs_ligne_avec_leader(
        ligne,
        relations,
        autoriser_espacement_negatif=True,
        largeur_ligne_emu=bbox_ancre.largeur,
    )
    if ligne_leader is None:
        runs = "".join(
            _run_xml(span, relations, autoriser_espacement_negatif=True)
            for span in ligne.spans
        )
        tabs = ""
    else:
        runs, tabs = ligne_leader
    alignement = getattr(ligne, "alignement", "left") or "left"
    gauche = max(pt_vers_twips(emu_vers_pt(getattr(ligne, "retrait_gauche_emu", 0))), 0)
    premiere = pt_vers_twips(emu_vers_pt(getattr(ligne, "retrait_premiere_ligne_emu", 0)))
    if ligne_leader is None and premiere < 0:
        tabs = f'<w:tabs><w:tab w:val="left" w:pos="{gauche}"/></w:tabs>'

    paragraphe = (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="0" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        f"{tabs}"
        f'<w:ind w:left="{gauche}" w:right="0" w:firstLine="{premiere}"/>'
        f'<w:jc w:val="{"left" if ligne_leader is not None else alignement}"/>'
        "</w:pPr>"
        f"{runs}</w:p>"
    )

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/>'
        "<wps:spPr>"
        '<a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{max(bbox_ancre.largeur, 1)}" cy="{max(bbox_ancre.hauteur, 1)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        f"<wps:txbx><w:txbxContent>{paragraphe}</w:txbxContent></wps:txbx>"
        f'<wps:bodyPr rot="{_rotation_ooxml(ligne)}" spcFirstLastPara="0" vertOverflow="overflow" '
        'horzOverflow="clip" vert="horz" wrap="none" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(bbox_ancre, identifiant, z, f"Ligne {identifiant}", contenu)


def _interligne_paragraphe(paragraphe: FlowParagraph) -> int:
    taille = max(
        [paragraphe.size_pt, *(span.size_pt for span in paragraphe.spans if span.texte.strip())],
        default=paragraphe.size_pt,
    )
    minimum = pt_vers_emu(max(taille * (1.12 if len(paragraphe.lignes) >= 2 else 1.0), 1.0))
    if len(paragraphe.lignes) >= 2:
        lignes = sorted(paragraphe.lignes, key=lambda item: item.bbox.y0)
        deltas = [
            max(0, courant.bbox.y0 - precedent.bbox.y0)
            for precedent, courant in zip(lignes, lignes[1:])
        ]
        deltas = sorted(delta for delta in deltas if delta > 0)
        if deltas:
            # Un paragraphe OCR peut contenir un saut visuel entre deux styles
            # (titre puis metadonnees). Le plus grand delta ne doit pas devenir
            # l'interligne de toutes les lignes.
            return max(minimum, deltas[0], paragraphe.interligne_emu)
    return max(minimum, paragraphe.interligne_emu, paragraphe.bbox.hauteur)


def _nombre_lignes_paragraphe(paragraphe: FlowParagraph) -> int:
    if paragraphe.lignes:
        return max(1, len(paragraphe.lignes))
    if paragraphe.spans:
        return max(1, sum(str(span.texte).count("\n") for span in paragraphe.spans) + 1)
    return max(1, str(paragraphe.texte).count("\n") + 1)


def _bbox_paragraphe_word(paragraphe: FlowParagraph) -> BBox:
    interligne = _interligne_paragraphe(paragraphe)
    lignes = _nombre_lignes_paragraphe(paragraphe)
    hauteur_typo = interligne * lignes
    hauteur = max(paragraphe.bbox.hauteur, hauteur_typo)
    return quantifier_bbox(BBox(paragraphe.bbox.x0, paragraphe.bbox.y0, paragraphe.bbox.x1, paragraphe.bbox.y0 + hauteur))


def zone_paragraphe_xml(
    paragraphe: FlowParagraph,
    identifiant: int,
    z: int,
    relations=None,
    *,
    natif: bool = False,
    espacement_avant_emu: int = 0,
    flux_origine_x_emu: int | None = None,
    flux_largeur_emu: int | None = None,
    echelle_verticale: float = 1.0,
    echelle_police: float = 1.0,
    polices: dict | None = None,
) -> str:
    """Rend un paragraphe Word editable ancre a sa bbox PDF."""
    bbox_ancre = _bbox_paragraphe_word(paragraphe)
    interligne = max(
        pt_vers_twips(emu_vers_pt(_interligne_paragraphe(paragraphe) * echelle_verticale)),
        1,
    )
    spans = paragraphe.spans or [
        Span(
            paragraphe.texte,
            paragraphe.police,
            paragraphe.size_pt,
            paragraphe.couleur,
            espacement_twips=paragraphe.espacement_twips,
            souligne=paragraphe.souligne,
            barre=paragraphe.barre,
            capitales=paragraphe.capitales,
            surlignage=paragraphe.surlignage,
        )
    ]
    if echelle_police != 1.0:
        spans = [
            replace(span, size_pt=max(4.0, round(span.size_pt * echelle_police, 2)))
            for span in spans
        ]
    runs = _runs_paragraphe(paragraphe, relations, polices=polices) or "".join(
        _run_xml(span, relations, autoriser_espacement_negatif=True) for span in spans
    )
    alignement = getattr(paragraphe, "alignement", "left") or "left"
    if natif and len(paragraphe.lignes) <= 1 and alignement == "both":
        alignement = "left"
    gauche_emu = max(0, paragraphe.retrait_gauche_emu - paragraphe.bbox.x0)
    gauche = max(pt_vers_twips(emu_vers_pt(gauche_emu)), 0)
    premiere = pt_vers_twips(emu_vers_pt(paragraphe.retrait_premiere_ligne_emu))
    tab_stops = []
    for ligne in paragraphe.lignes:
        decalage = ligne.bbox.x0 - paragraphe.bbox.x0
        if decalage > pt_vers_emu(3):
            tab_stops.append(
                f'<w:tab w:val="left" w:pos="{pt_vers_twips(emu_vers_pt(decalage))}"/>'
            )
    if premiere < 0:
        tab_stops.append(f'<w:tab w:val="left" w:pos="{gauche}"/>')
    tabs = f"<w:tabs>{''.join(dict.fromkeys(tab_stops))}</w:tabs>" if tab_stops else ""

    avant = max(pt_vers_twips(emu_vers_pt(espacement_avant_emu * echelle_verticale)), 0)
    retrait_droite_emu = paragraphe.retrait_droite_emu
    if natif:
        origine_x = flux_origine_x_emu or 0
        gauche_emu = max(paragraphe.bbox.x0, paragraphe.retrait_gauche_emu) - origine_x
        if flux_largeur_emu is not None:
            retrait_droite_emu = max(
                0,
                flux_largeur_emu - max(0, paragraphe.bbox.x1 - origine_x),
            )
        # Les titres OCR tres grands ont souvent une bbox trop etroite. En flux Word,
        # conserver ce retrait droit force un retour artificiel au milieu du mot.
        if paragraphe.size_pt >= 18 or len(paragraphe.texte.strip()) <= 20 or len(paragraphe.texte.strip()) > 30:
            retrait_droite_emu = 0
    alignement_vertical = getattr(paragraphe, "vertical_alignement", "top") or "top"
    alignement_vertical_xml = (
        '<w:textAlignment w:val="center"/>'
        if natif and alignement_vertical in {"center", "middle"}
        else ""
    )
    contenu_para = (
        "<w:p><w:pPr>"
        f'<w:spacing w:before="{avant}" w:after="0" w:line="{interligne}" w:lineRule="exact"/>'
        f"{tabs}"
        f'<w:ind w:left="{max(pt_vers_twips(emu_vers_pt(gauche_emu)), 0) if natif else gauche}" '
        f'w:right="{max(pt_vers_twips(emu_vers_pt(retrait_droite_emu)), 0) if natif else 0}" '
        f'w:firstLine="{premiere}"/>'
        f"{alignement_vertical_xml}"
        f'<w:jc w:val="{alignement}"/>'
        "</w:pPr>"
        f"{runs}</w:p>"
    )

    if natif:
        return contenu_para

    vertical = getattr(paragraphe, "vertical_alignement", "top") or "top"
    ancre_verticale = {"center": "ctr", "middle": "ctr", "bottom": "b"}.get(vertical, "t")
    centre_vertical = "1" if ancre_verticale == "ctr" else "0"
    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/>'
        "<wps:spPr>"
        '<a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{max(bbox_ancre.largeur, 1)}" cy="{max(bbox_ancre.hauteur, 1)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        f"<wps:txbx><w:txbxContent>{contenu_para}</w:txbxContent></wps:txbx>"
        f'<wps:bodyPr rot="{_rotation_ooxml(paragraphe)}" spcFirstLastPara="0" vertOverflow="clip" '
        'horzOverflow="clip" vert="horz" wrap="square" '
        f'lIns="0" tIns="0" rIns="0" bIns="0" anchor="{ancre_verticale}" anchorCtr="{centre_vertical}">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(bbox_ancre, identifiant, z, f"Paragraphe {identifiant}", contenu)


def image_xml(element, identifiant: int, z: int, rel_id: str, derriere: bool = False, *, planned: bool = False) -> str:
    """Rend une image, ou une région rastérisée, comme image flottante ancrée."""
    bbox = quantifier_bbox(element.bbox)
    largeur = max(bbox.largeur, 1)
    hauteur = max(bbox.hauteur, 1)
    if not planned and getattr(element, "z_index", None) is not None:
        z = 100 + 10 * element.z_index
    elif not planned and getattr(element, "purpose", None) in {"formula", "symbol"}:
        z += 100000

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

    return _ancre(bbox, identifiant, z, f"Image {identifiant}", contenu, derriere)


def _span_ajuste_espacement_cellule(span, cell, vertical: bool):
    """Compresse l'approche dans les cellules serrées sans changer le corps.

    Le PDF place des glyphes ; Word recompose du texte. Dans les tableaux denses, les
    métriques Word sont souvent plus larges que celles du PDF original. La fidélité de
    police/taille est conservée en ajustant l'espacement inter-caractères, pas la taille.
    """
    if vertical:
        return span

    size_pt = float(span.size_pt)
    largeur_pt = max(emu_vers_pt(cell.bbox.largeur) - 1.2, 1.0)
    lignes = [ligne for ligne in str(span.texte or "").splitlines() if ligne] or [span.texte or ""]
    texte_large = max(lignes, key=len)
    estimation = max(len(texte_large), 1) * size_pt * 0.46
    if estimation <= largeur_pt:
        return span

    ecart_pt = largeur_pt - estimation
    interstices = max(len(texte_large) - 1, 1)
    correction = round(pt_vers_twips(ecart_pt / interstices))
    correction = max(correction, -12)
    if correction >= 0:
        return span
    espacement = int(span.espacement_twips or 0) + correction
    return _copier_span(span, espacement_twips=espacement)


def _span_contraste_cellule(span, fond: str | None):
    if not _couleur_sombre(fond):
        return span
    if (span.couleur or "").upper() not in {"000000", "111111", "222222"}:
        return span
    return _copier_span(span, couleur="FFFFFF")


def _union_bbox(a: BBox, b: BBox) -> BBox:
    from pdfexact.geometry import union

    return union(a, b)


def _bbox_spans_cellule(spans: list[Span]) -> BBox | None:
    bboxes = [span.bbox for span in spans if span.bbox is not None]
    if not bboxes:
        return None
    bbox = bboxes[0]
    for item in bboxes[1:]:
        bbox = _union_bbox(bbox, item)
    return quantifier_bbox(bbox)


def _marges_cellule_twips(cell, spans: list[Span], strict_geometry: bool) -> tuple[int, int, int, int, str]:
    if not strict_geometry:
        return 25, 15, 25, 15, "center"
    texte_bbox = _bbox_spans_cellule(spans)
    if texte_bbox is None:
        return 0, 0, 0, 0, "center"

    cell_bbox = quantifier_bbox(cell.bbox)
    alignement = getattr(cell, "alignement", "center") or "center"
    taille_max = max((float(span.size_pt) for span in spans), default=8.0)
    lignes = max(1, sum(max(1, str(span.texte or "").count("\n") + 1) for span in spans))
    hauteur_cellule = max(pt_vers_twips(emu_vers_pt(cell_bbox.hauteur)), 1)
    hauteur_texte = max(pt_vers_twips(taille_max * 1.02) * lignes, 1)
    marge_verticale_disponible = max(0, hauteur_cellule - hauteur_texte)

    haut_brut = max(0, pt_vers_twips(emu_vers_pt(texte_bbox.y0 - cell_bbox.y0)))
    bas_brut = max(0, pt_vers_twips(emu_vers_pt(cell_bbox.y1 - texte_bbox.y1)))
    haut = min(haut_brut, marge_verticale_disponible)
    bas = min(bas_brut, max(0, marge_verticale_disponible - haut))

    largeur_cellule = max(pt_vers_twips(emu_vers_pt(cell_bbox.largeur)), 1)
    marge_gauche_reelle = max(0, pt_vers_twips(emu_vers_pt(texte_bbox.x0 - cell_bbox.x0)))
    marge_droite_reelle = max(0, pt_vers_twips(emu_vers_pt(cell_bbox.x1 - texte_bbox.x1)))
    maximum_h = max(0, largeur_cellule - 1)
    if alignement == "left":
        gauche = min(marge_gauche_reelle, maximum_h)
        droite = 0
    elif alignement == "right":
        gauche = 0
        droite = min(marge_droite_reelle, maximum_h)
    else:
        gauche = 0
        droite = 0
    return (
        gauche,
        haut,
        droite,
        bas,
        alignement,
    )


def _hauteurs_lignes_table(element) -> list[int]:
    """Calcule des hauteurs séquentielles même si PyMuPDF renvoie des rows chevauchantes."""
    if not element.rows:
        return []

    hauteurs: list[int] = []
    for index, row in enumerate(element.rows):
        y0 = row.bbox.y0
        prochain_y0 = None
        for suivante in element.rows[index + 1 :]:
            if suivante.bbox.y0 > y0:
                prochain_y0 = suivante.bbox.y0
                break
        y1 = prochain_y0 if prochain_y0 is not None else max(row.bbox.y1, element.bbox.y1)
        y1 = min(max(y1, y0 + 1), element.bbox.y1)
        hauteurs.append(max(y1 - y0, 1))

    total = sum(hauteurs)
    cible = max(element.bbox.hauteur, 1)
    if total <= cible:
        hauteurs[-1] += cible - total
    elif total > cible:
        ecart = total - cible
        for index in range(len(hauteurs) - 1, -1, -1):
            reduction = min(ecart, max(0, hauteurs[index] - 1))
            hauteurs[index] -= reduction
            ecart -= reduction
            if ecart <= 0:
                break
    return hauteurs


def table_body_xml(
    element,
    relations=None,
    strict_geometry: bool = True,
    positionne: bool = False,
    indentation_emu: int | None = None,
    texte_cellules: bool = True,
) -> str:
    """Rend le contenu Word natif d'un tableau PDF détecté."""
    bbox_table = quantifier_bbox(element.bbox)
    largeur = max(bbox_table.largeur, 1)
    grid = "".join(
        f'<w:gridCol w:w="{max(pt_vers_twips(emu_vers_pt(quantifier_coord(w))), 1)}"/>'
        for w in element.col_widths_emu
    )
    rows_xml = []
    hauteurs_lignes = _hauteurs_lignes_table(element)

    def _bordures_cellule(cell) -> str:
        if not cell.bordures:
            return ""
        noms = {
            "top": "top",
            "left": "left",
            "bottom": "bottom",
            "right": "right",
        }
        parties = []
        for cle, balise in noms.items():
            bordure = cell.bordures.get(cle)
            if bordure is not None and bordure.visible:
                parties.append(
                    f'<w:{balise} w:val="single" w:sz="{bordure.sz}" '
                    f'w:space="0" w:color="{bordure.couleur}"/>'
                )
        return f"<w:tcBorders>{''.join(parties)}</w:tcBorders>"

    for row_index, row in enumerate(element.rows):
        hauteur_ligne = (
            hauteurs_lignes[row_index]
            if row_index < len(hauteurs_lignes)
            else row.bbox.hauteur
        )
        tr_height = max(pt_vers_twips(emu_vers_pt(quantifier_coord(hauteur_ligne))), 1)
        cells_xml = []
        for cell in row.cells:
            cell_bbox = quantifier_bbox(cell.bbox)
            tc_width = max(pt_vers_twips(emu_vers_pt(cell_bbox.largeur)), 1)
            grid_span = (
                f'<w:gridSpan w:val="{cell.col_span}"/>'
                if cell.col_span > 1
                else ""
            )
            shading = f'<w:shd w:fill="{cell.fond}"/>' if cell.fond else ""
            borders = _bordures_cellule(cell)
            v_merge = ""
            if getattr(cell, "v_merge", None) == "restart":
                v_merge = '<w:vMerge w:val="restart"/>'
            elif getattr(cell, "v_merge", None) == "continue":
                v_merge = "<w:vMerge/>"
            spans = (
                cell.spans
                or [
                    Span(
                        texte=cell.texte,
                        police=element.police,
                        size_pt=element.size_pt,
                        couleur=element.couleur,
                    )
                ]
                if texte_cellules
                else []
            )
            direction_texte = (
                f'<w:textDirection w:val="{cell.direction_texte}"/>'
                if getattr(cell, "direction_texte", None)
                else ""
            )
            if strict_geometry:
                spans = [
                    _span_contraste_cellule(
                        _span_ajuste_espacement_cellule(
                            span,
                            cell,
                            bool(getattr(cell, "direction_texte", None)),
                        ),
                        cell.fond,
                    )
                    for span in spans
                ]
            runs = "".join(_run_xml(span, relations) for span in spans)
            marge_gauche, marge_haut, marge_droite, marge_bas, alignement = _marges_cellule_twips(
                cell, spans, strict_geometry
            )
            taille_max = max((float(span.size_pt) for span in spans), default=float(element.size_pt))
            interligne = max(pt_vers_twips(taille_max * (1.02 if strict_geometry else 1.12)), 1)
            cells_xml.append(
                "<w:tc>"
                "<w:tcPr>"
                f'<w:tcW w:w="{tc_width}" w:type="dxa"/>'
                f"{grid_span}{v_merge}{shading}{borders}{direction_texte}"
                f'<w:vAlign w:val="{"top" if strict_geometry else "center"}"/>'
                f'<w:tcMar><w:top w:w="{marge_haut}" w:type="dxa"/><w:left w:w="{marge_gauche}" w:type="dxa"/>'
                f'<w:bottom w:w="{marge_bas}" w:type="dxa"/><w:right w:w="{marge_droite}" w:type="dxa"/></w:tcMar>'
                "</w:tcPr>"
                '<w:p><w:pPr>'
                f'<w:spacing w:before="0" w:after="0" w:line="{interligne}" '
                f'w:lineRule="{"exact" if strict_geometry else "auto"}"/>'
                f'<w:jc w:val="{alignement}"/></w:pPr>'
                f"{runs}</w:p>"
                "</w:tc>"
            )
        rows_xml.append(
            "<w:tr>"
            f'<w:trPr><w:cantSplit/><w:trHeight w:val="{tr_height}" '
            f'w:hRule="{"exact" if strict_geometry else "atLeast"}"/></w:trPr>'
            f"{''.join(cells_xml)}</w:tr>"
        )

    cell_margin = (
        '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar>'
        if strict_geometry
        else ""
    )
    position_table = (
        '<w:tblpPr w:leftFromText="0" w:rightFromText="0" '
        'w:topFromText="0" w:bottomFromText="0" '
        'w:vertAnchor="page" w:horzAnchor="page" '
        f'w:tblpX="{max(pt_vers_twips(emu_vers_pt(bbox_table.x0)), 0)}" '
        f'w:tblpY="{max(pt_vers_twips(emu_vers_pt(bbox_table.y0)), 0)}"/>'
        if positionne
        else f'<w:tblInd w:w="{max(pt_vers_twips(emu_vers_pt(bbox_table.x0 if indentation_emu is None else quantifier_coord(indentation_emu))), 0)}" w:type="dxa"/>'
    )
    if getattr(element, "bordures_globales", True):
        tbl_borders = (
            '<w:tblBorders>'
            f'<w:top w:val="single" w:sz="{element.bordure_sz}" w:space="0" w:color="{element.bordure_couleur}"/>'
            f'<w:left w:val="single" w:sz="{element.bordure_sz}" w:space="0" w:color="{element.bordure_couleur}"/>'
            f'<w:bottom w:val="single" w:sz="{element.bordure_sz}" w:space="0" w:color="{element.bordure_couleur}"/>'
            f'<w:right w:val="single" w:sz="{element.bordure_sz}" w:space="0" w:color="{element.bordure_couleur}"/>'
            f'<w:insideH w:val="single" w:sz="{element.bordure_sz}" w:space="0" w:color="{element.bordure_couleur}"/>'
            f'<w:insideV w:val="single" w:sz="{element.bordure_sz}" w:space="0" w:color="{element.bordure_couleur}"/>'
            '</w:tblBorders>'
        )
    else:
        tbl_borders = (
            '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/>'
            '<w:bottom w:val="nil"/><w:right w:val="nil"/>'
            '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'
        )
    tbl = (
        "<w:tbl>"
        "<w:tblPr>"
        f'<w:tblW w:w="{max(pt_vers_twips(emu_vers_pt(largeur)), 1)}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        f"{position_table}"
        f"{cell_margin}"
        f"{tbl_borders}"
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        f"{''.join(rows_xml)}"
        "</w:tbl>"
    )
    return tbl


def _lignes_cellule_overlay(cell, element=None) -> list[Line]:
    def _est_fallback_cellule(span: Span) -> bool:
        if span.bbox is None:
            return False
        tolerance = pt_vers_emu(0.1)
        return (
            abs(span.bbox.x0 - cell.bbox.x0) <= tolerance
            and abs(span.bbox.y0 - cell.bbox.y0) <= tolerance
            and abs(span.bbox.x1 - cell.bbox.x1) <= tolerance
            and abs(span.bbox.y1 - cell.bbox.y1) <= tolerance
        )

    spans_avec_bbox = [
        _span_contraste_cellule(
            _copier_span(span, texte=str(span.texte or "").replace("\n", "")),
            cell.fond,
        )
        for span in cell.spans
        if span.bbox is not None and not _est_fallback_cellule(span) and str(span.texte or "").replace("\n", "").strip()
    ]
    if not spans_avec_bbox:
        return []

    if element is not None:
        cellules = sum(len(row.cells) for row in getattr(element, "rows", []))
        dense = cellules >= 120 or getattr(element, "bbox", cell.bbox).largeur >= pt_vers_emu(500)
        if dense:
            lignes = []
            for span in spans_avec_bbox:
                bbox = quantifier_bbox(span.bbox)
                texte = str(span.texte or "").strip()
                if not texte:
                    continue
                propre = _copier_span(span, texte=texte)
                lignes.append(
                    Line(
                        bbox=bbox,
                        spans=[propre],
                        hauteur_ligne_emu=max(bbox.hauteur, pt_vers_emu(propre.size_pt * 1.02)),
                        largeur_cible_emu=max(bbox.largeur, 1),
                        alignement="left",
                    )
                )
            return lignes

    groupes: list[list[Span]] = []
    tolerance = pt_vers_emu(2.0)
    for span in sorted(spans_avec_bbox, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        centre = (span.bbox.y0 + span.bbox.y1) // 2
        if groupes:
            centre_groupe = sum((item.bbox.y0 + item.bbox.y1) // 2 for item in groupes[-1]) // len(groupes[-1])
            if abs(centre - centre_groupe) <= tolerance:
                groupes[-1].append(span)
                continue
        groupes.append([span])

    lignes: list[Line] = []
    for groupe in groupes:
        bbox = groupe[0].bbox
        for span in groupe[1:]:
            bbox = _union_bbox(bbox, span.bbox)
        bbox = quantifier_bbox(bbox)
        taille = max((span.size_pt for span in groupe), default=8.0)
        lignes.append(
            Line(
                bbox=bbox,
                spans=sorted(groupe, key=lambda item: item.bbox.x0),
                hauteur_ligne_emu=max(bbox.hauteur, pt_vers_emu(taille * 1.02)),
                largeur_cible_emu=max(bbox.largeur, 1),
                alignement=getattr(cell, "alignement", "left") or "left",
            )
        )
    return lignes


def table_text_overlays_xml(element, compteur: list, z: int, relations=None, largeur_page_emu: int | None = None, polices=None) -> str:
    morceaux: list[str] = []
    for row in element.rows:
        for cell in row.cells:
            for ligne in _lignes_cellule_overlay(cell, element):
                compteur[0] += 1
                morceaux.append(zone_texte_xml(ligne, compteur[0], z, relations, largeur_page_emu, polices))
    return "".join(morceaux)


def _rect_rempli_xml(bbox: BBox, identifiant: int, z: int, couleur: str, alpha: float = 1.0) -> str:
    bbox = quantifier_bbox(bbox)
    largeur = max(bbox.largeur, 1)
    hauteur = max(bbox.hauteur, 1)
    alpha_xml = ""
    if alpha < 1.0:
        alpha_xml = f'<a:alpha val="{max(0, round(alpha * 100000))}"/>'
    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp><wps:cNvSpPr/>"
        "<wps:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:solidFill><a:srgbClr val="{couleur}">{alpha_xml}</a:srgbClr></a:solidFill>'
        "<a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        '<wps:bodyPr rot="0" anchor="t"/>'
        "</wps:wsp></a:graphicData></a:graphic>"
    )
    return _ancre(bbox, identifiant, z, f"Trait {identifiant}", contenu)


def _positions_uniques_table(positions: list[int]) -> list[int]:
    positions = sorted(quantifier_coord(pos) for pos in positions)
    if not positions:
        return []
    tolerance = pt_vers_emu(0.6)
    groupes: list[list[int]] = [[positions[0]]]
    for pos in positions[1:]:
        if pos - groupes[-1][-1] <= tolerance:
            groupes[-1].append(pos)
        else:
            groupes.append([pos])
    return [quantifier_coord(round(sum(groupe) / len(groupe))) for groupe in groupes]


def _positions_x_table(element) -> list[int]:
    x = quantifier_bbox(element.bbox).x0
    positions = [x]
    for largeur in element.col_widths_emu:
        x += quantifier_coord(largeur)
        positions.append(x)
    positions[-1] = quantifier_bbox(element.bbox).x1
    return _positions_uniques_table(positions)


def _positions_y_table(element) -> list[int]:
    bbox = quantifier_bbox(element.bbox)
    positions = [bbox.y0]
    for row in element.rows:
        positions.append(quantifier_coord(row.bbox.y0))
        positions.append(quantifier_coord(row.bbox.y1))
    positions.append(bbox.y1)
    return _positions_uniques_table([pos for pos in positions if bbox.y0 <= pos <= bbox.y1])


def table_grid_overlays_xml(element, compteur: list, z: int) -> str:
    """Dessine une grille de table en ancres absolues, sans reflow Word."""
    bbox = quantifier_bbox(element.bbox)
    couleur = element.bordure_couleur or "000000"
    epaisseur = max(pt_vers_emu(min(max(float(element.bordure_sz) / 8.0, 0.25), 0.35)), 1)
    demi = max(epaisseur // 2, 1)
    morceaux: list[str] = []

    for y in _positions_y_table(element):
        compteur[0] += 1
        ligne = BBox(bbox.x0, y - demi, bbox.x1, y - demi + epaisseur)
        morceaux.append(_rect_rempli_xml(ligne, compteur[0], z, couleur))

    for x in _positions_x_table(element):
        compteur[0] += 1
        ligne = BBox(x - demi, bbox.y0, x - demi + epaisseur, bbox.y1)
        morceaux.append(_rect_rempli_xml(ligne, compteur[0], z, couleur))

    return "".join(morceaux)


def table_cell_background_overlays_xml(element, compteur: list, z: int) -> str:
    """Dessine les fonds de cellules avant la grille et le texte."""
    morceaux: list[str] = []
    for row in element.rows:
        for cell in row.cells:
            if not cell.fond:
                continue
            compteur[0] += 1
            morceaux.append(_rect_rempli_xml(cell.bbox, compteur[0], z, cell.fond))
    return "".join(morceaux)


def table_xml(element, identifiant: int, z: int, relations=None) -> str:
    """Rend un tableau PDF détecté en vrai tableau Word, ancré à la page."""
    bbox = quantifier_bbox(element.bbox)
    largeur = max(bbox.largeur, 1)
    hauteur = max(bbox.hauteur, 1)
    tbl = table_body_xml(element, relations, indentation_emu=0)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/>'
        "<wps:spPr>"
        '<a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        "</wps:spPr>"
        f"<wps:txbx><w:txbxContent>{tbl}</w:txbxContent></wps:txbx>"
        '<wps:bodyPr rot="0" spcFirstLastPara="0" vertOverflow="clip" '
        'horzOverflow="clip" vert="horz" wrap="none" '
        'lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" anchorCtr="0">'
        "<a:noAutofit/></wps:bodyPr>"
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(bbox, identifiant, z, f"Tableau {identifiant}", contenu)


def _commandes_xml(chemins, origine_x: int, origine_y: int) -> str:
    """Traduit les chemins en éléments de a:path, en coordonnées relatives à la bbox."""
    morceaux = []
    for chemin in chemins:
        for operateur, points in chemin:
            relatifs = [
                (quantifier_coord(x) - origine_x, quantifier_coord(y) - origine_y)
                for x, y in points
            ]
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


def forme_xml(element, identifiant: int, z: int, derriere: bool = False, *, planned: bool = False) -> str:
    """Rend une forme vectorielle en géométrie personnalisée DrawingML."""
    bbox = quantifier_bbox(element.bbox)
    largeur = max(bbox.largeur, 1)
    hauteur = max(bbox.hauteur, 1)
    if not planned and getattr(element, "z_index", None) is not None:
        z = 100 + 10 * element.z_index

    if element.remplissage:
        alpha = ""
        if element.alpha < 1.0:
            alpha = f'<a:alpha val="{max(0, round(element.alpha * 100000))}"/>'
        remplissage = (
            f'<a:solidFill><a:srgbClr val="{element.remplissage}">{alpha}</a:srgbClr>'
            "</a:solidFill>"
        )
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

    commandes = _commandes_xml(element.chemins, bbox.x0, bbox.y0)
    geometrie = (
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        if not commandes
        else (
            "<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>"
            f'<a:rect l="0" t="0" r="{largeur}" b="{hauteur}"/>'
            f'<a:pathLst><a:path w="{largeur}" h="{hauteur}" '
            f'fill="{"norm" if element.remplissage else "none"}">{commandes}</a:path></a:pathLst>'
            "</a:custGeom>"
        )
    )

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp><wps:cNvSpPr/>"
        "<wps:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        f"{geometrie}"
        f"{remplissage}{trait}"
        "</wps:spPr>"
        '<wps:bodyPr rot="0" anchor="t"/>'
        "</wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(bbox, identifiant, z, f"Forme {identifiant}", contenu, derriere)


def zone_lien_xml(element, identifiant: int, z: int, rel_id: str) -> str:
    """Rend un lien de zone comme rectangle invisible cliquable."""
    bbox = quantifier_bbox(element.bbox)
    largeur = max(bbox.largeur, 1)
    hauteur = max(bbox.hauteur, 1)

    contenu = (
        "<a:graphic><a:graphicData "
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        "<wps:wsp><wps:cNvSpPr/><wps:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{largeur}" cy="{hauteur}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "<a:noFill/><a:ln><a:noFill/></a:ln>"
        f'<a:hlinkClick r:id="{rel_id}"/>'
        "</wps:spPr><wps:bodyPr/></wps:wsp></a:graphicData></a:graphic>"
    )

    return _ancre(bbox, identifiant, z, f"Lien {identifiant}", contenu)
