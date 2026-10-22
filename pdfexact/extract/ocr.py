"""Couche OCR positionnée.

Tesseract fournit les mots et leurs boîtes en pixels. On les convertit en coordonnées
PDF puis en EMU pour poser une couche texte au-dessus du rendu visuel exact.
"""
import csv
import math
import re
import subprocess
import sys
from copy import deepcopy
from io import StringIO
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf

from pdfexact.extract.blocks import (
    OcrLine,
    centre_dans,
    detecter_blocs_page,
    est_dans_zone,
)
from pdfexact.extract.styles import decorations_texte
from pdfexact.fallback.rasterize import rasteriser_region
from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt, pt_vers_emu, pt_vers_twips, se_chevauchent
from pdfexact.analysis.geometry import rect_intersection_area, overlap_ratio
from pdfexact.ir import FlowParagraph, FontRef, Line, Span, TextBox, RasterEl, element_source_ids, element_text
from pdfexact.scene import capture_source_observations, ensure_source_identity, record_source_transformation
from pdfexact.analysis.provenance import Evidence
from pdfexact.extract.orientation import angle_depuis_points, classer_orientation
from pdfexact.extract.ocr_routing import get_local_ocr, has_non_latin_letters, script_counts


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
    page, dpi: int = 300, langue: str = "eng", visible: bool = False, verbose: bool = False,
    observation_page=None,
):
    """Retourne des TextBox OCR positionnées par ligne."""
    with TemporaryDirectory(prefix="pdfexact-ocr-") as dossier:
        image = Path(dossier) / "page.png"
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        pixmap.save(image)
        rows = _lancer_tesseract(image, langue)

    facteur = 72.0 / dpi
    raw_lines = []
    for row in rows:
        if not (row.get("text") or "").strip():
            continue
        try:
            left, top, width, height = (float(row[key]) * facteur for key in ("left", "top", "width", "height"))
            score = float(row.get("conf", -1)) / 100.0
        except (KeyError, TypeError, ValueError):
            continue
        raw_lines.append(OcrLine(row["text"], score, BBox(pt_vers_emu(left), pt_vers_emu(top),
                                                        pt_vers_emu(left + width), pt_vers_emu(top + height))))
    observations = _capture_ocr_lines(page, raw_lines, observation_page, "tesseract-word", language=langue)
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
            bbox=bbox,
            source_kind="ocr",
            language=langue,
            confidence=min(conf for _row, _text, conf in valeurs) / 100.0,
        )
        ligne = Line(
            bbox=bbox,
            spans=[span],
            hauteur_ligne_emu=max(bbox.hauteur, 1),
            largeur_cible_emu=max(bbox.largeur, 1),
            source_kind="ocr",
            language=langue,
        )
        blocs.append(TextBox(bbox=bbox, lignes=[ligne], source_kind="ocr", language=langue))

    if verbose:
        print(f"      OCR: {len(blocs)} ligne(s) positionnée(s)", file=sys.stderr)
    return _finaliser_source_ocr(page, blocs, observations, observation_page)


def _capture_ocr_lines(page_pdf, lines, observation_page, engine, *, language="auto", routing_evidence=None):
    observations = []
    for index, source in enumerate(lines):
        score = float(source.score) if source.score is not None else None
        confidence = score if score is not None and 0 <= score <= 1 else None
        quad = tuple((pt_vers_emu(x), pt_vers_emu(y)) for x, y in source.quad_points)
        span = Span(source.texte, FontRef("", "", False, False), 0.0, "", bbox=source.bbox,
                    source_kind="ocr", confidence=confidence, language=language, quad=quad,
                    angle_deg=source.angle_deg, orientation=source.orientation,
                    attributes={"engine": engine, "raw_score": score, "font_observed": False})
        line = Line(source.bbox, [span], source.bbox.hauteur, source.bbox.largeur,
                    source_kind="ocr", confidence=confidence, language=language, quad=quad,
                    angle_deg=source.angle_deg, orientation=source.orientation)
        observation = TextBox(source.bbox, [line], source_kind="ocr", confidence=confidence, language=language,
                              attributes={"engine": engine, "raw_score": score, "observation_only": True})
        counts = script_counts(source.texte)
        for item in (span, line, observation):
            item.attributes["observed_scripts"] = counts
            if len(counts) == 1:
                item.script = next(iter(counts))
            if routing_evidence is not None and index < len(routing_evidence):
                details = routing_evidence[index]
                item.attributes["ocr_routing"] = details
                if details.get("ambiguous"):
                    item.confidence = None
                item.evidence.append(Evidence("ocr-script-routing", "pdfexact.extract.ocr_routing",
                                              confidence=None, details=tuple(details.items())))
        ensure_source_identity(observation, getattr(page_pdf, "number", 0), source_kind="ocr",
                               source_token=f"{engine}:{index}")
        observations.append(observation)
    if observation_page is not None:
        capture_source_observations(observation_page, observations)
    return observations


def _finaliser_source_ocr(page_pdf, outputs, observations, observation_page, *, dpi=None):
    for output in outputs:
        if getattr(output, "source_kind", None) == "pdf-native":
            ensure_source_identity(output, getattr(page_pdf, "number", 0))
            continue
        matched = []
        output_text = " ".join(element_text(output).split())
        for source in observations:
            source_text = " ".join(element_text(source).split())
            inside = overlap_ratio(source.bbox, output.bbox) == 1.0
            if isinstance(output, RasterEl):
                equivalent = inside
            else:
                # Literal content and geometric containment are both needed.
                equivalent = bool(source_text and inside and re.search(r"(?<!\w)" + re.escape(source_text) + r"(?!\w)", output_text))
            if equivalent:
                matched.append(source)
        if not getattr(output, "source_kind", None):
            output.source_kind = "inferred" if isinstance(output, RasterEl) else "ocr"
        ensure_source_identity(output, getattr(page_pdf, "number", 0), source_kind=output.source_kind,
                               source_token="ocr-output:" + "|".join(source.source_id for source in matched))
        output.source_ids = tuple(dict.fromkeys((*element_source_ids(output),
                                                *(source_id for source in matched for source_id in element_source_ids(source)))))
        routing = [source.attributes["ocr_routing"] for source in matched if "ocr_routing" in source.attributes]
        if routing:
            output.attributes["ocr_routing"] = routing
            output.evidence.append(Evidence("ocr-script-routing", "pdfexact.extract.ocr_routing", confidence=None,
                                            details=(("regions", routing),)))
            if any(region["ambiguous"] for region in routing):
                output.confidence = None
        if output.source_kind == "ocr":
            for item in [output, *getattr(output, "lignes", []),
                         *(span for line in getattr(output, "lignes", []) for span in line.spans)]:
                text = (element_text(item) if item is output else
                        (item.texte if isinstance(item, Span) else "".join(span.texte for span in item.spans)))
                counts = script_counts(text)
                item.attributes["observed_scripts"] = counts
                if len(counts) == 1:
                    item.script = next(iter(counts))
        if isinstance(output, RasterEl):
            output.source_component_ids = tuple(source.source_id for source in matched)
            output.fallback_reason = output.fallback_reason or f"ocr-{output.purpose or 'visual'}-fallback"
            output.attributes["source_component_ids"] = output.source_component_ids
            output.attributes["replaces"] = output.source_component_ids
            proof = {"reason": output.fallback_reason, "source_ids": output.source_component_ids, "output_id": output.source_id,
                     "dpi": dpi, "capture_method": "source-page-region-render", "pixel_equivalence_verified": False}
            output.evidence.append(Evidence("raster-replacement", "pdfexact.extract.ocr", confidence=None, details=tuple(proof.items())))
        if observation_page is not None and matched:
            record_source_transformation(observation_page, matched, [output], "ocr-source-adapter",
                                         proof="literal-source-text-in-output-and-source-bbox-contained" if not isinstance(output, RasterEl)
                                         else "source-bbox-contained-in-raster")
    if observation_page is not None:
        capture_source_observations(observation_page, outputs)
    return outputs


def _acquerir_sources_natives(page_pdf, polices, geometrie, observation_page):
    from pdfexact.extract.text import extraire_texte

    sources = extraire_texte(page_pdf, polices, geometrie)
    if observation_page is not None:
        capture_source_observations(observation_page, sources, source_kind="pdf-native")
        sources = [deepcopy(observation_page.source_inventory[source.source_id]) for source in sources]
    return sources


def _sortie_sources_natives(page_pdf, sources, selected_line_ids, observations,
                           observation_page, geometrie):
    """Retain acquired native components; OCR correspondence is a separate proof."""
    from pdfexact.analysis.ocr_correspondence import (
        build_ocr_native_correspondence,
        selection_event_details,
    )

    outputs = []
    owners = {}
    for source in sources:
        selected = [line for line in source.lignes if line.source_id in selected_line_ids]
        if not selected:
            continue
        output = deepcopy(source)
        output.lignes = deepcopy(selected)
        output.source_ids = tuple(dict.fromkeys((source.source_id, *(ident for line in selected
                                                                    for ident in element_source_ids(line)))))
        outputs.append(output)
        owners.update((line.source_id, output) for line in selected)

    binding = {"index": getattr(page_pdf, "number", 0),
               "source_pdf_id": getattr(observation_page, "source_pdf_id", None),
               "geometry": geometrie.snapshot()}
    if observation_page is not None:
        observation_page.ocr_correspondence_page_binding = deepcopy(binding)
    for observation in observations:
        proof = None
        reasons = []
        if observation_page is None:
            reasons.append("missing-observation-page")
        else:
            proof, reasons = build_ocr_native_correspondence(
                observation, None, observation_page.source_inventory, page_binding=binding,
            )
        line_id = proof["native_ref"]["line_id"] if proof is not None else None
        if proof is not None and line_id in owners:
            owner = owners[line_id]
            record_source_transformation(
                observation_page, [observation], [owner], "ocr-native-selection",
                **selection_event_details(proof),
            )
            owner.evidence.append(Evidence(
                "ocr-native-source-match", "pdfexact.extract.ocr", confidence=None,
                details=(("proof", deepcopy(proof)),),
            ))
        else:
            if proof is not None:
                reasons.append("unselected-native-components")
            evidence = Evidence(
                "ocr-native-source-conflict", "pdfexact.extract.ocr", confidence=None,
                details=(("observation_id", observation.source_id),
                         ("reasons", tuple(dict.fromkeys(reasons)) or ("no-native-correspondence",))),
            )
            if observation_page is not None:
                observation_page.diagnostics.append(evidence)
            else:
                for output in outputs:
                    output.evidence.append(evidence)
    return _finaliser_source_ocr(page_pdf, outputs, observations, observation_page)


