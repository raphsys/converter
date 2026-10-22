"""Extraction du texte : dictionnaire PyMuPDF vers TextBox / Line / Span.

Le découpage se fait à la ligne. Chaque ligne devient une zone de texte OOXML posée de
sorte que sa baseline retombe exactement là où le PDF l'avait mise.

Deux grandeurs gouvernent ce placement, et toutes deux viennent de la police **déclarée
dans le docx**, pas de celle du PDF : c'est avec elles que Word composera.

- Hauteur de ligne imposée : ascendante + descendante. Cette valeur exacte fait tomber la
  baseline à `ascendante` du haut de la zone.
- Sommet de la zone : baseline du PDF moins cette ascendante.
"""
import re
import math
from dataclasses import asdict
from functools import lru_cache

import pymupdf
from fontTools.agl import toUnicode
from fontTools.ttLib import TTFont

from pdfexact.extract.fonts import (
    ascendante_pt,
    descendante_pt,
    mesurer_largeur_pt,
)
from pdfexact.fontlib import normaliser_nom
from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt, pt_vers_emu, pt_vers_twips
from pdfexact.ir import FontRef, Line, Span, TextBox, element_source_ids
from pdfexact.scene import ensure_source_identity
from pdfexact.extract.orientation import angle_depuis_points, classer_orientation
from pdfexact.analysis.text_geometry import geometry_contract_for, presentation_for

_BIT_ITALIQUE = 1 << 1
_BIT_GRAS = 1 << 4

# Word applique l'espacement inter-caractères après chaque caractère, dernier compris.
# L'écart total à répartir se divise donc par le nombre de caractères, pas par les
# intervalles. Vérifié par tests/visual/test_placement_texte.py.
_ESPACEMENT_PAR_CARACTERE = True


def _couleur_hexa(valeur: int) -> str:
    if isinstance(valeur, tuple):
        rouge, vert, bleu = (max(0, min(255, round(canal * 255))) for canal in valeur[:3])
        return f"{rouge:02X}{vert:02X}{bleu:02X}"
    return f"{int(valeur) & 0xFFFFFF:06X}"


def _bbox_depuis_liste(
    quadruplet,
    geometrie: PageGeometry | None = None,
) -> BBox:
    rect = pymupdf.Rect(
        float(quadruplet[0]),
        float(quadruplet[1]),
        float(quadruplet[2]),
        float(quadruplet[3]),
    )
    if geometrie is not None:
        return geometrie.bbox_depuis_rect_natif(rect)
    return BBox(
        pt_vers_emu(rect.x0),
        pt_vers_emu(rect.y0),
        pt_vers_emu(rect.x1),
        pt_vers_emu(rect.y1),
    )


def _point_depuis_origine(
    origine,
    geometrie: PageGeometry | None = None,
) -> tuple[float, float]:
    x, y = float(origine[0]), float(origine[1])
    if geometrie is not None:
        return geometrie.point_natif_vers_affiche(x, y)
    return x, y


def _angle_direction(
    direction,
    geometrie: PageGeometry | None = None,
) -> float:
    """Calcule l'angle dirige visible dans le repere mathematique de l'IR.

    La matrice de page agit d'abord dans le repere PyMuPDF, dont Y descend.
    L'inversion de Y vient ensuite ; replier modulo 180 perdrait le sens du texte.
    """
    try:
        dx, dy = float(direction[0]), float(direction[1])
    except (TypeError, ValueError, IndexError):
        dx, dy = 1.0, 0.0
    if geometrie is not None:
        dx, dy = geometrie.vecteur_natif_vers_affiche(dx, dy)
    return angle_depuis_points(((0.0, 0.0), (dx, -dy)))


def _quad_affiche(quad, geometrie: PageGeometry | None = None):
    points = []
    for point in quad or ():
        coordinates = (point.x, point.y) if hasattr(point, "x") and hasattr(point, "y") else tuple(point)
        x, y = _point_depuis_origine(coordinates, geometrie)
        points.append((pt_vers_emu(x), pt_vers_emu(y)))
    return tuple(points)


