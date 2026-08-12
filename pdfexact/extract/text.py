"""Extraction du texte : dictionnaire PyMuPDF vers TextBox / Line / Span.

Le découpage se fait à la ligne. Chaque ligne devient une zone de texte OOXML posée de
sorte que sa baseline retombe exactement là où le PDF l'avait mise.

Deux grandeurs gouvernent ce placement, et toutes deux viennent de la police **déclarée
dans le docx**, pas de celle du PDF : c'est avec elles que Word composera.

- Hauteur de ligne imposée : ascendante + descendante. Cette valeur exacte fait tomber la
  baseline à `ascendante` du haut de la zone.
- Sommet de la zone : baseline du PDF moins cette ascendante.
"""
from functools import lru_cache

from fontTools.agl import toUnicode
from fontTools.ttLib import TTFont

from pdfexact.extract.fonts import (
    ascendante_pt,
    descendante_pt,
    mesurer_largeur_pt,
)
from pdfexact.fontlib import normaliser_nom
from pdfexact.geometry import BBox, emu_vers_pt, pt_vers_emu, pt_vers_twips
from pdfexact.ir import FontRef, Line, Span, TextBox

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
    gras = bool(drapeaux & _BIT_GRAS) or any(
        mot in minuscule for mot in ("bold", "demi", "black", "heavy", "extrabold")
    )
    italique = bool(drapeaux & _BIT_ITALIQUE) or any(
        mot in minuscule for mot in ("italic", "oblique")
    )
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

    mesuree_pt = sum(
        mesurer_largeur_pt(span.texte, polices[span.police.font_id], span.size_pt)
        for span in ligne.spans
    )
    ecart_pt = emu_vers_pt(ligne.largeur_cible_emu) - mesuree_pt
    diviseur = caracteres if _ESPACEMENT_PAR_CARACTERE else max(caracteres - 1, 1)

    espacement = round(pt_vers_twips(ecart_pt / diviseur))
    for span in ligne.spans:
        span.espacement_twips = espacement


def _span_ir(span: dict, polices: dict) -> Span | None:
    texte = span.get("text", "")
    if not texte:
        return None

    font_id = _resoudre_police(span.get("font", ""), polices)
    asset = polices[font_id]
    drapeaux = int(span.get("flags", 0))

    gras, italique = _style_depuis_nom(span.get("font", ""), drapeaux)
    return Span(
        texte=texte,
        police=FontRef(
            font_id=font_id,
            famille=asset.famille,
            gras=gras,
            italique=italique,
        ),
        size_pt=round(float(span.get("size", 12.0)), 2),
        couleur=_couleur_hexa(span.get("color", 0)),
    )


def _ligne_ir(ligne: dict, polices: dict) -> Line | None:
    spans_ir = []
    spans_bruts = []
    for span in ligne.get("spans", []):
        converti = _span_ir(span, polices)
        if converti is not None:
            spans_ir.append(converti)
            spans_bruts.append(span)

    if not spans_ir:
        return None

    boite = _bbox_depuis_liste(ligne["bbox"])
    premier, span_brut = spans_ir[0], spans_bruts[0]
    asset = polices[premier.police.font_id]

    ascendante = ascendante_pt(asset, premier.size_pt)
    descendante = descendante_pt(asset, premier.size_pt)
    baseline_pt = float(span_brut.get("origin", (0.0, 0.0))[1])

    haut_emu = pt_vers_emu(baseline_pt - ascendante)
    hauteur_emu = max(pt_vers_emu(ascendante + descendante), 1)

    ligne_ir = Line(
        bbox=BBox(boite.x0, haut_emu, boite.x1, haut_emu + hauteur_emu),
        spans=spans_ir,
        hauteur_ligne_emu=hauteur_emu,
        largeur_cible_emu=max(boite.largeur, 1),
    )
    _corriger_espacement(ligne_ir, polices)
    return ligne_ir


def extraire_texte(page, polices: dict) -> list[TextBox]:
    """Retourne les blocs de texte de la page, en EMU."""
    blocs_ir: list[TextBox] = []

    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue

        lignes_ir = [
            converti
            for converti in (_ligne_ir(ligne, polices) for ligne in bloc.get("lines", []))
            if converti is not None
        ]
        if lignes_ir:
            blocs_ir.append(TextBox(bbox=_bbox_depuis_liste(bloc["bbox"]), lignes=lignes_ir))

    return blocs_ir


def extraire_texte_glyphes(page, polices: dict) -> list[TextBox]:
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

        for code, gid, origine, boite_pt in trace.get("chars", ()):
            texte = _texte_depuis_glyphe(code, gid, asset)
            if not texte:
                continue

            x0, _y0, x1, _y1 = boite_pt
            baseline_pt = float(origine[1])
            haut_emu = pt_vers_emu(baseline_pt - ascendante)
            boite = BBox(
                pt_vers_emu(x0),
                haut_emu,
                max(pt_vers_emu(x1), pt_vers_emu(x0) + 1),
                haut_emu + hauteur_emu,
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
            )
            ligne = Line(
                bbox=boite,
                spans=[span],
                hauteur_ligne_emu=hauteur_emu,
                largeur_cible_emu=max(boite.largeur, 1),
            )
            _corriger_espacement(ligne, polices)
            blocs_ir.append(TextBox(bbox=boite, lignes=[ligne]))

    return blocs_ir