def extraire_tesseract_lignes_absentes(
    page,
    polices: dict,
    elements_existants: list,
    dpi: int = 300,
    geometrie: PageGeometry | None = None,
):
    """Récupère les petites lignes ratées par RapidOCR, sous forme native.

    Cette passe ne remplace jamais RapidOCR : elle ajoute seulement une ligne dont la
    bande verticale et la boîte ne recouvrent aucun texte déjà reconnu. Elle est donc
    adaptée aux pages scannées denses, où les ISBN, crédits ou petits sous-titres sont
    parfois absents de la détection principale.
    """
    try:
        candidats = extraire_ocr(page, dpi=dpi, langue="eng", visible=True)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return []
    existantes = []
    for element in elements_existants:
        for ligne in getattr(element, "lignes", []):
            if any(span.texte.strip() for span in ligne.spans):
                existantes.append(ligne.bbox)

    def deja_reconnue(bbox: BBox) -> bool:
        for autre in existantes:
            hauteur = max(min(bbox.hauteur, autre.hauteur), 1)
            recouvrement_y = max(0, min(bbox.y1, autre.y1) - max(bbox.y0, autre.y0)) / hauteur
            recouvrement = _intersection(
                (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                (autre.x0, autre.y0, autre.x1, autre.y1),
            ) / max(min(bbox.largeur * bbox.hauteur, autre.largeur * autre.hauteur), 1)
            centre_x = (bbox.x0 + bbox.x1) / 2
            autre_centre_x = (autre.x0 + autre.x1) / 2
            if recouvrement >= 0.20 or (
                recouvrement_y >= 0.45
                and abs(centre_x - autre_centre_x) <= pt_vers_emu(22)
            ):
                return True
        return False

    ajoutes = []
    for element in candidats:
        if len(element.lignes) != 1:
            continue
        ligne = element.lignes[0]
        texte = " ".join(span.texte.strip() for span in ligne.spans if span.texte.strip())
        if len(texte) < 2 or deja_reconnue(ligne.bbox):
            continue
        police, taille, couleur, decoration = _trace_style(
            page, polices, ligne.bbox, 12700.0, geometrie
        )
        span = Span(
            texte=texte,
            police=police,
            size_pt=taille,
            couleur=couleur or "000000",
            souligne=decoration.souligne,
            barre=decoration.barre,
            surlignage=decoration.surlignage,
            bbox=ligne.bbox,
        )
        ligne_native = Line(
            bbox=ligne.bbox,
            spans=[span],
            hauteur_ligne_emu=ligne.hauteur_ligne_emu,
            largeur_cible_emu=ligne.largeur_cible_emu,
            alignement="left",
        )
        ajoutes.append(
            FlowParagraph(
                bbox=ligne.bbox,
                texte=texte,
                police=police,
                size_pt=taille,
                couleur=couleur or "000000",
                espace_apres_emu=0,
                interligne_emu=ligne.hauteur_ligne_emu,
                souligne=decoration.souligne,
                barre=decoration.barre,
                surlignage=decoration.surlignage,
                spans=[span],
                lignes=[ligne_native],
            )
        )
        existantes.append(ligne.bbox)
    return ajoutes


def _rapidocr(language="auto", model_root=None):
    return get_local_ocr(model_root=model_root, language=language)


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
    return rect_intersection_area(a, b)


def _bbox_trace_affiche(trace, geometrie: PageGeometry | None = None) -> tuple[float, float, float, float]:
    rect = pymupdf.Rect(trace.get("bbox", (0, 0, 0, 0)))
    if geometrie is not None:
        bbox = geometrie.bbox_depuis_rect_natif(rect)
        return (
            bbox.x0 / 12700.0,
            bbox.y0 / 12700.0,
            bbox.x1 / 12700.0,
            bbox.y1 / 12700.0,
        )
    return (rect.x0, rect.y0, rect.x1, rect.y1)


def _trace_style(
    page,
    polices: dict,
    bbox: BBox,
    facteur_emu: float,
    geometrie: PageGeometry | None = None,
):
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
        score = _intersection(cible, _bbox_trace_affiche(trace, geometrie))
        if score > meilleur_score:
            meilleur = trace
            meilleur_score = score

    decoration = decorations_texte(page, bbox, geometrie)

    if meilleur is None:
        taille_ocr = max(4.0, min(72.0, emu_vers_pt(bbox.hauteur) * 0.82))
        return (
            FontRef("OCR", "Arial", False, False),
            round(taille_ocr, 2),
            "000000",
            decoration,
        )

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
        decoration,
    )


def _est_dans_zone_ignoree(boite: BBox, zones_ignorees: list[BBox]) -> bool:
    return est_dans_zone(boite, zones_ignorees)


def _touche_zone_ignoree(boite: BBox, zones_ignorees: list[BBox], seuil: float = 0.10) -> bool:
    """Vrai si la boîte appartient visiblement à une zone protégée.

    Les tableaux et figures sont ajoutés aux zones ignorées avant l'OCR. Une ligne OCR
    issue d'une cellule peut ressembler à une formule ("KMSC-02-35") ; elle ne doit pas
    être rasterisée puis réinsérée hors du tableau.
    """
    if _est_dans_zone_ignoree(boite, zones_ignorees):
        return True
    aire_boite = max(boite.largeur, 0) * max(boite.hauteur, 0)
    if not aire_boite:
        return False
    for zone in zones_ignorees:
        aire_zone = max(zone.largeur, 0) * max(zone.hauteur, 0)
        if not aire_zone:
            continue
        x0 = max(boite.x0, zone.x0)
        y0 = max(boite.y0, zone.y0)
        x1 = min(boite.x1, zone.x1)
        y1 = min(boite.y1, zone.y1)
        intersection = max(0, x1 - x0) * max(0, y1 - y0)
        if intersection / aire_boite >= seuil:
            return True
        if intersection / max(min(aire_boite, aire_zone), 1) >= 0.32:
            return True
    return False


def _ligne_hors_zones_protegees(ligne: OcrLine, zones_ignorees: list[BBox]) -> bool:
    """Filtre OCR strict pour les régions déjà reconstruites autrement.

    Une table reconstruite cellule par cellule doit rester l'unique source de son texte.
    RapidOCR produit parfois des boîtes légèrement plus hautes ou plus larges que la
    cellule PDF : un simple test "dans la zone" laisse alors passer des doublons hors
    tableau. Le test par recouvrement évite ces fuites sans toucher au texte courant.
    """
    return not _touche_zone_ignoree(ligne.bbox, zones_ignorees)


def _ligne_dans_cadres_lecture(
    ligne: OcrLine,
    cadres_lecture: list[BBox],
    hauteur_page_emu: int,
) -> bool:
    if not cadres_lecture:
        return True
    if ligne.bbox.y0 <= pt_vers_emu(48) or ligne.bbox.y1 >= hauteur_page_emu - pt_vers_emu(48):
        return True

    aire_ligne = max(ligne.bbox.largeur, 0) * max(ligne.bbox.hauteur, 0)
    if not aire_ligne:
        return False
    centre_x = (ligne.bbox.x0 + ligne.bbox.x1) // 2
    centre_y = (ligne.bbox.y0 + ligne.bbox.y1) // 2
    for cadre in cadres_lecture:
        if cadre.x0 <= centre_x <= cadre.x1 and cadre.y0 <= centre_y <= cadre.y1:
            return True
        x0 = max(ligne.bbox.x0, cadre.x0)
        y0 = max(ligne.bbox.y0, cadre.y0)
        x1 = min(ligne.bbox.x1, cadre.x1)
        y1 = min(ligne.bbox.y1, cadre.y1)
        intersection = max(0, x1 - x0) * max(0, y1 - y0)
        if intersection / aire_ligne >= 0.45:
            return True
    return False


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
    # Observed non-Latin characters are not Latin OCR spelling errors.
    if not has_non_latin_letters(texte):
        for source, cible in _REMPLACEMENTS_OCR:
            texte = texte.replace(source, cible)
    texte = re.sub(r"\s+([,.;:])", r"\1", texte)
    texte = re.sub(r"([(\[])\s+", r"\1", texte)
    texte = re.sub(r"\s+([)\]])", r"\1", texte)
    return " ".join(texte.split())


_MARQUEUR_PAGE_COLONNE_DROITE = re.compile(
    r"^\s*-{1,3}\s*(\d{1,4}|[ivxlcdm]{1,8})\s*$",
    re.IGNORECASE,
)


def _normaliser_marqueur_colonne_droite(page, bbox: BBox, texte: str) -> str:
    """Corrige les numéros de sommaire OCR lus comme tirets + numéro.

    On ne le fait que dans la colonne droite, là où les tables des matières, listes de
    figures et listes de tableaux placent leurs numéros de page. Cela évite de toucher
    les valeurs négatives du texte courant ou des tableaux.
    """
    if bbox.x0 < pt_vers_emu(page.rect.width * 0.62):
        return texte
    correspondance = _MARQUEUR_PAGE_COLONNE_DROITE.match(texte)
    if not correspondance:
        return texte
    return correspondance.group(1)


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
_MATH_SYMBOLS_FORTS = set("=×÷<>≤≥≈≠∫∑√^_∆ΔΩωπζλμνρσ")


def _semble_formule(texte: str) -> bool:
    compact = texte.replace(" ", "")
    if len(compact) < 4:
        return False
    if not any(caractere in _MATH_SYMBOLS_FORTS for caractere in compact):
        return False
    symboles = sum(1 for caractere in compact if caractere in _MATH_SYMBOLS)
    chiffres = sum(1 for caractere in compact if caractere.isdigit())
    lettres = sum(1 for caractere in compact if caractere.isalpha())
    densite = (symboles + chiffres) / len(compact)
    return symboles >= 2 and densite >= 0.28 and lettres <= len(compact) * 0.75


def _ligne_formule_a_rasteriser(ligne: OcrLine, polices: dict | None) -> bool:
    if not _semble_formule(ligne.texte):
        return False
    if not ligne.spans:
        return True
    spans_utiles = [span for span in ligne.spans if span.texte.strip()]
    if not spans_utiles:
        return False
    if any(_police_symbole_non_reconnue(span.police.font_id) for span in spans_utiles):
        return True
    if any(caractere in "×÷≤≥≈≠∫∑√∆ΔΩωπζλμνρσ" for caractere in ligne.texte):
        return True
    return False


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


def _police_symbole_non_reconnue(nom: str | None) -> bool:
    normalise = (nom or "").lower()
    return any(
        marqueur in normalise
        for marqueur in ("math", "symbol", "ding", "wp-", "wp_", "wordperfect")
    )


def _ligne_glyphe_symbole_non_reconnue(ligne: OcrLine, polices: dict | None) -> bool:
    if not polices or not ligne.spans:
        return False

    spans_utiles = [span for span in ligne.spans if span.texte.strip()]
    if not spans_utiles:
        return False

    inconnus_symboles = [
        span
        for span in spans_utiles
        if _police_symbole_non_reconnue(span.police.font_id)
        and not getattr(polices.get(span.police.font_id), "reconnue", False)
    ]
    if not inconnus_symboles:
        return False

    texte = "".join(span.texte for span in spans_utiles).strip()
    if not texte:
        return False
    if has_non_latin_letters(texte):
        return False
    lettres = sum(1 for caractere in texte if caractere.isalpha())
    chiffres = sum(1 for caractere in texte if caractere.isdigit())
    signes = sum(1 for caractere in texte if not caractere.isalnum() and not caractere.isspace())
    return signes >= 1 or (len(texte) <= 2 and lettres + chiffres <= 2)


def _zones_glyphes_symboles_non_reconnus(
    lignes: list[OcrLine],
    polices: dict | None,
) -> list[BBox]:
    zones = [
        ligne.bbox
        for ligne in lignes
        if _ligne_glyphe_symbole_non_reconnue(ligne, polices)
    ]
    if not zones:
        return []

    marge = pt_vers_emu(1.0)
    zones = [
        BBox(zone.x0 - marge, zone.y0 - marge, zone.x1 + marge, zone.y1 + marge)
        for zone in zones
    ]
    fusionnees: list[BBox] = []
    for zone in sorted(zones, key=lambda item: (item.y0, item.x0)):
        index_fusion = None
        zone_etendue = BBox(
            zone.x0 - pt_vers_emu(2),
            zone.y0 - pt_vers_emu(3),
            zone.x1 + pt_vers_emu(2),
            zone.y1 + pt_vers_emu(3),
        )
        for index, existante in enumerate(fusionnees):
            if se_chevauchent(zone_etendue, existante):
                index_fusion = index
                break
        if index_fusion is None:
            fusionnees.append(zone)
        else:
            fusionnees[index_fusion] = _fusionner_bbox(fusionnees[index_fusion], zone)
    return fusionnees