def _resoudre_police(nom_du_span: str, polices: dict) -> str:
    """Relie un span à sa police par le nom PostScript.

    get_text("dict") ne donne pas de xref : la clé `font` du span et le champ `basefont`
    de get_fonts() sont le seul point de jonction.
    """
    if not polices:
        raise ValueError("aucune police collectée pour ce document")

    nom = normaliser_nom(nom_du_span or "")
    if nom in polices:
        return nom

    minuscule = nom.lower()
    for identifiant in polices:
        if identifiant.lower() == minuscule:
            return identifiant

    return next(iter(polices))


def _style_depuis_nom(nom: str, drapeaux: int = 0) -> tuple[bool, bool]:
    minuscule = nom.lower()
    compact = re.sub(r"[^a-z0-9]", "", minuscule)
    for suffixe in ("psmt", "mt", "ps", "ms"):
        if compact.endswith(suffixe) and len(compact) > len(suffixe):
            compact = compact[: -len(suffixe)]
            break
    gras = bool(drapeaux & _BIT_GRAS) or any(
        mot in minuscule for mot in ("bold", "demi", "black", "heavy", "extrabold")
    ) or compact.endswith(("bd", "bdit", "bold", "bolditalic", "semibold"))
    italique = bool(drapeaux & _BIT_ITALIQUE) or any(
        mot in minuscule for mot in ("italic", "oblique")
    ) or compact.endswith(("it", "bdit", "italic", "bolditalic"))
    return gras, italique


@lru_cache(maxsize=128)
def _ordre_glyphes(chemin) -> tuple[str, ...]:
    try:
        return tuple(TTFont(chemin, fontNumber=0, lazy=True).getGlyphOrder())
    except Exception:  # noqa: BLE001
        return ()


def _texte_depuis_glyphe(code: int, gid: int, asset) -> str:
    """Reconstruit le caractère depuis le glyph id quand le Unicode PDF est douteux."""
    if asset.chemin:
        ordre = _ordre_glyphes(asset.chemin)
        if 0 <= gid < len(ordre):
            try:
                texte = toUnicode(ordre[gid])
            except KeyError:
                texte = ""
            if texte:
                return texte
    try:
        return chr(code)
    except (TypeError, ValueError):
        return ""


def _corriger_espacement(ligne: Line, polices: dict) -> None:
    """Répartit l'écart de largeur sur les caractères, en vingtièmes de point.

    Word ne restitue pas exactement les largeurs du PDF, même à police reconnue : le PDF
    a pu poser ses glyphes un à un avec ses propres avances. Sans correction, le bord
    droit de la ligne ne tombe pas au bon endroit.
    """
    caracteres = sum(len(span.texte) for span in ligne.spans)
    if caracteres < 1:
        return
    texte_ligne = "".join(span.texte for span in ligne.spans)

    mesuree_pt = sum(
        mesurer_largeur_pt(span.texte, polices[span.police.font_id], span.size_pt)
        for span in ligne.spans
    )
    ecart_pt = emu_vers_pt(ligne.largeur_cible_emu) - mesuree_pt
    diviseur = caracteres if _ESPACEMENT_PAR_CARACTERE else max(caracteres - 1, 1)

    espacement = round(pt_vers_twips(ecart_pt / diviseur))
    if espacement < 0 and _ligne_mots_lisible(texte_ligne):
        espacement = 0
    espacement = max(-24, min(18, espacement))
    for span in ligne.spans:
        span.espacement_twips = espacement