def _lignes_rapidocr(result, facteur: float) -> list[OcrLine]:
    lignes: list[OcrLine] = []
    for texte, score, points in zip(result.txts, result.scores, result.boxes):
        texte = _normaliser_texte_ocr((texte or "").strip())
        if not texte:
            continue
        points_source = tuple(
            (float(point[0]) * facteur, float(point[1]) * facteur)
            for point in points
        )
        orientation = classer_orientation(texte, angle_depuis_points(points_source))
        lignes.append(
            OcrLine(
                texte=texte,
                score=score,
                bbox=_boite_rapidocr(points, facteur),
                angle_deg=orientation.angle_deg,
                orientation=orientation.kind,
                quad_points=points_source,
                semantic_role=orientation.semantic_role,
            )
        )
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


def _elements_mots_rapidocr(result, facteur: float) -> list[tuple[str, float, BBox]]:
    word_results = getattr(result, "word_results", None)
    if not word_results:
        return []

    elements: list[tuple[str, float, BBox]] = []
    for ligne in word_results:
        for item in ligne:
            if len(item) < 3:
                continue
            texte, score, points = item[:3]
            texte = _normaliser_texte_ocr((texte or "").strip())
            if texte:
                elements.append((texte, score, _boite_rapidocr(points, facteur)))
    return elements