def _ligne_mots_lisible(texte: str) -> bool:
    from pdfexact.extract.ocr_routing import has_non_latin_letters
    if has_non_latin_letters(texte):
        return True
    return bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}\s+[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", texte))


def _span_ir(
    span: dict,
    polices: dict,
    geometrie: PageGeometry | None = None,
) -> Span | None:
    texte = span.get("text", "")
    if not texte and not span.get("bbox"):
        return None

    font_id = _resoudre_police(span.get("font", ""), polices)
    asset = polices[font_id]
    drapeaux = int(span.get("flags", 0))
    taille_pt = round(float(span.get("size", 12.0)), 2)
    nom_source = span.get("font", "")
    if "AkzidenzGroteskBE" in nom_source and "Cn" in nom_source:
        taille_pt = round(taille_pt * 0.88, 2)

    gras, italique = _style_depuis_nom(nom_source, drapeaux)
    return Span(
        texte=texte,
        police=FontRef(
            font_id=font_id,
            famille=asset.famille,
            gras=gras,
            italique=italique,
        ),
        size_pt=taille_pt,
        couleur=_couleur_hexa(span.get("color", 0)),
        bbox=(
            _bbox_depuis_liste(span["bbox"], geometrie)
            if span.get("bbox")
            else None
        ),
        source_kind="pdf-native",
        font_metrics=dict(asset.metriques),
        glyph_ids=tuple(char["glyph_id"] for char in span.get("chars", ()) if "glyph_id" in char),
        to_unicode_status="decoded-unicode" if span.get("chars") else None,
        attributes={"source_font_name": nom_source, "source_origin": span.get("origin"),
                    "source_size_pt": span.get("size"), "source_alpha": span.get("alpha")},
    )


def _ligne_ir(
    ligne: dict,
    polices: dict,
    geometrie: PageGeometry | None = None,
) -> Line | None:
    spans_ir = []
    spans_bruts = []
    for span in ligne.get("spans", []):
        converti = _span_ir(span, polices, geometrie)
        if converti is not None:
            angle = _angle_direction(ligne.get("dir") or (1.0, 0.0), geometrie)
            converti.angle_deg = angle
            converti.orientation = classer_orientation(converti.texte, angle).kind
            try:
                quad = span.get("quad") or pymupdf.recover_span_quad(ligne.get("dir") or (1.0, 0.0), span)
            except (KeyError, ValueError, TypeError):
                quad = None
            converti.quad = _quad_affiche(quad, geometrie)
            if span.get("origin") is not None:
                origin = _point_depuis_origine(span["origin"], geometrie)
                start = (pt_vers_emu(origin[0]), pt_vers_emu(origin[1]))
                dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                length = max(((x - start[0]) * dx + (y - start[1]) * dy for x, y in converti.quad), default=0)
                converti.baseline_points = (start, (round(start[0] + length * dx), round(start[1] + length * dy)))
                converti.baseline = converti.baseline_points
            spans_ir.append(converti)
            spans_bruts.append(span)

    if not spans_ir:
        return None

    boite = _bbox_depuis_liste(ligne["bbox"], geometrie)
    direction = ligne.get("dir") or (1.0, 0.0)
    angle = _angle_direction(direction, geometrie)
    centre_x = (boite.x0 + boite.x1) / 2.0
    centre_y = (boite.y0 + boite.y1) / 2.0
    # Pour une ligne tournee, la longueur de la ligne est portee par la hauteur
    # de la bbox source. Utiliser sa largeur (ancienne logique) reduit une legende
    # verticale a la seule hauteur d'un glyphe.
    horizontal = abs(math.cos(math.radians(angle))) >= abs(math.sin(math.radians(angle)))
    longueur_base = max(boite.largeur if horizontal else boite.hauteur, 1)
    direction_x = math.cos(math.radians(angle))
    direction_y = math.sin(math.radians(angle))
    baseline_points = (
        (centre_x - direction_x * longueur_base / 2.0, centre_y - direction_y * longueur_base / 2.0),
        (centre_x + direction_x * longueur_base / 2.0, centre_y + direction_y * longueur_base / 2.0),
    )
    if spans_ir[0].baseline_points and spans_ir[-1].baseline_points:
        baseline_points = (spans_ir[0].baseline_points[0], spans_ir[-1].baseline_points[-1])
    orientation = classer_orientation(
        "".join(span.texte for span in spans_ir),
        angle,
        baseline_points=baseline_points,
    )
    premier, span_brut = spans_ir[0], spans_bruts[0]
    asset = polices[premier.police.font_id]

    ascendante = ascendante_pt(asset, premier.size_pt)
    descendante = descendante_pt(asset, premier.size_pt)
    origine_affiche = _point_depuis_origine(
        span_brut.get("origin", (0.0, 0.0)),
        geometrie,
    )
    baseline_pt = origine_affiche[1]

    haut_emu = pt_vers_emu(baseline_pt - ascendante)
    hauteur_emu = max(pt_vers_emu(ascendante + descendante), 1)
    if orientation.kind != "horizontal":
        # La bbox PDF contient deja l'emprise reelle de la ligne orientee. Elle
        # doit rester la geometrie du cadre Word ; la hauteur de police ne sert
        # qu'a la metrique interne du run.
        bbox_ligne = boite
        hauteur_emu = max(boite.hauteur, hauteur_emu)
    else:
        bbox_ligne = BBox(boite.x0, haut_emu, boite.x1, haut_emu + hauteur_emu)

    line_quad = ligne.get("quad")
    if not line_quad:
        try:
            line_quad = pymupdf.recover_line_quad(ligne)
        except (KeyError, ValueError, TypeError):
            line_quad = None
    ligne_ir = Line(
        bbox=bbox_ligne,
        spans=spans_ir,
        hauteur_ligne_emu=hauteur_emu,
        largeur_cible_emu=max(boite.largeur if orientation.kind == "horizontal" else boite.hauteur, 1),
        quad=_quad_affiche(line_quad, geometrie),
        angle_deg=orientation.angle_deg,
        orientation=orientation.kind,
        baseline_points=tuple((int(x), int(y)) for x, y in baseline_points),
        semantic_role=orientation.semantic_role,
        curved=orientation.curved,
        source_kind="pdf-native",
    )
    _corriger_espacement(ligne_ir, polices)
    return ligne_ir


def extraire_texte(
    page,
    polices: dict,
    geometrie: PageGeometry | None = None,
) -> list[TextBox]:
    """Retourne les blocs de texte de la page, en EMU."""
    blocs_ir: list[TextBox] = []
    # Dict block numbers are not paint sequence numbers. Trace origins refer to
    # the same source glyph positions, before any font/line metric adjustment.
    paint_origins = {}
    for trace in page.get_texttrace():
        for char in trace.get("chars", ()):
            origin = tuple(round(float(value), 3) for value in char[2])
            paint_origins.setdefault((origin, char[0]), []).append((trace, char))

    for block_index, bloc in enumerate(page.get_text("rawdict").get("blocks", [])):
        if bloc.get("type") != 0:
            continue

        for source_line in bloc.get("lines", []):
            spans = []
            for source_span in source_line.get("spans", []):
                groups = []
                for char in source_span.get("chars", []):
                    origin = tuple(round(float(value), 3) for value in char["origin"])
                    candidates = paint_origins.get((origin, ord(char["c"])), [])
                    sequence = None
                    if candidates:
                        # Repeated glyphs may share an origin but have different
                        # styles/paint times. Consume the matching occurrence;
                        # never promote an earlier glyph to a later paint layer.
                        def identity_distance(candidate):
                            trace, glyph = candidate
                            return (
                                normaliser_nom(trace.get("font", "")) != normaliser_nom(source_span.get("font", "")),
                                _couleur_hexa(trace.get("color", 0)) != _couleur_hexa(source_span.get("color", 0)),
                                abs(float(trace.get("size", 0)) - float(source_span.get("size", 0))),
                                tuple(trace.get("dir", (1, 0))) != tuple(source_line.get("dir", (1, 0))),
                                abs((glyph[3][2] - glyph[3][0]) - (char["bbox"][2] - char["bbox"][0])),
                            )

                        index = min(range(len(candidates)), key=lambda index: identity_distance(candidates[index]))
                        trace, _glyph = candidates.pop(index)
                        sequence = trace["seqno"]
                        char["glyph_id"] = _glyph[1]
                        char["source_opacity"] = trace.get("opacity")
                    if not groups or groups[-1][0] != sequence:
                        groups.append((sequence, []))
                    groups[-1][1].append(char)
                for sequence, chars in groups:
                    spans.append({
                        **source_span,
                        "text": "".join(char["c"] for char in chars),
                        "origin": chars[0]["origin"],
                        "bbox": (
                            min(char["bbox"][0] for char in chars),
                            min(char["bbox"][1] for char in chars),
                            max(char["bbox"][2] for char in chars),
                            max(char["bbox"][3] for char in chars),
                        ),
                        "paint_sequence": sequence,
                        "chars": chars,
                    })
            source_line["spans"] = spans

        lignes_ir = [
            converti
            for converti in (
                _ligne_ir(ligne, polices, geometrie)
                for ligne in bloc.get("lines", [])
            )
            if converti is not None
        ]
        if lignes_ir:
            for source_line, line in zip(
                (line for line in bloc.get("lines", []) if any(span.get("text") for span in line.get("spans", []))),
                lignes_ir,
            ):
                sequences = []
                for source_span, span in zip(
                    (span for span in source_line.get("spans", []) if span.get("text")), line.spans,
                ):
                    span.z_index = source_span.get("paint_sequence")
                    span.z_order = span.z_index
                    source_opacity = next((char.get("source_opacity") for char in source_span.get("chars", ())
                                           if char.get("source_opacity") is not None), None)
                    span.opacity = source_opacity if source_opacity is not None else float(source_span["alpha"]) / 255.0 if source_span.get("alpha") is not None else 1.0
                    if span.z_index is not None:
                        sequences.append(span.z_index)
                line.z_index = min(sequences) if sequences else None
            element = TextBox(
                bbox=_bbox_depuis_liste(bloc["bbox"], geometrie),
                lignes=lignes_ir,
                z_index=min((line.z_index for line in lignes_ir if line.z_index is not None), default=None),
                source_kind="pdf-native",
            )
            ensure_source_identity(element, getattr(page, "number", 0), source_kind="pdf-native",
                                   source_token=f"rawdict-block:{bloc.get('number', block_index)}")
            element.geometry = geometry_contract_for(element)
            element.presentation = asdict(presentation_for(element))
            blocs_ir.append(element)

    return blocs_ir


def dedoublonner_textboxes_paragraphes(blocs: list[TextBox]) -> list[TextBox]:
    """Nettoie les doublons natifs avant de construire les paragraphes Word.

    Les PDF de mise en page contiennent parfois le même objet texte deux fois, ou
    un fragment d'une/deux lettres posé au-dessus d'un bloc complet. Ces fragments
    ne doivent pas devenir des paragraphes séparés.
    """
    for index, element in enumerate(blocs):
        ensure_source_identity(element, getattr(element, "source_page_index", 0), source_kind="pdf-native",
                               source_token=f"native-acquisition:{index}")
    resultat: list[TextBox] = []
    for candidat in sorted(blocs, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        texte = " ".join(
            span.texte for ligne in candidat.lignes for span in ligne.spans
        ).strip()
        if not texte:
            resultat.append(candidat)
            continue
        supprimer = False
        for existant in resultat:
            texte_existant = " ".join(
                span.texte for ligne in existant.lignes for span in ligne.spans
            ).strip()
            intersection = BBox(
                max(candidat.bbox.x0, existant.bbox.x0),
                max(candidat.bbox.y0, existant.bbox.y0),
                min(candidat.bbox.x1, existant.bbox.x1),
                min(candidat.bbox.y1, existant.bbox.y1),
            )
            if intersection.largeur <= 0 or intersection.hauteur <= 0:
                continue
            aire_candidat = max(candidat.bbox.largeur * candidat.bbox.hauteur, 1)
            aire_existant = max(existant.bbox.largeur * existant.bbox.hauteur, 1)
            aire_intersection = intersection.largeur * intersection.hauteur
            recouvrement = aire_intersection / min(aire_candidat, aire_existant)
            from pdfexact.extract.document import _preuve_doublon_texte

            equivalent_paint = (
                candidat.bbox == existant.bbox
                and candidat.source_kind == existant.source_kind
                and candidat.z_index == existant.z_index
                and len(candidat.lignes) == len(existant.lignes)
                and all(_preuve_doublon_texte(a, b) for a, b in zip(candidat.lignes, existant.lignes))
                and all(getattr(candidat, name, None) == getattr(existant, name, None)
                        for name in ("alpha", "opacity", "clip_ids", "clip_bbox", "compositing"))
            )
            if texte == texte_existant and recouvrement >= 0.55 and equivalent_paint:
                ensure_source_identity(candidat, getattr(candidat, "source_page_index", 0))
                ensure_source_identity(existant, getattr(existant, "source_page_index", 0))
                candidat.attributes.update({"duplicate_of": existant.source_id, "duplicate_verified": True})
                existant.source_ids = tuple(dict.fromkeys((*element_source_ids(existant), *element_source_ids(candidat))))
                supprimer = True
                break
        if not supprimer:
            resultat.append(candidat)
    return resultat


def extraire_texte_glyphes(
    page,
    polices: dict,
    geometrie: PageGeometry | None = None,
) -> list[TextBox]:
    """Retourne une zone par glyphe, avec police/couleur/style au niveau caractère."""
    blocs_ir: list[TextBox] = []

    for trace in page.get_texttrace():
        font_id = _resoudre_police(trace.get("font", ""), polices)
        asset = polices[font_id]
        size_pt = round(float(trace.get("size", 12.0)), 2)
        ascendante = ascendante_pt(asset, size_pt)
        descendante = descendante_pt(asset, size_pt)
        hauteur_emu = max(pt_vers_emu(ascendante + descendante), 1)
        couleur = _couleur_hexa(trace.get("color", 0))
        gras, italique = _style_depuis_nom(trace.get("font", ""), int(trace.get("flags", 0)))
        direction = trace.get("dir") or (1.0, 0.0)
        angle = _angle_direction(direction, geometrie)
        points_base = tuple(
            (
                pt_vers_emu(
                    _point_depuis_origine(
                        (
                            (float(boite[0]) + float(boite[2])) / 2.0,
                            (float(boite[1]) + float(boite[3])) / 2.0,
                        ),
                        geometrie,
                    )[0]
                ),
                pt_vers_emu(
                    _point_depuis_origine(
                        (
                            (float(boite[0]) + float(boite[2])) / 2.0,
                            (float(boite[1]) + float(boite[3])) / 2.0,
                        ),
                        geometrie,
                    )[1]
                ),
            )
            for _code, _gid, _origine, boite in trace.get("chars", ())
        )

        for glyph_index, (code, gid, origine, boite_pt) in enumerate(trace.get("chars", ())):
            texte = _texte_depuis_glyphe(code, gid, asset)
            boite = _bbox_depuis_liste(boite_pt, geometrie)
            origine_affiche = _point_depuis_origine(origine, geometrie)
            if abs(angle) <= 7.0:
                haut_emu = pt_vers_emu(origine_affiche[1] - ascendante)
                boite = BBox(
                    boite.x0,
                    haut_emu,
                    boite.x1,
                    max(haut_emu + hauteur_emu, boite.y1),
                )
            span = Span(
                texte=texte,
                police=FontRef(
                    font_id=font_id,
                    famille=asset.famille,
                    gras=gras,
                    italique=italique,
                ),
                size_pt=size_pt,
                couleur=couleur,
                bbox=boite,
                source_kind="pdf-native",
                z_index=trace.get("seqno"),
                glyph_ids=(gid,),
                to_unicode_status="unicode-present" if code >= 0 else "unicode-missing",
                font_metrics=dict(asset.metriques),
                attributes={"source_font_name": trace.get("font"), "source_alpha": trace.get("opacity")},
            )
            span.opacity = trace.get("opacity", 1.0)
            orientation = classer_orientation(
                texte,
                angle,
                baseline_points=points_base,
            )
            span.angle_deg = angle
            span.orientation = orientation.kind
            span.baseline_points = tuple((int(x), int(y)) for x, y in points_base)
            span.baseline = span.baseline_points
            ligne = Line(
                bbox=boite,
                spans=[span],
                hauteur_ligne_emu=hauteur_emu,
                largeur_cible_emu=max(
                    boite.largeur if abs(angle) <= 7.0 else boite.hauteur,
                    1,
                ),
                angle_deg=angle,
                orientation=orientation.kind,
                baseline_points=tuple((int(x), int(y)) for x, y in points_base),
                semantic_role=orientation.semantic_role,
                curved=orientation.curved,
                source_kind="pdf-native",
                z_index=trace.get("seqno"),
            )
            _corriger_espacement(ligne, polices)
            element = TextBox(bbox=boite, lignes=[ligne], z_index=trace.get("seqno"), source_kind="pdf-native")
            ensure_source_identity(element, getattr(page, "number", 0), source_kind="pdf-native",
                                   source_token=f"trace:{trace.get('seqno')}:{glyph_index}")
            blocs_ir.append(element)

    return blocs_ir