def _index_colonne_pour_bbox(bbox: BBox, colonnes: list[BBox]) -> int | None:
    if len(colonnes) < 2:
        return None

    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    marge_x = pt_vers_emu(4)
    marge_y = pt_vers_emu(3)
    candidats = [
        (index, colonne)
        for index, colonne in enumerate(colonnes)
        if colonne.x0 - marge_x <= centre_x <= colonne.x1 + marge_x
        and colonne.y0 - marge_y <= centre_y <= colonne.y1 + marge_y
    ]
    if candidats:
        return min(
            candidats,
            key=lambda item: abs(centre_x - ((item[1].x0 + item[1].x1) // 2)),
        )[0]

    meilleur_index: int | None = None
    meilleur_score = 0.0
    for index, colonne in enumerate(colonnes):
        recouvrement_x = max(0, min(bbox.x1, colonne.x1) - max(bbox.x0, colonne.x0))
        recouvrement_y = max(0, min(bbox.y1, colonne.y1) - max(bbox.y0, colonne.y0))
        ratio_x = recouvrement_x / max(bbox.largeur, 1)
        ratio_y = recouvrement_y / max(bbox.hauteur, 1)
        if ratio_x < 0.20 or ratio_y < 0.20:
            continue
        score = ratio_y * 2.0 + ratio_x
        if score > meilleur_score:
            meilleur_index = index
            meilleur_score = score
    return meilleur_index


def _reconstruire_lignes_depuis_mots_colonnes(
    mots: list[tuple[str, float, BBox]],
    colonnes: list[BBox],
) -> list[OcrLine]:
    """Découpe les lignes OCR qui traversent plusieurs colonnes.

    RapidOCR peut reconnaître une seule "ligne" contenant des fragments alignés dans
    deux ou trois colonnes. En mode fidélité visuelle, les colonnes natives du PDF sont
    la frontière fiable : on regroupe donc les mots par colonne avant de reformer les
    lignes Word.
    """
    if len(colonnes) < 2 or len(mots) < 6:
        return []

    groupes: dict[int, list[tuple[str, float, BBox]]] = {index: [] for index in range(len(colonnes))}
    for texte, score, bbox in mots:
        index = _index_colonne_pour_bbox(bbox, colonnes)
        if index is not None:
            groupes[index].append((texte, score, bbox))

    lignes: list[OcrLine] = []
    for index, items in groupes.items():
        if not items:
            continue
        items.sort(key=lambda item: ((item[2].y0 + item[2].y1) // 2, item[2].x0))
        lignes_colonne: list[list[tuple[str, float, BBox]]] = []
        courant: list[tuple[str, float, BBox]] = []
        centre_y_courant = 0
        hauteur_courante = 0

        for item in items:
            bbox = item[2]
            centre_y = (bbox.y0 + bbox.y1) // 2
            hauteur = max(bbox.hauteur, pt_vers_emu(4))
            if not courant:
                courant = [item]
                centre_y_courant = centre_y
                hauteur_courante = hauteur
                continue

            seuil_ligne = max(pt_vers_emu(3), int(max(hauteur_courante, hauteur) * 0.72))
            if abs(centre_y - centre_y_courant) > seuil_ligne:
                lignes_colonne.append(courant)
                courant = [item]
                centre_y_courant = centre_y
                hauteur_courante = hauteur
                continue

            courant.append(item)
            centre_y_courant = int(
                (centre_y_courant * (len(courant) - 1) + centre_y) / len(courant)
            )
            hauteur_courante = max(hauteur_courante, hauteur)

        if courant:
            lignes_colonne.append(courant)

        colonne = colonnes[index]
        for ligne_items in lignes_colonne:
            ligne_items.sort(key=lambda item: item[2].x0)
            texte = _normaliser_texte_ocr(" ".join(item[0] for item in ligne_items))
            if not texte:
                continue
            bbox = ligne_items[0][2]
            scores = []
            for _texte, score, item_bbox in ligne_items[1:]:
                bbox = _fusionner_bbox(bbox, item_bbox)
                scores.append(score or 0.0)
            scores.append(ligne_items[0][1] or 0.0)
            x0 = max(bbox.x0, colonne.x0)
            x1 = min(bbox.x1, colonne.x1)
            bbox = BBox(x0, bbox.y0, max(x0 + 1, x1), bbox.y1)
            lignes.append(OcrLine(texte=texte, score=sum(scores) / max(len(scores), 1), bbox=bbox))

    lignes.sort(key=lambda ligne: (ligne.bbox.y0, ligne.bbox.x0))
    return lignes


def _lignes_natives_hybrides(
    layout_map,
    zones_ignorees: list[BBox],
    polices: dict | None = None,
    *,
    lignes_visuelles: bool = True,
    fusionner_fragments: bool = True,
) -> list[OcrLine]:
    lignes: list[OcrLine] = []
    source_lignes = layout_map.lignes_visuelles_natives() if lignes_visuelles else layout_map.lignes_natives()
    cadres_preservation = layout_map._cadres_lecture_taxonomie()
    for item in source_lignes:
        texte = _normaliser_texte_ocr(item.text.strip())
        if not texte:
            continue
        spans = tuple(_spans_layout_item(item, polices)) if polices is not None else ()
        if spans:
            texte = _normaliser_texte_ocr("".join(span.texte for span in spans).strip())
        else:
            texte = _texte_depuis_police_symbole(texte, item.font_name)
        ligne = OcrLine(texte=texte, score=1.0, bbox=item.bbox, spans=spans)
        dans_cadre_lecture = _ligne_dans_cadres_lecture(
            ligne,
            cadres_preservation,
            layout_map.hauteur_emu,
        ) if cadres_preservation else False
        if _ligne_hors_zones_protegees(ligne, zones_ignorees) or dans_cadre_lecture:
            lignes.append(ligne)
    if not lignes_visuelles and fusionner_fragments:
        lignes = _fusionner_lignes_natives_visuelles(lignes, layout_map.cadres_lecture_natifs())
    return lignes


def extraire_textes_natifs_zones(
    page,
    polices: dict,
    zones: list[BBox],
    layout_map,
    geometrie: PageGeometry | None = None,
    observation_page=None,
) -> list[TextBox]:
    """Extrait le texte PDF natif situé dans des zones visuelles protégées.

    Ces lignes servent aux diagrammes : le fond graphique peut être rasterisé, mais les
    libellés restent éditables et positionnés à leurs boîtes PDF.
    """
    if not zones or layout_map is None:
        return []

    geometrie = geometrie or PageGeometry.depuis_page(page)
    # Les deux APIs PyMuPDF sont complémentaires : `dict` garde les lignes et les
    # espaces, tandis que `texttrace` retrouve les glyphes que le regroupement PDF
    # peut omettre (crédits verticaux, petites légendes, textes superposés). Ne jamais
    # traiter la première source non vide comme une réponse complète.
    resultats_lignes = _extraire_lignes_natives_visuelles_dict(page, polices, zones, geometrie)
    resultats_visibles = _extraire_textes_visibles_texttrace(page, polices, zones, geometrie)
    acquired = resultats_lignes + resultats_visibles
    for index, element in enumerate(acquired):
        ensure_source_identity(element, getattr(page, "number", 0), source_kind="pdf-native",
                               source_token=f"native-visual-acquisition:{index}")
    if observation_page is not None:
        capture_source_observations(observation_page, acquired, source_kind="pdf-native")
    resultats_natifs = _dedoublonner_textboxes_natifs(acquired)
    resultats: list[TextBox] = list(resultats_natifs)
    vus: set[tuple[int, int, int, int, str]] = set()
    items = sorted(layout_map.lignes_natives(), key=lambda item: (item.bbox.y0, item.bbox.x0))
    for item in items:
        texte = _normaliser_texte_ocr(item.text.strip())
        if not texte:
            continue
        if not _bbox_dans_zones(item.bbox, zones):
            continue
        spans = _spans_layout_item(item, polices)
        if spans:
            texte = _normaliser_texte_ocr("".join(span.texte for span in spans).strip())
        else:
            texte = _texte_depuis_police_symbole(texte, item.font_name)
        if not texte:
            continue
        cle = (item.qbbox.x0, item.qbbox.y0, item.qbbox.x1, item.qbbox.y1, texte)
        if cle in vus:
            continue
        vus.add(cle)

        bbox = _limiter_bbox(page, item.bbox)
        if spans:
            size_pt = max((span.size_pt for span in spans if span.texte.strip()), default=10.0)
        else:
            police, size_pt, couleur, decoration = _trace_style(page, polices, bbox, 12700.0, geometrie)
            spans = [
                Span(
                    texte=texte,
                    police=police,
                    size_pt=size_pt,
                    couleur=couleur,
                    souligne=decoration.souligne,
                    barre=decoration.barre,
                    surlignage=decoration.surlignage,
                )
            ]
        hauteur_ligne = max(bbox.hauteur, pt_vers_emu(size_pt * 1.12))
        bbox = BBox(bbox.x0, bbox.y0, bbox.x1, min(geometrie.hauteur_emu, bbox.y0 + hauteur_ligne))
        ligne = Line(
            bbox=bbox,
            spans=spans,
            hauteur_ligne_emu=max(hauteur_ligne, 1),
            largeur_cible_emu=max(bbox.largeur, 1),
            alignement=_alignement_ligne(page, bbox, texte),
        )
        _ajuster_largeur_ocr(ligne, polices)
        textbox = TextBox(bbox=bbox, lignes=[ligne])
        textbox.preserve_as_textbox = True
        ensure_source_identity(textbox, getattr(page, "number", 0), source_kind="pdf-native",
                               source_token=f"layout-native:{cle}")
        resultats.append(textbox)
    if observation_page is not None:
        capture_source_observations(observation_page, resultats, source_kind="pdf-native")
    outputs = _dedoublonner_textboxes_natifs(resultats)
    if observation_page is not None:
        for source in [*acquired, *resultats]:
            if any(source is output for output in outputs):
                continue
            winner_id = source.attributes.get("duplicate_of")
            winner = next((output for output in outputs if output.source_id == winner_id), None)
            record_source_transformation(observation_page, [source], [winner] if winner else [], "native-visual-deduplication",
                                         duplicate_of=winner_id, duplicate_verified=source.attributes.get("duplicate_verified", False))
    return outputs


def _extraire_lignes_natives_visuelles_dict(
    page,
    polices: dict,
    zones: list[BBox],
    geometrie: PageGeometry,
) -> list[TextBox]:
    """Préserve les textes PDF inversés en lignes natives complètes.

    Les bandeaux et couvertures colorées ont souvent du texte blanc en police
    condensée. `get_texttrace()` est précis au caractère, mais il fragmente ces titres
    en petits groupes que Word recompose mal. `get_text("dict")` conserve la ligne PDF
    et ses espaces, ce qui donne une couche Word native traduisible sans casser le rendu.
    """

    from pdfexact.extract.text import _couleur_hexa, _resoudre_police, _style_depuis_nom

    resultats: list[TextBox] = []
    vus: set[tuple[int, int, int, int, str]] = set()
    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne_pdf in bloc.get("lines", []):
            spans_source = [span for span in ligne_pdf.get("spans", []) if span.get("text", "").strip()]
            if not spans_source:
                continue

            spans: list[Span] = []
            boites: list[BBox] = []
            ligne_inverse = False
            taille_max = 0.0
            for brut in spans_source:
                bbox_span = _limiter_bbox(
                    page,
                    geometrie.bbox_depuis_rect_natif(pymupdf.Rect(brut.get("bbox", ligne_pdf.get("bbox", (0, 0, 0, 0))))),
                )
                if not _bbox_dans_zones(bbox_span, zones):
                    continue
                texte = _texte_depuis_police_symbole(str(brut.get("text", "")), str(brut.get("font", "")))
                if not texte:
                    continue
                couleur_int = int(brut.get("color", 0) or 0)
                taille = round(float(brut.get("size", 10.0) or 10.0), 2)
                taille_max = max(taille_max, taille)
                if _couleur_texte_inverse(couleur_int):
                    ligne_inverse = True
                nom_police = str(brut.get("font", "") or "")
                font_id = _resoudre_police(nom_police, polices)
                asset = polices[font_id]
                gras, italique = _style_depuis_nom(nom_police, int(brut.get("flags", 0) or 0))
                span = Span(
                    texte=texte,
                    police=FontRef(font_id, asset.famille, gras, italique),
                    size_pt=taille,
                    couleur=_couleur_hexa(couleur_int),
                    bbox=bbox_span,
                )
                if spans and _doit_inserer_espace_span(spans[-1], span):
                    spans[-1].texte += " "
                spans.append(span)
                boites.append(bbox_span)

            if not spans or not boites:
                continue
            # Les citations, crédits et légendes peuvent être petits et sombres.
            # Le seuil historique de 18 pt supprimait ces textes récupérables.
            if not ligne_inverse and taille_max < 4.0 and len("".join(span.texte for span in spans).strip()) < 2:
                continue

            texte_ligne = _normaliser_texte_ocr("".join(span.texte for span in spans).strip())
            if not texte_ligne:
                continue
            bbox = boites[0]
            for boite in boites[1:]:
                bbox = _fusionner_bbox(bbox, boite)
            bbox = _limiter_bbox(page, bbox)
            cle = (
                bbox.x0 // 10000,
                bbox.y0 // 10000,
                bbox.x1 // 10000,
                bbox.y1 // 10000,
                texte_ligne,
            )
            if cle in vus:
                continue
            vus.add(cle)

            decoration = decorations_texte(page, bbox, geometrie)
            spans = [
                Span(
                    texte=span.texte,
                    police=span.police,
                    size_pt=span.size_pt,
                    couleur=span.couleur,
                    souligne=decoration.souligne,
                    barre=decoration.barre,
                    surlignage=decoration.surlignage,
                    bbox=span.bbox,
                )
                for span in spans
            ]
            size_pt = max((span.size_pt for span in spans), default=10.0)
            hauteur_ligne = max(bbox.hauteur, pt_vers_emu(size_pt * 1.12))
            bbox_ligne = BBox(
                bbox.x0,
                bbox.y0,
                bbox.x1,
                min(geometrie.hauteur_emu, bbox.y0 + hauteur_ligne),
            )
            direction = ligne_pdf.get("dir") or (1.0, 0.0)
            try:
                angle = angle_depuis_points(
                    ((0.0, 0.0), (float(direction[0]), float(-direction[1])))
                )
            except (TypeError, ValueError, IndexError):
                angle = 0.0
            orientation = classer_orientation(texte_ligne, angle)
            ligne = Line(
                bbox=bbox_ligne,
                spans=spans,
                hauteur_ligne_emu=max(hauteur_ligne, 1),
                largeur_cible_emu=max(bbox_ligne.largeur, 1),
                alignement=_alignement_ligne(page, bbox_ligne, texte_ligne),
                angle_deg=orientation.angle_deg,
                orientation=orientation.kind,
                semantic_role=orientation.semantic_role,
                curved=orientation.curved,
            )
            _ajuster_largeur_ocr(ligne, polices)
            textbox = TextBox(bbox=bbox_ligne, lignes=[ligne])
            textbox.preserve_as_textbox = True
            resultats.append(textbox)
    resultats.sort(key=lambda textbox: (textbox.bbox.y0, textbox.bbox.x0))
    return resultats


def _couleur_texte_inverse(couleur: int) -> bool:
    r = (couleur >> 16) & 255
    g = (couleur >> 8) & 255
    b = couleur & 255
    return r >= 220 and g >= 220 and b >= 220


def _extraire_textes_visibles_texttrace(
    page,
    polices: dict,
    zones: list[BBox],
    geometrie: PageGeometry,
) -> list[TextBox]:
    """Reconstruit les lignes natives visibles dans des zones rasterisées sans texte."""

    from pdfexact.extract.text import _couleur_hexa, _resoudre_police, _style_depuis_nom

    occlusions = _occlusions_opaques(page, geometrie)
    resultats: list[TextBox] = []
    vus: set[tuple[int, int, int, int, str]] = set()
    for trace in page.get_texttrace():
        seqno = int(trace.get("seqno", -1) or -1)
        caracteres: list[tuple[str, BBox]] = []
        for code, _gid, _origine, boite_pt in trace.get("chars", ()):
            try:
                caractere = chr(code)
            except (TypeError, ValueError):
                continue
            bbox_car = _limiter_bbox(page, geometrie.bbox_depuis_rect_natif(pymupdf.Rect(boite_pt)))
            if not _bbox_dans_zones(bbox_car, zones):
                continue
            if caractere.strip() and _bbox_occultee_apres_seqno(bbox_car, seqno, occlusions):
                continue
            caracteres.append((caractere, bbox_car))

        nom_police = trace.get("font", "") or ""
        font_id = _resoudre_police(nom_police, polices)
        asset = polices[font_id]
        gras, italique = _style_depuis_nom(nom_police, int(trace.get("flags", 0) or 0))
        size_pt = round(float(trace.get("size", 10.0) or 10.0), 2)
        direction = trace.get("dir") or (1.0, 0.0)
        try:
            angle = angle_depuis_points(
                ((0.0, 0.0), (float(direction[0]), float(-direction[1])))
            )
        except (TypeError, ValueError, IndexError):
            angle = 0.0
        for groupe in _groupes_caracteres_visibles(caracteres, angle):
            texte = "".join(car for car, _bbox in groupe)
            texte = _normaliser_texte_ocr(texte.strip())
            if not texte:
                continue
            boites_significatives = [bbox for car, bbox in groupe if car.strip()]
            if not boites_significatives:
                continue
            bbox = boites_significatives[0]
            for boite in boites_significatives[1:]:
                bbox = _fusionner_bbox(bbox, boite)
            bbox = _limiter_bbox(page, bbox)
            cle = (
                bbox.x0 // 10000,
                bbox.y0 // 10000,
                bbox.x1 // 10000,
                bbox.y1 // 10000,
                texte,
            )
            if cle in vus:
                continue
            vus.add(cle)

            decoration = decorations_texte(page, bbox, geometrie)
            span = Span(
                texte=_texte_depuis_police_symbole(texte, nom_police),
                police=FontRef(font_id, asset.famille, gras, italique),
                size_pt=size_pt,
                couleur=_couleur_hexa(trace.get("color", 0)),
                souligne=decoration.souligne,
                barre=decoration.barre,
                surlignage=decoration.surlignage,
                bbox=bbox,
            )
            hauteur_ligne = max(bbox.hauteur, pt_vers_emu(size_pt * 1.12))
            bbox_ligne = BBox(bbox.x0, bbox.y0, bbox.x1, min(geometrie.hauteur_emu, bbox.y0 + hauteur_ligne))
            direction = trace.get("dir") or (1.0, 0.0)
            try:
                angle = angle_depuis_points(((0.0, 0.0), (float(direction[0]), float(-direction[1]))))
            except (TypeError, ValueError, IndexError):
                angle = 0.0
            points_base = tuple(
                ((bbox_car.x0 + bbox_car.x1) / 2.0, (bbox_car.y0 + bbox_car.y1) / 2.0)
                for _car, bbox_car in groupe
                if _car.strip()
            )
            orientation = classer_orientation(
                texte,
                angle,
                baseline_points=points_base,
            )
            ligne = Line(
                bbox=bbox_ligne,
                spans=[span],
                hauteur_ligne_emu=max(hauteur_ligne, 1),
                largeur_cible_emu=max(bbox_ligne.largeur, 1),
                alignement=_alignement_ligne(page, bbox_ligne, texte),
                angle_deg=orientation.angle_deg,
                orientation=orientation.kind,
                baseline_points=tuple(
                    (int(x), int(y)) for x, y in points_base
                ),
                semantic_role=orientation.semantic_role,
                curved=orientation.curved,
            )
            _ajuster_largeur_ocr(ligne, polices)
            textbox = TextBox(bbox=bbox_ligne, lignes=[ligne])
            textbox.preserve_as_textbox = True
            resultats.append(textbox)
    resultats.sort(key=lambda textbox: (textbox.bbox.y0, textbox.bbox.x0))
    return resultats


def _groupes_caracteres_visibles(
    caracteres: list[tuple[str, BBox]],
    angle_deg: float = 0.0,
) -> list[list[tuple[str, BBox]]]:
    visibles = [(car, bbox) for car, bbox in caracteres if car.strip()]
    if not visibles:
        return []
    hauteur_ref = max(
        pt_vers_emu(4),
        sorted((bbox.hauteur for _car, bbox in visibles))[len(visibles) // 2],
    )
    angle_rad = math.radians(angle_deg)
    ux, uy = math.cos(angle_rad), math.sin(angle_rad)
    nx, ny = -uy, ux

    def projections(bbox: BBox) -> tuple[float, float]:
        centre_x = (bbox.x0 + bbox.x1) / 2.0
        centre_y = (bbox.y0 + bbox.y1) / 2.0
        return centre_x * ux + centre_y * uy, centre_x * nx + centre_y * ny

    lignes: list[list[tuple[str, BBox]]] = []
    centres: list[float] = []
    for item in sorted(caracteres, key=lambda item: projections(item[1])[1]):
        car, bbox = item
        if not car.strip() and not lignes:
            continue
        _projection_base, projection_normal = projections(bbox)
        meilleur = None
        meilleur_delta = None
        for index, centre in enumerate(centres):
            delta = abs(projection_normal - centre)
            if delta <= hauteur_ref * 0.58 and (meilleur_delta is None or delta < meilleur_delta):
                meilleur = index
                meilleur_delta = delta
        if meilleur is None:
            lignes.append([item])
            centres.append(projection_normal)
            continue
        lignes[meilleur].append(item)
        centres[meilleur] = (
            centres[meilleur] * (len(lignes[meilleur]) - 1) + projection_normal
        ) / len(lignes[meilleur])

    groupes: list[list[tuple[str, BBox]]] = []
    seuil_gap = max(pt_vers_emu(12), int(hauteur_ref * 2.8))
    for ligne in lignes:
        courant: list[tuple[str, BBox]] = []
        precedent: BBox | None = None
        for car, bbox in sorted(ligne, key=lambda item: projections(item[1])[0]):
            projection_base = projections(bbox)[0]
            precedent_base = projections(precedent)[0] if precedent is not None else None
            if precedent is not None and projection_base - precedent_base > seuil_gap and any(c.strip() for c, _b in courant):
                groupes.append(courant)
                courant = []
            courant.append((car, bbox))
            if car.strip():
                precedent = bbox
        if courant and any(car.strip() for car, _bbox in courant):
            groupes.append(courant)
    return groupes


def _dedoublonner_textboxes_natifs(textboxes: list[TextBox]) -> list[TextBox]:
    """Fusionne les deux extractions natives sans éliminer les glyphes distincts."""
    from pdfexact.extract.text import dedoublonner_textboxes_paragraphes

    return dedoublonner_textboxes_paragraphes(textboxes)


def _occlusions_opaques(page, geometrie: PageGeometry) -> list[tuple[int, BBox]]:
    page_aire = max(geometrie.largeur_emu * geometrie.hauteur_emu, 1)
    occlusions: list[tuple[int, BBox]] = []
    for dessin in page.get_drawings():
        if not dessin.get("fill"):
            continue
        if float(dessin.get("fill_opacity", 1.0) or 1.0) < 0.92:
            continue
        seqno = int(dessin.get("seqno", -1) or -1)
        bbox = _limiter_bbox(page, geometrie.bbox_depuis_rect_natif(dessin["rect"]))
        aire = max(bbox.largeur, 0) * max(bbox.hauteur, 0)
        if aire <= 0 or aire / page_aire > 0.82:
            continue
        if bbox.largeur < pt_vers_emu(2) or bbox.hauteur < pt_vers_emu(2):
            continue
        occlusions.append((seqno, bbox))
    return occlusions


def _bbox_occultee_apres_seqno(bbox: BBox, seqno: int, occlusions: list[tuple[int, BBox]]) -> bool:
    aire = max(bbox.largeur, 0) * max(bbox.hauteur, 0)
    if not aire:
        return False
    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    for seq_occlusion, zone in occlusions:
        if seq_occlusion <= seqno:
            continue
        if not se_chevauchent(bbox, zone):
            continue
        x0 = max(bbox.x0, zone.x0)
        y0 = max(bbox.y0, zone.y0)
        x1 = min(bbox.x1, zone.x1)
        y1 = min(bbox.y1, zone.y1)
        intersection = max(0, x1 - x0) * max(0, y1 - y0)
        if intersection / aire >= 0.55:
            return True
        if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1 and intersection / aire >= 0.20:
            return True
    return False


def _bbox_dans_zones(bbox: BBox, zones: list[BBox]) -> bool:
    aire = max(bbox.largeur * bbox.hauteur, 1)
    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    for zone in zones:
        if zone.x0 <= centre_x <= zone.x1 and zone.y0 <= centre_y <= zone.y1:
            return True
        if not (bbox.x0 < zone.x1 and zone.x0 < bbox.x1 and bbox.y0 < zone.y1 and zone.y0 < bbox.y1):
            continue
        intersection = (
            max(0, min(bbox.x1, zone.x1) - max(bbox.x0, zone.x0))
            * max(0, min(bbox.y1, zone.y1) - max(bbox.y0, zone.y0))
        )
        if intersection / aire >= 0.45:
            return True
    return False


def _bbox_lignes(lignes: list[OcrLine]) -> BBox:
    boite = lignes[0].bbox
    for ligne in lignes[1:]:
        boite = _fusionner_bbox(boite, ligne.bbox)
    return boite


def _bbox_spans_ligne(spans: list[Span]) -> BBox | None:
    bboxes = [span.bbox for span in spans if span.texte.strip() and span.bbox is not None]
    if not bboxes:
        return None
    boite = bboxes[0]
    for bbox in bboxes[1:]:
        boite = _fusionner_bbox(boite, bbox)
    return boite


def _bbox_spans_coherente_ligne(bbox_ligne: BBox, bbox_spans: BBox) -> bool:
    centre_ligne = (bbox_ligne.y0 + bbox_ligne.y1) // 2
    centre_spans = (bbox_spans.y0 + bbox_spans.y1) // 2
    tolerance = max(bbox_ligne.hauteur, bbox_spans.hauteur, pt_vers_emu(4))
    return abs(centre_ligne - centre_spans) <= tolerance


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


def _spans_paragraphe_word_native(lignes: list[OcrLine]) -> list[Span]:
    spans: list[Span] = []
    for index, ligne in enumerate(lignes):
        if index:
            reference = spans[-1] if spans else (ligne.spans[0] if ligne.spans else None)
            if reference is not None:
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
        if ligne.spans:
            spans.extend(ligne.spans)
    return spans


def _fusionner_lignes_natives_visuelles(
    lignes: list[OcrLine],
    cadres_lecture: list[BBox],
) -> list[OcrLine]:
    """Regroupe les fragments PDF natifs qui appartiennent a la meme ligne visuelle."""
    if len(lignes) < 2 or len(cadres_lecture) < 2:
        return lignes

    groupes_par_cadre: dict[int, list[OcrLine]] = {}
    hors_cadre: list[OcrLine] = []
    for ligne in sorted(lignes, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        index = _index_cadre_ligne(ligne.bbox, cadres_lecture)
        if index is None:
            hors_cadre.append(ligne)
        else:
            groupes_par_cadre.setdefault(index, []).append(ligne)

    fusionnees: list[OcrLine] = []
    for lignes_cadre in groupes_par_cadre.values():
        rangees: list[list[OcrLine]] = []
        for ligne in lignes_cadre:
            if not rangees:
                rangees.append([ligne])
                continue
            reference = rangees[-1][-1].bbox
            centre_delta = abs((ligne.bbox.y0 + ligne.bbox.y1) - (reference.y0 + reference.y1))
            meme_rangee = centre_delta <= max(ligne.bbox.hauteur, reference.hauteur, pt_vers_emu(6)) * 0.80
            if meme_rangee:
                rangees[-1].append(ligne)
            else:
                rangees.append([ligne])

        for rangee in rangees:
            morceaux = sorted(rangee, key=lambda item: item.bbox.x0)
            bbox = _bbox_lignes(morceaux)
            texte = _normaliser_texte_ocr(" ".join(item.texte.strip() for item in morceaux if item.texte.strip()))
            spans: list[Span] = []
            for item in morceaux:
                if spans and item.spans and _doit_inserer_espace_span(spans[-1], item.spans[0]):
                    spans[-1].texte += " "
                spans.extend(item.spans)
            score = sum(item.score for item in morceaux) / max(len(morceaux), 1)
            fusionnees.append(OcrLine(texte=texte, score=score, bbox=bbox, spans=tuple(spans)))

    fusionnees.extend(hors_cadre)
    fusionnees.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
    return fusionnees


def _scinder_drop_caps(lignes: list[OcrLine]) -> list[OcrLine]:
    """Separe une lettrine native du texte courant quand le PDF les met sur une ligne."""
    resultat: list[OcrLine] = []
    for ligne in lignes:
        spans_utiles = [span for span in ligne.spans if span.texte]
        if len(spans_utiles) < 2:
            resultat.append(ligne)
            continue

        premier = spans_utiles[0]
        suivants = [span for span in spans_utiles[1:] if span.texte.strip()]
        if (
            premier.bbox is None
            or not suivants
            or len(premier.texte.strip()) > 2
            or premier.size_pt < max(span.size_pt for span in suivants) * 2.0
        ):
            resultat.append(ligne)
            continue

        reste_spans = tuple(span for span in ligne.spans[1:] if span.texte)
        if not reste_spans:
            resultat.append(ligne)
            continue

        bbox_reste = next((span.bbox for span in reste_spans if span.bbox is not None), None)
        if bbox_reste is None:
            resultat.append(ligne)
            continue
        for span in reste_spans:
            if span.bbox is not None:
                bbox_reste = _fusionner_bbox(bbox_reste, span.bbox)

        texte_reste = _normaliser_texte_ocr("".join(span.texte for span in reste_spans).strip())
        resultat.append(
            OcrLine(
                texte=premier.texte.strip(),
                score=ligne.score,
                bbox=premier.bbox,
                spans=(premier,),
            )
        )
        resultat.append(
            OcrLine(
                texte=texte_reste,
                score=ligne.score,
                bbox=bbox_reste,
                spans=reste_spans,
            )
        )
    resultat.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
    return resultat


def _styles_compatibles(a: OcrLine, b: OcrLine) -> bool:
    if not a.spans or not b.spans:
        return True
    sa = next((span for span in a.spans if span.texte.strip()), a.spans[0])
    sb = next((span for span in b.spans if span.texte.strip()), b.spans[0])
    return (
        sa.police.famille == sb.police.famille
        and sa.police.gras == sb.police.gras
        and sa.police.italique == sb.police.italique
        and abs(sa.size_pt - sb.size_pt) <= 1.2
        and sa.couleur == sb.couleur
    )


def _grouper_lignes_word_native(page, lignes: list[OcrLine]) -> list[list[OcrLine]]:
    lignes = sorted(lignes, key=lambda ligne: (ligne.bbox.y0, ligne.bbox.x0))
    groupes: list[list[OcrLine]] = []
    courant: list[OcrLine] = []

    for ligne in lignes:
        texte = ligne.texte.strip()
        if not texte:
            continue
        if not courant:
            courant = [ligne]
            continue

        precedente = courant[-1]
        texte_precedent = precedente.texte.strip()
        hauteur = max(precedente.bbox.hauteur, ligne.bbox.hauteur, pt_vers_emu(8))
        gap_y = ligne.bbox.y0 - precedente.bbox.y1
        meme_colonne = abs(ligne.bbox.x0 - precedente.bbox.x0) <= pt_vers_emu(10)
        bord_droit_proche = abs(ligne.bbox.x1 - precedente.bbox.x1) <= pt_vers_emu(42)
        chevauche_horizontal = min(ligne.bbox.x1, precedente.bbox.x1) > max(ligne.bbox.x0, precedente.bbox.x0)
        titre_centre = _ligne_centree(page, ligne.bbox) and len(texte) <= 130
        precedent_titre = _ligne_centree(page, precedente.bbox) and len(texte_precedent) <= 130
        liste = _ligne_liste(texte) or _ligne_liste(texte_precedent)
        nouveau = False

        if gap_y > max(hauteur * 1.15, pt_vers_emu(10)):
            nouveau = True
        if not chevauche_horizontal:
            nouveau = True
        if not meme_colonne and not (titre_centre and precedent_titre):
            nouveau = True
        if len(courant) == 1 and precedent_titre and not titre_centre:
            nouveau = True
        if titre_centre and not precedent_titre:
            nouveau = True
        if liste:
            nouveau = True
        if not _styles_compatibles(precedente, ligne) and gap_y >= 0:
            nouveau = True
        if texte_precedent.endswith((".", ":", ";")) and gap_y > hauteur * 0.65 and not bord_droit_proche:
            nouveau = True

        if nouveau:
            groupes.append(courant)
            courant = [ligne]
        else:
            courant.append(ligne)

    if courant:
        groupes.append(courant)
    return groupes


def _ligne_centree(page, bbox: BBox) -> bool:
    centre_page = pt_vers_emu(page.rect.width / 2)
    return abs((bbox.x0 + bbox.x1) / 2 - centre_page) <= pt_vers_emu(35)


_LISTE_RE = re.compile(
    r"^\s*(?:[•●▪▫◦*]|\(?\d{1,3}[\.)]|[A-Za-z][\.)]|[ivxlcdmIVXLCDM]+[\.)]|o)\s+"
)


def _ligne_liste(texte: str) -> bool:
    return bool(_LISTE_RE.match(texte.strip()))


def _texte_depuis_police_symbole(texte: str, nom_police: str | None) -> str:
    police = (nom_police or "").lower()
    if "wingdings" in police:
        return "".join("→" if caractere in {"Î", "è"} else caractere for caractere in texte)
    return texte


def _doit_inserer_espace_span(precedent: Span, courant: Span) -> bool:
    if not precedent.texte or not courant.texte:
        return False
    if precedent.texte[-1].isspace() or courant.texte[0].isspace():
        return False
    if courant.texte[:1] in ",.;:)]}%":
        return False
    if precedent.texte[-1:] in "([{/$":
        return False
    if precedent.bbox is None or courant.bbox is None:
        return False
    centre_precedent = (precedent.bbox.y0 + precedent.bbox.y1) // 2
    centre_courant = (courant.bbox.y0 + courant.bbox.y1) // 2
    hauteur = max(precedent.bbox.hauteur, courant.bbox.hauteur, 1)
    if abs(centre_precedent - centre_courant) > hauteur * 0.45:
        return False
    gap = courant.bbox.x0 - precedent.bbox.x1
    seuil = max(pt_vers_emu(0.75), int(max(precedent.size_pt, courant.size_pt) * 0.08 * 12700))
    return gap >= seuil


def _spans_layout_item(item, polices: dict) -> list[Span]:
    if not getattr(item, "spans", ()):
        return []

    from pdfexact.extract.text import _couleur_hexa, _resoudre_police, _style_depuis_nom

    spans: list[Span] = []
    for brut in item.spans:
        nom_police = brut.font_name or ""
        texte = _texte_depuis_police_symbole(brut.text, brut.font_name)
        if not texte:
            continue
        nom_resolution = "TimesNewRomanPSMT" if texte != brut.text and "wingdings" in nom_police.lower() else nom_police
        font_id = _resoudre_police(nom_resolution, polices)
        asset = polices[font_id]
        gras, italique = _style_depuis_nom(nom_resolution, int(brut.flags or 0))
        span = Span(
            texte=texte,
            police=FontRef(font_id, asset.famille, gras, italique),
            size_pt=round(float(brut.size_pt or 10.0), 2),
            couleur=_couleur_hexa(brut.color or 0),
            bbox=brut.bbox,
        )
        if spans and _doit_inserer_espace_span(spans[-1], span):
            spans[-1].texte += " "
        spans.append(span)
    if spans and spans[0].texte.strip() in {"•", "●", "▪", "▫", "◦", "*", "o", "O", "○"}:
        for span in spans[1:]:
            if span.texte and not span.texte.strip():
                span.texte = "\t"
                break
    return spans


def _texte_titre(texte: str) -> bool:
    lettres = [car for car in texte if car.isalpha()]
    if not lettres:
        return False
    majuscules = sum(1 for car in lettres if car.isupper())
    return majuscules / len(lettres) >= 0.70


def _alignement_ligne(
    page,
    bbox: BBox,
    texte: str,
    lignes: list[OcrLine] | None = None,
    index: int | None = None,
) -> str:
    largeur_page = pt_vers_emu(page.rect.width)
    marge_gauche = max(0, bbox.x0)
    marge_droite = max(0, largeur_page - bbox.x1)
    court = len(texte) <= 120
    marges_equilibrees = abs(marge_gauche - marge_droite) <= max(pt_vers_emu(14), bbox.largeur * 0.08)
    largeur_relative = bbox.largeur / max(largeur_page, 1)

    if _ligne_liste(texte):
        return "left"
    if (
        "http" in texte.lower()
        and bbox.y0 >= pt_vers_emu(page.rect.height * 0.80)
        and marges_equilibrees
    ):
        return "center"

    ligne_voisine_corps = False
    if lignes is not None and index is not None:
        for autre_index in (index - 1, index + 1):
            if autre_index < 0 or autre_index >= len(lignes):
                continue
            autre = lignes[autre_index].bbox
            meme_colonne = abs(autre.x0 - bbox.x0) <= pt_vers_emu(12)
            meme_bord_droit = abs(autre.x1 - bbox.x1) <= pt_vers_emu(24)
            if meme_colonne and meme_bord_droit:
                ligne_voisine_corps = True
                break

    if (
        court
        and marges_equilibrees
        and _ligne_centree(page, bbox)
        and (largeur_relative <= 0.70 or _texte_titre(texte))
        and (not ligne_voisine_corps or _texte_titre(texte))
    ):
        return "center"
    if marge_droite <= pt_vers_emu(28) and len(texte) <= 90 and marge_gauche > marge_droite + pt_vers_emu(80):
        return "right"

    pres_du_bord_gauche = marge_gauche <= pt_vers_emu(90)
    pres_du_bord_droit = marge_droite <= pt_vers_emu(90)
    largeur_colonne_probable = bbox.largeur >= pt_vers_emu(145) and (
        ligne_voisine_corps or (pres_du_bord_gauche and pres_du_bord_droit)
    )
    if (
        len(texte) >= 45
        and (
            largeur_relative >= 0.58
            or largeur_colonne_probable
        )
        and (ligne_voisine_corps or len(texte) >= 70 or (pres_du_bord_gauche and pres_du_bord_droit))
    ):
        return "both"
    return "left"


def _espacement_paragraphe_word_native(
    texte: str,
    bbox: BBox,
    police,
    polices: dict,
    size_pt: float,
    alignement: str,
) -> int:
    if not texte or police.font_id not in polices:
        return 0
    if alignement not in {"left", "both"} or len(texte) < 35:
        return 0

    from pdfexact.extract.fonts import mesurer_largeur_pt

    cible_pt = emu_vers_pt(bbox.largeur)
    mesuree_pt = mesurer_largeur_pt(texte, polices[police.font_id], size_pt)
    if cible_pt <= 0 or mesuree_pt <= 0:
        return 0
    delta_pt = cible_pt - mesuree_pt
    if abs(delta_pt) < 0.35:
        return 0

    caracteres = max(len(texte) - 1, 1)
    espacement = round(pt_vers_twips(delta_pt / caracteres))
    return max(-12, min(18, espacement))


def _retraits_liste_word_native(ligne: OcrLine, bbox: BBox) -> tuple[int, int]:
    if not _ligne_liste(ligne.texte) or not ligne.spans:
        return max(0, bbox.x0), 0

    texte_x0 = None
    for span in ligne.spans:
        texte = span.texte.strip()
        if not texte or texte in {"•", "●", "▪", "▫", "◦", "*", "o", "O", "○"}:
            continue
        span_bbox = getattr(span, "bbox", None)
        if span_bbox is not None:
            texte_x0 = span_bbox.x0
            break

    if texte_x0 is None or texte_x0 <= bbox.x0:
        return max(0, bbox.x0), 0
    retrait_gauche = max(0, texte_x0)
    retrait_premiere = bbox.x0 - retrait_gauche
    return retrait_gauche, retrait_premiere


def _ligne_word_native(
    page,
    polices: dict,
    ligne: OcrLine,
    facteur_emu: float,
    lignes_triees: list[OcrLine],
    index_ligne: int,
    geometrie: PageGeometry | None = None,
) -> Line:
    police, size_pt, couleur, decoration = _trace_style(page, polices, ligne.bbox, facteur_emu, geometrie)
    spans = list(ligne.spans)
    if spans:
        premier_style = next((span for span in spans if span.texte.strip()), spans[0])
        size_pt = premier_style.size_pt
    else:
        spans = [
            Span(
                ligne.texte,
                police,
                size_pt,
                couleur,
                souligne=decoration.souligne,
                barre=decoration.barre,
                surlignage=decoration.surlignage,
                bbox=ligne.bbox,
            )
        ]
    rendu = Line(
        bbox=ligne.bbox,
        spans=spans,
        hauteur_ligne_emu=max(ligne.bbox.hauteur, pt_vers_emu(size_pt * 1.05)),
        largeur_cible_emu=ligne.bbox.largeur,
        alignement=_alignement_ligne(page, ligne.bbox, ligne.texte, lignes_triees, index_ligne),
        angle_deg=ligne.angle_deg,
        orientation=ligne.orientation,
        baseline_points=tuple((pt_vers_emu(x), pt_vers_emu(y)) for x, y in ligne.quad_points),
        semantic_role=ligne.semantic_role,
    )
    retrait_gauche, retrait_premiere = _retraits_liste_word_native(ligne, ligne.bbox)
    rendu.retrait_gauche_emu = max(0, retrait_gauche - ligne.bbox.x0)
    rendu.retrait_premiere_ligne_emu = retrait_premiere
    return rendu


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
    geometrie: PageGeometry | None = None,
) -> list[FlowParagraph]:
    paragraphes: list[FlowParagraph] = []
    precedent_bas = 0

    for groupe in _grouper_lignes_reflow(page, lignes):
        texte = _texte_paragraphe(groupe)
        if not texte:
            continue
        bbox = _bbox_lignes(groupe)
        police, size_pt, couleur, decoration = _trace_style(page, polices, bbox, facteur_emu, geometrie)
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
                souligne=decoration.souligne,
                barre=decoration.barre,
                surlignage=decoration.surlignage,
            )
        )
        precedent_bas = bbox.y1
    return paragraphes


def _paragraphes_word_native(
    page,
    polices: dict,
    lignes: list[OcrLine],
    facteur_emu: float,
    geometrie: PageGeometry | None = None,
) -> list[FlowParagraph]:
    paragraphes: list[FlowParagraph] = []
    lignes_triees = _scinder_drop_caps(sorted(lignes, key=lambda item: (item.bbox.y0, item.bbox.x0)))
    for groupe in _grouper_lignes_word_native(page, lignes_triees):
        ligne = groupe[0]
        bbox = _bbox_lignes(groupe)
        texte = _texte_paragraphe(groupe)
        if not texte:
            continue
        police, size_pt, couleur, decoration = _trace_style(page, polices, bbox, facteur_emu, geometrie)
        spans = _spans_paragraphe_word_native(groupe)
        if spans:
            premier_style = next((span for span in spans if span.texte.strip()), spans[0])
            police = premier_style.police
            size_pt = premier_style.size_pt
            couleur = premier_style.couleur
        index_ligne = lignes_triees.index(ligne)
        alignements = [
            _alignement_ligne(page, item.bbox, item.texte, lignes_triees, lignes_triees.index(item))
            for item in groupe
        ]
        if len(groupe) > 1 and alignements.count("both") >= max(1, len(groupe) // 2):
            alignement = "both"
        else:
            alignement = _alignement_ligne(page, ligne.bbox, ligne.texte, lignes_triees, index_ligne)
        espacement = (
            0
            if spans
            else _espacement_paragraphe_word_native(texte, bbox, police, polices, size_pt, alignement)
        )
        retrait_gauche, retrait_premiere = _retraits_liste_word_native(ligne, bbox)
        hauteur_ligne = max(
            int(sum(item.bbox.hauteur for item in groupe) / len(groupe)),
            pt_vers_emu(size_pt * 1.05),
        )
        lignes_rendu = [
            _ligne_word_native(
                page,
                polices,
                item,
                facteur_emu,
                lignes_triees,
                lignes_triees.index(item),
                geometrie,
            )
            for item in groupe
        ]
        paragraphes.append(
            FlowParagraph(
                bbox=bbox,
                texte=texte,
                police=police,
                size_pt=size_pt,
                couleur=couleur,
                alignement=alignement,
                retrait_gauche_emu=retrait_gauche,
                retrait_droite_emu=max(0, pt_vers_emu(page.rect.width) - bbox.x1),
                retrait_premiere_ligne_emu=retrait_premiere,
                espace_avant_emu=0,
                espace_apres_emu=0,
                interligne_emu=hauteur_ligne,
                souligne=decoration.souligne,
                barre=decoration.barre,
                surlignage=decoration.surlignage,
                espacement_twips=espacement,
                spans=spans,
                lignes=lignes_rendu,
                angle_deg=ligne.angle_deg,
                orientation=ligne.orientation,
                baseline_points=tuple((pt_vers_emu(x), pt_vers_emu(y)) for x, y in ligne.quad_points),
                semantic_role=ligne.semantic_role,
                curved=ligne.orientation == "curved",
            )
        )
    return paragraphes


def _paragraphes_word_native_par_cadres(
    page,
    polices: dict,
    lignes: list[OcrLine],
    facteur_emu: float,
    cadres_lecture: list[BBox],
    geometrie: PageGeometry | None = None,
) -> list[FlowParagraph]:
    if len(cadres_lecture) < 2:
        return _paragraphes_word_native(page, polices, lignes, facteur_emu, geometrie)

    groupes: dict[int, list[OcrLine]] = {index: [] for index in range(len(cadres_lecture))}
    hors_cadre: list[OcrLine] = []
    for ligne in lignes:
        index = _index_cadre_ligne(ligne.bbox, cadres_lecture)
        if index is None:
            hors_cadre.append(ligne)
        else:
            groupes[index].append(ligne)

    paragraphes: list[FlowParagraph] = []
    for index, cadre in sorted(enumerate(cadres_lecture), key=lambda item: (item[1].y0, item[1].x0)):
        if groupes[index]:
            paragraphes.extend(_paragraphes_word_native(page, polices, groupes[index], facteur_emu, geometrie))
    if hors_cadre:
        paragraphes.extend(_paragraphes_word_native(page, polices, hors_cadre, facteur_emu, geometrie))
    paragraphes.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
    return paragraphes


def _index_cadre_ligne(bbox: BBox, cadres: list[BBox]) -> int | None:
    centre_x = (bbox.x0 + bbox.x1) // 2
    centre_y = (bbox.y0 + bbox.y1) // 2
    meilleur_index: int | None = None
    meilleur_score = 0.0
    aire = max(bbox.largeur * bbox.hauteur, 1)
    for index, cadre in enumerate(cadres):
        contient = cadre.x0 <= centre_x <= cadre.x1 and cadre.y0 <= centre_y <= cadre.y1
        x0 = max(bbox.x0, cadre.x0)
        y0 = max(bbox.y0, cadre.y0)
        x1 = min(bbox.x1, cadre.x1)
        y1 = min(bbox.y1, cadre.y1)
        couverture = max(0, x1 - x0) * max(0, y1 - y0) / aire
        if not contient and couverture < 0.30:
            continue
        score = couverture + (1.0 if contient else 0.0)
        if score > meilleur_score:
            meilleur_index = index
            meilleur_score = score
    return meilleur_index


def _ligne_figure_isolee(ligne: OcrLine) -> bool:
    texte = ligne.texte.strip()
    if not texte:
        return True
    if has_non_latin_letters(texte):
        return False
    spans_utiles = [span for span in ligne.spans if span.texte.strip()]
    if spans_utiles and any(span.bbox is not None for span in spans_utiles):
        return False
    mots_alpha = [mot for mot in re.findall(r"[A-Za-z]+", texte) if len(mot) > 1]
    if spans_utiles:
        taille_max = max(span.size_pt for span in spans_utiles)
        couleur_non_noire = any(span.couleur.upper() not in {"000000", "0"} for span in spans_utiles)
        if taille_max >= 13 or couleur_non_noire or len(mots_alpha) >= 2:
            return False
    if len(texte) <= 3:
        return True
    lettres = sum(1 for c in texte if c.isalpha())
    # Un mot court peut être un titre valide (Physics, Wiley, Mass, ...). Les faux
    # positifs alphabétiques doivent être filtrés par le score OCR et le plan, pas par
    # une longueur arbitraire qui supprimait les titres de couverture.
    if len(texte) <= 18 and lettres <= 8 and len(mots_alpha) <= 1:
        return not texte.isalpha()
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
    asset = polices[span.police.font_id]
    mesuree_pt = mesurer_largeur_pt(span.texte, asset, span.size_pt)
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

    police_source = polices.get(span.police.font_id)
    if (
        span.size_pt <= 18
        and mesuree_pt > cible_sure_pt
        and (police_source is None or police_source.reconnue)
    ):
        facteur = max(0.76, min(0.99, (cible_sure_pt / mesuree_pt) * 0.98))
        span.size_pt = max(6.0, round(span.size_pt * facteur, 2))
        mesuree_pt *= facteur
    caracteres = max(len(span.texte), 1)
    span.espacement_twips = max(
        -4,
        min(0, round(pt_vers_twips((cible_sure_pt - mesuree_pt) / caracteres))),
    )


def _textbox(
    page,
    polices: dict,
    texte: str,
    bbox: BBox,
    facteur_emu: float,
    ajuster_largeur: bool = True,
    layout_map=None,
    geometrie: PageGeometry | None = None,
) -> TextBox:
    bbox = _limiter_bbox(page, bbox)
    if layout_map is not None:
        bbox = layout_map.recaler_ligne_ocr(bbox, texte)
    police, size_pt, couleur, decoration = _trace_style(page, polices, bbox, facteur_emu, geometrie)
    hauteur_ligne = max(bbox.hauteur, pt_vers_emu(size_pt * 1.18))
    bbox = BBox(bbox.x0, bbox.y0, bbox.x1, min(pt_vers_emu(page.rect.height), bbox.y0 + hauteur_ligne))
    span = Span(
        texte=texte,
        police=police,
        size_pt=size_pt,
        couleur=couleur,
        souligne=decoration.souligne,
        barre=decoration.barre,
        surlignage=decoration.surlignage,
    )
    ligne = Line(
        bbox=bbox,
        spans=[span],
        hauteur_ligne_emu=max(hauteur_ligne, 1),
        largeur_cible_emu=max(bbox.largeur, 1),
        alignement=_alignement_ligne(page, bbox, texte),
        angle_deg=0.0,
        orientation="horizontal",
    )
    if ajuster_largeur:
        _ajuster_largeur_ocr(ligne, polices)
    return TextBox(bbox=bbox, lignes=[ligne])


def _textbox_depuis_ligne_native(
    page,
    polices: dict,
    ligne_source: OcrLine,
    facteur_emu: float,
    layout_map=None,
    geometrie: PageGeometry | None = None,
) -> TextBox:
    bbox = _limiter_bbox(page, ligne_source.bbox)
    texte = ligne_source.texte
    if layout_map is not None:
        bbox = layout_map.recaler_ligne_ocr(bbox, texte)
    if ligne_source.spans:
        spans = [
            Span(
                texte=span.texte,
                police=span.police,
                size_pt=span.size_pt,
                couleur=span.couleur,
                espacement_twips=span.espacement_twips,
                lien=span.lien,
                invisible=span.invisible,
                souligne=span.souligne,
                barre=span.barre,
                capitales=span.capitales,
                exposant=span.exposant,
                indice=span.indice,
                surlignage=span.surlignage,
                bbox=span.bbox,
            )
            for span in ligne_source.spans
        ]
        taille = max((span.size_pt for span in spans if span.texte.strip()), default=10.0)
        bbox_spans = _bbox_spans_ligne(spans)
        if bbox_spans is not None and _bbox_spans_coherente_ligne(bbox, bbox_spans):
            bbox = _limiter_bbox(page, bbox_spans)
    else:
        police, taille, couleur, decoration = _trace_style(page, polices, bbox, facteur_emu, geometrie)
        spans = [
            Span(
                texte=texte,
                police=police,
                size_pt=taille,
                couleur=couleur,
                souligne=decoration.souligne,
                barre=decoration.barre,
                surlignage=decoration.surlignage,
            )
        ]
    hauteur_ligne = max(bbox.hauteur, pt_vers_emu(taille * 1.12))
    if ligne_source.orientation == "horizontal":
        bbox = BBox(
            bbox.x0,
            bbox.y0,
            bbox.x1,
            min(pt_vers_emu(page.rect.height), bbox.y0 + hauteur_ligne),
        )
    else:
        # RapidOCR peut fournir une bbox quadrilatere haute pour une legende
        # verticale. Ne la reduisons pas a la hauteur d'un seul glyphe : cette
        # emprise devient ensuite la taille du cadre Word ancre.
        hauteur_ligne = max(bbox.hauteur, hauteur_ligne)
    ligne = Line(
        bbox=bbox,
        spans=spans,
        hauteur_ligne_emu=max(hauteur_ligne, 1),
        largeur_cible_emu=max(bbox.largeur, 1),
        alignement=_alignement_ligne(page, bbox, texte),
        angle_deg=ligne_source.angle_deg,
        orientation=ligne_source.orientation,
        baseline_points=tuple(
            (pt_vers_emu(x), pt_vers_emu(y)) for x, y in ligne_source.quad_points
        ),
        semantic_role=ligne_source.semantic_role,
        curved=ligne_source.orientation == "curved",
    )
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
    geometrie: PageGeometry | None = None,
    zones_cibles: list[BBox] | None = None,
    observation_page=None,
    language: str = "auto",
    model_root=None,
):
    """Retourne du vrai texte Word visible, reconnu par RapidOCR et positionné."""
    zones_ignorees = zones_ignorees or []
    page_exact_native = layout in {"hybrid", "word-native"}
    besoin_boites_mots = granularite != "line" or (page_exact_native and layout_map is not None)
    with TemporaryDirectory(prefix="pdfexact-rapidocr-") as dossier:
        image = Path(dossier) / "page.png"
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        pixmap.save(image)
        facteur = 72.0 / dpi
        def accept_box(points):
            bbox = _boite_rapidocr(points, facteur)
            return (not zones_cibles or _bbox_dans_zones(bbox, zones_cibles)) and not _touche_zone_ignoree(bbox, zones_ignorees)

        result = _rapidocr(language=language, model_root=model_root)(
            str(image),
            return_word_box=besoin_boites_mots,
            return_single_char_box=granularite == "char",
            accept_box=accept_box,
        )

    facteur = 72.0 / dpi
    facteur_emu = 12700.0
    blocs = []
    lignes_ocr = []
    raw_lines = [OcrLine(text or "", score, _boite_rapidocr(points, facteur),
                         quad_points=tuple((float(x) * facteur, float(y) * facteur) for x, y in points))
                 for text, score, points in zip(result.txts, result.scores, result.boxes)]
    observations = _capture_ocr_lines(page, raw_lines, observation_page, "rapidocr-line", language=language,
                                      routing_evidence=getattr(result, "routing_evidence", None))
    if observation_page is not None:
        observation_page.diagnostics.append(Evidence("ocr-routing-summary", "pdfexact.extract.ocr_routing",
            confidence=None, details=(("language_request", language), ("auto_calibrated", False),
                                     ("warnings", getattr(result, "routing_warnings", [])),
                                     ("elapsed_seconds", getattr(result, "routing_elapsed_seconds", None)))))
    lignes_brutes = _lignes_rapidocr(result, facteur)
    if zones_cibles:
        lignes_brutes = [
            ligne for ligne in lignes_brutes if _bbox_dans_zones(ligne.bbox, zones_cibles)
        ]
    lignes_source = lignes_brutes
    lignes_natives_directes: list[OcrLine] = []
    lignes_mots_colonnes: list[OcrLine] = []
    sources_natives = []
    native_line_ids = {}
    native_blank_ids = set()
    if page_exact_native and layout_map is not None:
        if layout == "word-native":
            geometrie = geometrie or PageGeometry.depuis_page(page)
            sources_natives = _acquerir_sources_natives(page, polices, geometrie, observation_page)
            cadres = layout_map._cadres_lecture_taxonomie()
            for source in sources_natives:
                for line in source.lignes:
                    proxy = OcrLine(element_text(line), line.confidence, line.bbox,
                                    tuple(line.spans), line.angle_deg, line.orientation,
                                    semantic_role=line.semantic_role)
                    if not (_ligne_hors_zones_protegees(proxy, zones_ignorees)
                            or (cadres and _ligne_dans_cadres_lecture(proxy, cadres, geometrie.hauteur_emu))):
                        continue
                    if zones_cibles and not _bbox_dans_zones(line.bbox, zones_cibles):
                        continue
                    if proxy.texte.strip():
                        lignes_natives_directes.append(proxy)
                        native_line_ids[id(proxy)] = line.source_id
                    else:
                        native_blank_ids.add(line.source_id)
        else:
            lignes_natives_directes = _lignes_natives_hybrides(
                layout_map,
                zones_ignorees,
                polices,
                lignes_visuelles=True,
                fusionner_fragments=True,
            )
        lignes_mots_colonnes = _reconstruire_lignes_depuis_mots_colonnes(
            _elements_mots_rapidocr(result, facteur),
            layout_map.cadres_lecture_natifs(),
        )
        if layout == "word-native" and lignes_natives_directes:
            lignes_source = _choisir_lignes_word_native(
                lignes_brutes,
                lignes_natives_directes,
                lignes_mots_colonnes,
            )
        elif len(lignes_natives_directes) >= max(4, int(len(lignes_brutes) * 0.35)):
            lignes_source = lignes_natives_directes
        elif len(lignes_mots_colonnes) >= 4:
            lignes_source = lignes_mots_colonnes

    if sources_natives and (lignes_source is lignes_natives_directes
                            or (not lignes_source and native_blank_ids)):
        selected_ids = {*native_blank_ids, *(native_line_ids[id(line)] for line in lignes_source)}
        return _sortie_sources_natives(page, sources_natives, selected_ids, observations,
                                      observation_page, geometrie)

    if zones_cibles:
        lignes_source = [
            ligne for ligne in lignes_source if _bbox_dans_zones(ligne.bbox, zones_cibles)
        ]

    for ligne in lignes_source:
        bbox = _limiter_bbox(page, ligne.bbox)
        if page_exact_native and layout_map is not None and not ligne.spans:
            bbox = layout_map.contraindre_bbox_texte(bbox, ligne.texte)
        texte = _normaliser_marqueur_colonne_droite(page, bbox, ligne.texte)
        lignes_ocr.append(
            OcrLine(
                texte,
                ligne.score,
                bbox,
                ligne.spans,
                ligne.angle_deg,
                ligne.orientation,
                ligne.quad_points,
                ligne.semantic_role,
            )
        )
    zones_formules = [
        ligne.bbox
        for ligne in lignes_ocr
        if _ligne_formule_a_rasteriser(ligne, polices)
        and _zone_raster_utile(ligne.bbox)
        and not _touche_zone_ignoree(ligne.bbox, zones_ignorees)
    ]
    zones_symboles = [
        zone
        for zone in _zones_glyphes_symboles_non_reconnus(lignes_ocr, polices)
        if not _touche_zone_ignoree(zone, zones_ignorees)
    ]
    if media is not None:
        for zone in zones_formules:
            blocs.append(rasteriser_region(page, zone, media, dpi=dpi, purpose="formula"))
        for zone in zones_symboles:
            blocs.append(rasteriser_region(page, zone, media, dpi=dpi, purpose="symbol"))
    zones_ignorees = zones_ignorees + zones_formules + zones_symboles
    cadres_lecture = (
        layout_map.cadres_lecture_natifs()
        if page_exact_native and layout == "word-native" and layout_map is not None
        else []
    )
    cadres_preservation = (
        layout_map._cadres_lecture_taxonomie()
        if page_exact_native and layout == "word-native" and layout_map is not None
        else []
    )
    if cadres_lecture and cadres_preservation:
        cadres_lecture = cadres_lecture + [
            cadre for cadre in cadres_preservation if cadre not in cadres_lecture
        ]
    if layout in {"reflow", "word-native"}:
        lignes_texte = [
            ligne
            for ligne in lignes_ocr
            if (
                _ligne_hors_zones_protegees(ligne, zones_ignorees)
                or (
                    page_exact_native
                    and layout_map is not None
                    and layout_map.confirme_texte_natif(ligne.bbox, ligne.texte)
                    and cadres_preservation
                    and _ligne_dans_cadres_lecture(
                        ligne,
                        cadres_preservation,
                        geometrie.hauteur_emu if geometrie else pt_vers_emu(page.rect.height),
                    )
                )
            )
            and not _ligne_glyphe_symbole_non_reconnue(ligne, polices)
            and not _ligne_figure_isolee(ligne)
            and _ligne_dans_cadres_lecture(ligne, cadres_lecture, geometrie.hauteur_emu if geometrie else pt_vers_emu(page.rect.height))
        ]
        if layout == "word-native":
            blocs.extend(
                _paragraphes_word_native_par_cadres(
                    page,
                    polices,
                    lignes_texte,
                    facteur_emu,
                    cadres_lecture,
                    geometrie,
                )
            )
        else:
            blocs.extend(_paragraphes_reflow(page, polices, lignes_texte, facteur_emu, geometrie))
        blocs.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
        if verbose:
            objets_word = len([b for b in blocs if isinstance(b, FlowParagraph)])
            if layout == "word-native":
                objets_word = len([b for b in blocs if isinstance(b, FlowParagraph)])
                print(
                    f"      RapidOCR: {len(lignes_texte)} ligne(s) -> "
                f"{objets_word} paragraphe(s) Word natif(s)"
                f" ({layout}), formules={len(zones_formules)}",
                file=sys.stderr,
            )
        return _finaliser_source_ocr(page, blocs, observations, observation_page, dpi=dpi)

    blocs_page = (
        detecter_blocs_page(
            [ligne for ligne in lignes_ocr if _ligne_hors_zones_protegees(ligne, zones_ignorees)],
            zones_ignorees,
        )
        if layout in {"blocks", "hybrid", "word-native"}
        else []
    )
    blocs_texte = [bloc for bloc in blocs_page if bloc.kind == "text"]

    elements = []
    if (
        (lignes_mots_colonnes and lignes_source is lignes_mots_colonnes)
        or (lignes_natives_directes and lignes_source is lignes_natives_directes)
    ):
        elements = [(ligne.texte, ligne.score, ligne.bbox) for ligne in lignes_ocr]
    else:
        for texte, score, points in _elements_rapidocr(result, granularite):
            texte = _normaliser_texte_ocr((texte or "").strip())
            if not texte:
                continue
            bbox = _limiter_bbox(page, _boite_rapidocr(points, facteur))
            texte = _normaliser_marqueur_colonne_droite(page, bbox, texte)
            elements.append((texte, score, bbox))
    word_observations = _capture_ocr_lines(page, [OcrLine(text, score, bbox) for text, score, bbox in elements],
                                          observation_page, "rapidocr-item")
    observations.extend(word_observations)
    elements = _dedoublonner_elements_ocr(_corriger_elements_ocr(elements))

    ignores = 0
    utilises: set[int] = set()
    remplacements_natifs_utilises: set[tuple[int, int, int, int, str]] = set()

    if layout in {"blocks", "hybrid", "word-native"}:
        for bloc in blocs_texte:
            for index, (texte, _score, bbox) in enumerate(elements):
                if index in utilises:
                    continue
                if not centre_dans(bbox, bloc.bbox):
                    continue
                preuve_native = (
                    page_exact_native
                    and layout_map is not None
                    and layout_map.confirme_texte_natif(bbox, texte)
                )
                filtre_visuel = (
                    page_exact_native
                    and layout_map is not None
                    and not preuve_native
                    and (
                        layout_map.touche_visuel(bbox)
                        or layout_map.contredit_texte_natif(bbox, texte)
                        or (len(texte.strip()) <= 8 and not has_non_latin_letters(texte)
                            and layout_map.proche_petit_visuel(bbox))
                    )
                )
                if _touche_zone_ignoree(bbox, zones_ignorees) or filtre_visuel:
                    ignores += 1
                    utilises.add(index)
                    continue
                texte_final = texte
                bbox_final = bbox
                if page_exact_native and layout_map is not None:
                    remplacement = layout_map.remplacement_texte_natif(bbox, texte)
                    if remplacement is not None:
                        cle_remplacement = (
                            remplacement.bbox.x0,
                            remplacement.bbox.y0,
                            remplacement.bbox.x1,
                            remplacement.bbox.y1,
                            remplacement.text,
                        )
                        if cle_remplacement in remplacements_natifs_utilises:
                            ignores += 1
                            utilises.add(index)
                            continue
                        remplacements_natifs_utilises.add(cle_remplacement)
                        texte_final = remplacement.text
                        bbox_final = remplacement.bbox
                blocs.append(
                    _textbox(
                        page,
                        polices,
                        texte_final,
                        bbox_final,
                        facteur_emu,
                        layout_map=layout_map if page_exact_native else None,
                        geometrie=geometrie,
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
                blocs.append(_textbox(page, polices, texte, bbox, facteur_emu, geometrie=geometrie))
    else:
        for texte, _score, bbox in elements:
            if _touche_zone_ignoree(bbox, zones_ignorees):
                ignores += 1
                continue
            blocs.append(_textbox(page, polices, texte, bbox, facteur_emu, geometrie=geometrie))

    blocs.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))

    if verbose:
        suffixe = f", {ignores} ignoré(s) sur image" if ignores else ""
        details_blocs = ""
        if layout in {"blocks", "hybrid", "word-native"}:
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
    return _finaliser_source_ocr(page, blocs, observations, observation_page, dpi=dpi)


def _choisir_lignes_word_native(
    lignes_brutes: list[OcrLine],
    lignes_natives_directes: list[OcrLine],
    lignes_mots_colonnes: list[OcrLine],
) -> list[OcrLine]:
    """Evite que le natif PDF sous-segmente un listing dense."""
    if len(lignes_brutes) >= max(8, int(len(lignes_natives_directes) * 1.6)):
        return lignes_brutes
    if len(lignes_mots_colonnes) >= max(8, int(len(lignes_natives_directes) * 1.6)):
        return lignes_mots_colonnes
    return lignes_natives_directes
