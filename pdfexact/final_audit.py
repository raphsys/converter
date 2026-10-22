"""Certification finale du DOCX produit.

La passe compare la source PDF et le document déjà rendu. Elle utilise le layout IA
comme source de zones attendues, puis récupère depuis le PDF original les zones
visuelles absentes de l'IR avant réécriture du DOCX.
"""
from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import mkdtemp
from typing import Callable, Sequence

import pymupdf

from pdfexact.fallback.rasterize import rasteriser_region, rasteriser_region_sans_texte
from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt, pt_vers_emu
from pdfexact.analysis.geometry import bbox_area, center_in, iou, overlap_ratio, union_many
from pdfexact.analysis.text_geometry import block_alignment, geometry_kind
from pdfexact.ir import Document, FlowParagraph, ImageEl, RasterEl, ShapeEl, TableEl, TextBox
from pdfexact.layout.ai import LayoutAIPage, LayoutAIZone, detecter_layout_ia
from pdfexact.layout.analyzer import analyser_page
from pdfexact.render.package import ecrire_docx
from pdfexact.report import CertificationFinale, IssueCertificationFinale

_ROLES_VISUELS_RECUPERABLES = {"visual", "formula", "table"}
_ROLES_VISUELS_AUDITES = {"visual", "formula", "table"}
_SEUIL_COUVERTURE = 0.72
_SEUIL_SIMILARITE = 0.86
_SEUIL_SIMILARITE_ZONE = 0.93
_TOKENS_TEXTE = re.compile(r"\w+|[^\w\s]")


@dataclass
class AuditRecord:
    """Résultat vérifiable pour un élément source individuel."""

    element_id: str
    page_index: int
    kind: str
    source_present: bool = True
    output_present: bool = False
    token_recall: float = 0.0
    token_precision: float = 0.0
    bbox_iou: float = 0.0
    expected_orientation: str = "horizontal"
    expected_geometry: str = "rectangular-flow"
    expected_alignment: str = "left"
    visible: bool = False
    editable: bool = False
    bbox_drift_pt: float = 0.0
    style_mismatches: list[str] = field(default_factory=list)
    occluded: bool = False
    status: str = "missing"
    causes: list[str] = field(default_factory=list)
    output_page_index: int | None = None
    text_sequence_matches: bool | None = None
    text_occurrences_match: bool | None = None
    # ``editable`` is IR eligibility, not proof from the emitted package XML.
    editability_verified: bool = False


@dataclass
class AuditReport:
    """Agrégat par page et par élément, indépendant du score global."""

    records: list[AuditRecord] = field(default_factory=list)

    @property
    def errors(self) -> list[AuditRecord]:
        return [record for record in self.records if record.status == "error"]

    @property
    def conforme(self) -> bool:
        return not self.errors


@dataclass
class CorrectionLocale:
    """Trace d'une mutation de page appliquée par l'audit."""

    page_index: int
    action: str
    reason: str
    removed_element_ids: list[str] = field(default_factory=list)
    inserted_element_id: str | None = None
    rollback_available: bool = True


def certifier_et_reparer(
    source_pdf,
    docx_produit,
    document: Document,
    *,
    dpi: int = 120,
    layout_provider: str | None = None,
    layout_model: str | None = None,
    layout_model_root: str | None = None,
    layout_device: str | None = None,
    native_rewriter: bool = False,
    max_repair_passes: int = 2,
    verbose: bool = False,
) -> CertificationFinale:
    if max_repair_passes < 0:
        raise ValueError("max_repair_passes ne peut pas etre negatif")
    # A certification is pessimistic until a real DOCX render has been
    # compared element-by-element with the source PDF.
    resultat = CertificationFinale(active=True, conforme=False)
    try:
        with pymupdf.open(source_pdf) as doc_source:
            resultat.pages_source = doc_source.page_count
            pages_layout = _detecter_pages_source(
                doc_source,
                document,
                provider=layout_provider,
                model=layout_model,
                model_root=layout_model_root,
                device=layout_device,
            )
            resultat.pages_analysees = len(pages_layout)
            resultat.zones_ai = sum(len(page.zones) for page in pages_layout)
            pdf_initial = _exporter_docx_pdf(docx_produit)
            if pdf_initial is None:
                resultat.avertissements.append("audit_rendu_ignore:export_docx_pdf_indisponible")
                resultat.issues.append(
                    IssueCertificationFinale(
                        page=0,
                        categorie="audit",
                        message="impossible de rendre le DOCX en PDF pour l'audit visuel",
                        severite="error",
                    )
                )
                return resultat
            try:
                doc_converti = pymupdf.open(pdf_initial) if pdf_initial else None
                try:
                    document_avant_recuperation = copy.deepcopy(document)
                    mots_avant_recuperation = _compter_mots_pdf(doc_converti)
                    resultat.pages_rendues = doc_converti.page_count if doc_converti is not None else 0
                    _auditer_structure_ir(document, resultat)
                    resultat.audit_diagnostics.extend(auditer_overflow(document))
                    resultat.audit_diagnostics.extend(auditer_z_order(document))
                    resultat.audit_diagnostics.extend(auditer_font_metrics(document))
                    if (
                        doc_converti is not None
                        and doc_converti.page_count != doc_source.page_count
                    ):
                        resultat.issues.append(
                            IssueCertificationFinale(
                                page=0,
                                categorie="pagination",
                                message=(
                                    "nombre de pages rendu différent du PDF source: "
                                    f"{doc_converti.page_count}/{doc_source.page_count}"
                                ),
                                severite="error",
                            )
                        )
                    _auditer_couverture_visuelle(
                        doc_source,
                        document,
                        pages_layout,
                        resultat,
                        dpi=dpi,
                        doc_converti=doc_converti,
                        native_rewriter=native_rewriter,
                    )
                finally:
                    if doc_converti is not None:
                        doc_converti.close()
            finally:
                if pdf_initial is not None:
                    _supprimer_fichier_temporaire(pdf_initial)
            if resultat.zones_visuelles_recuperees and max_repair_passes > 0:
                ecrire_docx(document, docx_produit, native_rewriter=native_rewriter)
            pdf_docx = _exporter_docx_pdf(docx_produit)
            if pdf_docx is None:
                resultat.avertissements.append("audit_rendu_ignore:export_docx_pdf_indisponible")
            else:
                resultat.audit_rendu_verifie = True
                try:
                    mots_apres_recuperation = _compter_mots_pdf(pdf_docx)
                    if (
                        mots_avant_recuperation
                        and mots_apres_recuperation < int(mots_avant_recuperation * 0.97)
                    ):
                        # Une récupération visuelle ne doit jamais sacrifier du texte.
                        # On restaure l'IR précédent et on réécrit le DOCX sans cette
                        # récupération agressive.
                        document.pages = document_avant_recuperation.pages
                        document.media = document_avant_recuperation.media
                        ecrire_docx(document, docx_produit, native_rewriter=native_rewriter)
                        _supprimer_fichier_temporaire(pdf_docx)
                        pdf_docx = _exporter_docx_pdf(docx_produit)
                        resultat.avertissements.append("recuperation_visuelle_annulee_texte_protege")
                    _auditer_similarite_zones_finales(
                        doc_source,
                        pdf_docx,
                        document,
                        pages_layout,
                        resultat,
                        dpi=dpi,
                        native_rewriter=native_rewriter,
                    )
                    _auditer_texte(source_pdf, pdf_docx, document, resultat)
                    _auditer_texte_visible(document, pdf_docx, resultat)
                    audit_elements = construire_audit_elements(document, pdf_docx, source_pdf=doc_source)
                    resultat.audit_elements = [asdict(record) for record in audit_elements.records]
                    resultat.audit_elements_en_erreur = len(audit_elements.errors)
                    resultat.audit_diagnostics.extend(auditer_editability(document, docx_produit))
                    _auditer_similarite_visuelle(source_pdf, pdf_docx, document, resultat, dpi=dpi)
                finally:
                    _supprimer_fichier_temporaire(pdf_docx)
    except Exception as exc:  # noqa: BLE001
        resultat.avertissements.append(f"audit_final_incomplet:{type(exc).__name__}:{exc}")

    resultat.conforme = (
        resultat.zones_visuelles_non_couvertes == 0
        and resultat.ratio_texte >= 0.97
        and "audit_rendu_ignore:export_docx_pdf_indisponible" not in resultat.avertissements
        and (
            resultat.score_visuel_min is None
            or resultat.score_visuel_min >= _SEUIL_SIMILARITE
        )
        and resultat.pages_source == resultat.pages_rendues
        and resultat.elements_hors_page == 0
        and resultat.textes_non_visibles == 0
        and resultat.audit_elements_en_erreur == 0
        and resultat.audit_rendu_verifie
        and not any(issue.severite == "error" for issue in resultat.issues)
    )
    if verbose:
        print(
            "      audit final: "
            f"{resultat.zones_visuelles_recuperees} récupération(s), "
            f"{resultat.zones_visuelles_non_couvertes} manque(s), "
            f"ratio texte={resultat.ratio_texte:.3f}",
            file=sys.stderr,
        )
    return resultat


def _detecter_pages_source(
    doc_source,
    document: Document,
    *,
    provider: str | None,
    model: str | None,
    model_root: str | Path | None,
    device: str | None,
) -> list[LayoutAIPage]:
    pages = []
    for page_doc in document.pages:
        if page_doc.index >= doc_source.page_count:
            continue
        page_pdf = doc_source.load_page(page_doc.index)
        geometrie = PageGeometry.depuis_page(page_pdf)
        analyse = analyser_page(page_pdf, geometrie)
        pages.append(
            detecter_layout_ia(
                page_pdf,
                analyse,
                provider=provider,
                model=model,
                model_root=model_root,
                device=device,
                required=True,
            )
        )
    return pages


def _auditer_couverture_visuelle(
    doc_source,
    document: Document,
    pages_layout: Sequence[LayoutAIPage],
    resultat: CertificationFinale,
    *,
    dpi: int,
    rasterizer: Callable = rasteriser_region,
    doc_converti=None,
    comparer_zone: Callable | None = None,
    native_rewriter: bool = False,
) -> None:
    comparer_zone = comparer_zone or _similarite_zone
    for sortie_index, (page_doc, page_layout) in enumerate(zip(document.pages, pages_layout, strict=False)):
        zones = [_normaliser_zone_visuelle(zone, page_doc.largeur_emu, page_doc.hauteur_emu) for zone in page_layout.zones]
        zones = [zone for zone in zones if zone is not None]
        resultat.zones_visuelles_attendues += sum(1 for zone in zones if zone.role in _ROLES_VISUELS_AUDITES)
        page_pdf = doc_source.load_page(page_doc.index) if page_doc.index < doc_source.page_count else None
        page_convertie = (
            doc_converti.load_page(sortie_index)
            if doc_converti is not None and sortie_index < doc_converti.page_count
            else None
        )
        for zone in zones:
            if zone.role not in _ROLES_VISUELS_AUDITES:
                continue
            couverture_ok = _zone_couverte(zone.bbox, page_doc.elements)
            score_zone = None
            if page_pdf is not None and page_convertie is not None and zone.role in _ROLES_VISUELS_RECUPERABLES:
                score_zone = comparer_zone(page_pdf, page_convertie, zone.bbox, dpi=dpi)
                resultat.zones_visuelles_comparees += 1
                resultat.score_zone_visuelle_min = (
                    score_zone
                    if resultat.score_zone_visuelle_min is None
                    else min(resultat.score_zone_visuelle_min, score_zone)
                )
            # Le rewriter natif possède déjà un objet éditable couvrant la zone.
            # Une différence de pixels (police, anti-aliasing, vecteur) ne justifie
            # pas de le remplacer par un raster qui pourrait réintroduire ses glyphes.
            # Les zones réellement absentes restent récupérables par la passe ci-dessous.
            couverture_native = max(
                (
                    _ratio_couverture(zone.bbox, element.bbox)
                    for element in page_doc.elements
                    if isinstance(element, (ImageEl, RasterEl, ShapeEl, TableEl))
                ),
                default=0.0,
            )
            similarite_ok = score_zone is None or score_zone >= _SEUIL_SIMILARITE_ZONE
            if couverture_ok and similarite_ok:
                continue
            cause = "non couverte" if not couverture_ok else f"différente du PDF source ({score_zone:.3f})"
            if zone.role not in _ROLES_VISUELS_RECUPERABLES:
                resultat.issues.append(
                    IssueCertificationFinale(
                        page=page_doc.index + 1,
                        categorie=zone.role,
                        message=f"zone {zone.label} {cause} dans le DOCX",
                        bbox=[zone.bbox.x0, zone.bbox.y0, zone.bbox.x1, zone.bbox.y1],
                    )
                )
                resultat.zones_visuelles_non_couvertes += 1
                continue
            if page_pdf is None:
                resultat.issues.append(
                    IssueCertificationFinale(
                        page=page_doc.index + 1,
                        categorie=zone.role,
                        message=f"zone {zone.label} {cause} dans le DOCX",
                        bbox=[zone.bbox.x0, zone.bbox.y0, zone.bbox.x1, zone.bbox.y1],
                    )
                )
                resultat.zones_visuelles_non_couvertes += 1
                continue
            contient_texte_word = _zone_contient_texte_word(zone.bbox, page_doc.elements)
            recuperation_sans_texte = contient_texte_word and rasterizer is rasteriser_region
            element = (
                rasteriser_region_sans_texte(page_pdf, zone.bbox, document.media, dpi=dpi)
                if recuperation_sans_texte
                else rasterizer(page_pdf, zone.bbox, document.media, dpi=dpi)
            )
            if recuperation_sans_texte:
                element.purpose = "audit-background"
            else:
                element.purpose = "audit-baked-visual"
            correction = appliquer_correction_avec_rollback(
                page_doc.elements,
                zone.bbox,
                element,
                retirer_texte=not recuperation_sans_texte,
                page_index=page_doc.index,
                reason=f"visual-zone:{zone.role}:{zone.zone_id}",
            )
            resultat.corrections_locales.append(asdict(correction))
            resultat.zones_visuelles_recuperees += 1
        if page_pdf is not None and page_convertie is not None:
            _auditer_tables_reconstituees(
                page_pdf,
                page_convertie,
                page_doc.elements,
                zones,
                resultat,
                document.media,
                page_numero=page_doc.index + 1,
                dpi=dpi,
                comparer_zone=comparer_zone,
            )


def _normaliser_zone_visuelle(zone: LayoutAIZone, largeur_page: int, hauteur_page: int) -> LayoutAIZone | None:
    if zone.role not in _ROLES_VISUELS_AUDITES:
        return None
    bbox = BBox(
        max(0, min(zone.bbox.x0, largeur_page)),
        max(0, min(zone.bbox.y0, hauteur_page)),
        max(0, min(zone.bbox.x1, largeur_page)),
        max(0, min(zone.bbox.y1, hauteur_page)),
    )
    if bbox.largeur < 1 or bbox.hauteur < 1:
        return None
    aire_page = max(1, largeur_page * hauteur_page)
    if _aire(bbox) / aire_page > 0.80:
        return None
    return LayoutAIZone(
        zone_id=zone.zone_id,
        label=zone.label,
        role=zone.role,
        confidence=zone.confidence,
        bbox=bbox,
        source=zone.source,
        model_id=zone.model_id,
    )


def _zone_couverte(zone: BBox, elements: Sequence[object]) -> bool:
    couvertures = []
    for element in elements:
        if not isinstance(element, (ImageEl, RasterEl, ShapeEl, TableEl)):
            continue
        couvertures.append(_ratio_couverture(zone, element.bbox))
    return max(couvertures, default=0.0) >= _SEUIL_COUVERTURE


def _auditer_tables_reconstituees(
    page_pdf,
    page_convertie,
    elements: list[object],
    zones_ia: Sequence[LayoutAIZone],
    resultat: CertificationFinale,
    media: dict,
    *,
    page_numero: int,
    dpi: int,
    comparer_zone: Callable,
) -> None:
    for table in list(element for element in elements if isinstance(element, TableEl)):
        score = comparer_zone(page_pdf, page_convertie, table.bbox, dpi=dpi)
        if score >= _SEUIL_SIMILARITE_ZONE:
            continue
        table_ia = any(
            zone.role == "table" and _ratio_couverture(table.bbox, zone.bbox) >= 0.50
            for zone in zones_ia
        )
        action = "récupérée" if table_ia else "supprimée"
        resultat.issues.append(
            IssueCertificationFinale(
                page=page_numero,
                categorie="table",
                message=f"table reconstruite différente du PDF source ({score:.3f}), {action}",
                bbox=[table.bbox.x0, table.bbox.y0, table.bbox.x1, table.bbox.y1],
            )
        )
        contient_texte_word = _zone_contient_texte_word(table.bbox, elements)
        _retirer_table(elements, table)
        if table_ia:
            element = (
                rasteriser_region_sans_texte(page_pdf, table.bbox, media, dpi=dpi)
                if contient_texte_word
                else rasteriser_region(page_pdf, table.bbox, media, dpi=dpi)
            )
            if contient_texte_word:
                element.purpose = "audit-background"
            else:
                element.purpose = "audit-baked-visual"
            _inserer_visuel_recupere(elements, element)
        resultat.zones_visuelles_recuperees += 1


def _retirer_table(elements: list[object], table: TableEl) -> None:
    elements[:] = [element for element in elements if element is not table]


def _inserer_visuel_recupere(elements: list[object], element: RasterEl) -> None:
    for index, existant in enumerate(elements):
        if isinstance(existant, (TextBox, FlowParagraph)):
            elements.insert(index, element)
            return
    elements.append(element)


def _retirer_elements_dans_zone(elements: list[object], zone: BBox, *, retirer_texte: bool = True) -> None:
    elements[:] = [
        element
        for element in elements
        if not (
            isinstance(
                element,
                (TextBox, FlowParagraph, ImageEl, RasterEl, ShapeEl)
                if retirer_texte
                else (ImageEl, RasterEl, ShapeEl),
            )
            and _centre_dans_zone(element.bbox, zone)
        )
    ]


def appliquer_correction_avec_rollback(
    elements: list[object],
    zone: BBox,
    element: RasterEl,
    *,
    retirer_texte: bool,
    page_index: int = 0,
    reason: str = "local-visual-recovery",
) -> CorrectionLocale:
    """Applique une correction locale et conserve son état vérifiable.

    La liste d'éléments est remplacée seulement après construction complète du
    nouvel état. Une exception laisse donc l'état original intact; le compteur et
    les identifiants permettent ensuite à l'audit de décider d'un rollback global.
    """
    avant = list(elements)
    types_retirables = (
        (TextBox, FlowParagraph, ImageEl, RasterEl, ShapeEl)
        if retirer_texte
        else (ImageEl, RasterEl, ShapeEl)
    )
    conserves = [
        existant
        for existant in avant
        if not (
            isinstance(existant, types_retirables)
            and _centre_dans_zone(existant.bbox, zone)
        )
    ]
    try:
        insertion = next(
            (index for index, existant in enumerate(conserves) if isinstance(existant, (TextBox, FlowParagraph))),
            len(conserves),
        )
        conserves.insert(insertion, element)
        elements[:] = conserves
    except Exception:
        elements[:] = avant
        raise
    conserves_ids = {id(item) for item in conserves}
    return CorrectionLocale(
        page_index=page_index,
        action="insert-local-visual",
        reason=reason,
        removed_element_ids=[
            str(getattr(existant, "source_id", None) or f"{type(existant).__name__}:{index}")
            for index, existant in enumerate(avant)
            if id(existant) not in conserves_ids
        ],
        inserted_element_id=str(getattr(element, "source_id", None) or getattr(element, "media_ref", None)),
    )


def _zone_contient_texte_word(zone: BBox, elements: Sequence[object]) -> bool:
    touches = 0
    for element in elements:
        if isinstance(element, TextBox):
            lignes = element.lignes
        elif isinstance(element, FlowParagraph):
            lignes = element.lignes or []
            if not lignes and _centre_dans_zone(element.bbox, zone):
                return True
        else:
            continue
        for ligne in lignes:
            texte = "".join(span.texte for span in ligne.spans).strip()
            if not texte:
                continue
            if _centre_dans_zone(ligne.bbox, zone) or _ratio_intersection(ligne.bbox, zone) >= 0.10:
                touches += 1
                if touches >= 2:
                    return True
    return False


def _centre_dans_zone(bbox: BBox, zone: BBox) -> bool:
    return center_in(bbox, zone)


def _ratio_intersection(bbox: BBox, zone: BBox) -> float:
    return overlap_ratio(bbox, zone)


def _sequence_texte(texte: str) -> list[str]:
    """Normalisation identique source/sortie, sans perdre glyphes ni occurrences."""
    normalise = unicodedata.normalize("NFC", (texte or "").casefold())
    return _TOKENS_TEXTE.findall(normalise)


def _tokens_texte(texte: str) -> set[str]:
    """Presence seulement; cet ensemble ne prouve ni l'ordre ni la multiplicite."""
    return set(_sequence_texte(texte))


def _orientation_texte(element) -> str:
    orientation = str(getattr(element, "orientation", "horizontal") or "horizontal").casefold()
    if orientation == "horizontal":
        for ligne in getattr(element, "lignes", None) or []:
            candidate = str(getattr(ligne, "orientation", "horizontal") or "horizontal").casefold()
            if candidate != "horizontal":
                return candidate
    return orientation


def _texte_visible_dans_bbox(page, bbox: BBox) -> str:
    """Lit les glyphes du PDF rendu, y compris les textes tournes.

    ``get_text('words')`` est fiable pour le flux horizontal mais peut ne pas
    produire un mot pour une textbox tournee. Le niveau ``rawdict`` conserve
    alors les caracteres individuels et permet de controler la visibilite reelle.
    """
    rect = pymupdf.Rect(
        emu_vers_pt(bbox.x0) - 2,
        emu_vers_pt(bbox.y0) - 2,
        emu_vers_pt(bbox.x1) + 2,
        emu_vers_pt(bbox.y1) + 2,
    )
    texte = []
    try:
        donnees = page.get_text("rawdict", clip=rect)
        for bloc in donnees.get("blocks", []):
            for ligne in bloc.get("lines", []):
                fragments = []
                for span in ligne.get("spans", []):
                    for caractere in span.get("chars", []):
                        fragments.append(str(caractere.get("c", "")))
                    if not span.get("chars") and span.get("text"):
                        fragments.append(str(span.get("text", "")))
                texte.append("".join(fragments))
    except (AttributeError, KeyError, TypeError, ValueError):
        texte = []
    if not texte:
        try:
            texte.append(page.get_text("text", clip=rect))
        except (AttributeError, TypeError, ValueError):
            pass
    return "\n".join(texte)


def _tokens_visibles_dans_bbox(page, bbox: BBox) -> set[str]:
    return _tokens_texte(_texte_visible_dans_bbox(page, bbox))


def _texte_element(element) -> str:
    if isinstance(element, FlowParagraph):
        return element.texte or " ".join(
            "".join(span.texte for span in ligne.spans)
            for ligne in element.lignes
        )
    return " ".join(
        "".join(span.texte for span in ligne.spans)
        for ligne in getattr(element, "lignes", None) or []
    )


def _element_id_audit(element, page_index: int, index: int) -> str:
    return str(getattr(element, "source_id", None) or f"p{page_index + 1}-e{index + 1}")


def _mots_et_bbox_dans_zone(page, bbox: BBox) -> tuple[list[str], BBox | None]:
    rect = pymupdf.Rect(
        emu_vers_pt(bbox.x0) - 2,
        emu_vers_pt(bbox.y0) - 2,
        emu_vers_pt(bbox.x1) + 2,
        emu_vers_pt(bbox.y1) + 2,
    )
    tokens: list[str] = []
    boxes = []
    try:
        for word in page.get_text("words"):
            word_rect = pymupdf.Rect(word[0], word[1], word[2], word[3])
            if not word_rect.intersects(rect):
                continue
            tokens.extend(_sequence_texte(word[4]))
            boxes.append(
                BBox(
                    pt_vers_emu(word_rect.x0),
                    pt_vers_emu(word_rect.y0),
                    pt_vers_emu(word_rect.x1),
                    pt_vers_emu(word_rect.y1),
                )
            )
    except (AttributeError, TypeError, ValueError):
        pass
    # Raw spans preserve text split across PDF spans without inserting word breaks.
    sequence = _sequence_texte(_texte_visible_dans_bbox(page, bbox))
    return sequence or tokens, union_many(boxes)


def _lignes_sortie_dans_bbox(page, bbox: BBox) -> list[BBox]:
    """Retourne les lignes effectivement peintes dans une region source."""
    rect = pymupdf.Rect(
        emu_vers_pt(bbox.x0) - 2,
        emu_vers_pt(bbox.y0) - 2,
        emu_vers_pt(bbox.x1) + 2,
        emu_vers_pt(bbox.y1) + 2,
    )
    lignes: list[BBox] = []
    try:
        donnees = page.get_text("dict", clip=rect)
        for bloc in donnees.get("blocks", []):
            for ligne in bloc.get("lines", []):
                texte = "".join(
                    str(span.get("text", "") or "")
                    for span in ligne.get("spans", [])
                ).strip()
                if not texte:
                    continue
                boite = ligne.get("bbox")
                if not boite or len(boite) != 4:
                    continue
                lignes.append(
                    BBox(
                        pt_vers_emu(boite[0]),
                        pt_vers_emu(boite[1]),
                        pt_vers_emu(boite[2]),
                        pt_vers_emu(boite[3]),
                    )
                )
    except (AttributeError, KeyError, TypeError, ValueError):
        return []
    return sorted(lignes, key=lambda item: (item.y0, item.x0))


def _auditer_geometrie_texte(element, page_out) -> list[str]:
    """Contrôle les contraintes de composition qui ne sont pas visibles par tokens."""
    attendu = geometry_kind(element)
    if attendu == "rectangular-flow" or _orientation_texte(element) != "horizontal":
        return []
    lignes_source = [
        ligne
        for ligne in getattr(element, "lignes", None) or []
        if any(str(span.texte or "").strip() for span in ligne.spans)
    ]
    lignes_sortie = _lignes_sortie_dans_bbox(page_out, element.bbox)
    causes: list[str] = []
    if len(lignes_source) >= 2 and len(lignes_sortie) < max(1, len(lignes_source) // 2):
        causes.append("line-geometry-loss")
        return causes
    if not lignes_sortie:
        return causes
    if attendu == "exclusion-flow" and lignes_source:
        source_first = min(lignes_source, key=lambda item: item.y0)
        output_first = lignes_sortie[0]
        tolerance = pt_vers_emu(4.0)
        source_indented = source_first.bbox.x0 > element.bbox.x0 + tolerance
        output_indented = output_first.x0 > element.bbox.x0 + tolerance
        if source_indented != output_indented:
            causes.append("exclusion-geometry-mismatch")
    if attendu == "variable-width-flow" and len(lignes_source) >= 2:
        source_widths = [ligne.bbox.largeur for ligne in lignes_source[:-1]]
        output_widths = [ligne.largeur for ligne in lignes_sortie[:-1]]
        if source_widths and output_widths:
            source_range = max(source_widths) - min(source_widths)
            output_range = max(output_widths) - min(output_widths)
            if source_range > pt_vers_emu(4.0) and output_range <= pt_vers_emu(2.0):
                causes.append("variable-width-geometry-flattened")
    return causes


def construire_audit_elements(document: Document, pdf_docx, source_pdf=None) -> AuditReport:
    """Audite chaque texte source dans le rendu PDF du DOCX.

    Le score global reste une métrique secondaire. Un seul texte absent, orienté
    incorrectement ou hors de sa bbox produit un ``AuditRecord`` indépendant.
    """
    handle = pdf_docx if hasattr(pdf_docx, "page_count") else pymupdf.open(pdf_docx)
    fermer = handle is not pdf_docx
    source_handle = None
    fermer_source = False
    rapport = AuditReport()
    try:
        source_handle = source_pdf if hasattr(source_pdf, "page_count") else (
            pymupdf.open(source_pdf) if source_pdf is not None else None
        )
        fermer_source = source_handle is not None and source_handle is not source_pdf
        for output_index, page_source in enumerate(document.pages):
            page_index = page_source.index
            if output_index >= handle.page_count:
                for index, element in enumerate(page_source.elements):
                    rapport.records.append(
                        AuditRecord(
                            element_id=_element_id_audit(element, page_index, index),
                            page_index=page_index,
                            output_page_index=output_index,
                            kind=type(element).__name__,
                            expected_orientation=_orientation_texte(element),
                            expected_geometry=geometry_kind(element),
                            expected_alignment=block_alignment(element),
                            status="error",
                            causes=["output-page-missing"],
                        )
                    )
                if not page_source.elements:
                    rapport.records.append(AuditRecord(
                        element_id=f"p{page_index + 1}", page_index=page_index,
                        output_page_index=output_index, kind="Page", status="error",
                        causes=["output-page-missing"],
                    ))
                continue
            page_out = handle.load_page(output_index)
            for index, element in enumerate(page_source.elements):
                if not isinstance(element, (TextBox, FlowParagraph)):
                    if source_handle is None or not 0 <= page_index < source_handle.page_count:
                        continue
                    if not isinstance(element, (ImageEl, RasterEl, ShapeEl, TableEl)):
                        continue
                    score = _similarite_zone(
                        source_handle.load_page(page_index),
                        page_out,
                        element.bbox,
                        dpi=150,
                    )
                    causes = [] if score >= 0.90 else ["visual-region-difference"]
                    rapport.records.append(
                        AuditRecord(
                            element_id=_element_id_audit(element, page_index, index),
                            page_index=page_index,
                            output_page_index=output_index,
                            kind=type(element).__name__,
                            output_present=score >= 0.50,
                            token_recall=score,
                            token_precision=score,
                            visible=score >= 0.50,
                            editable=not isinstance(element, (ImageEl, RasterEl)),
                            status="ok" if score >= 0.90 else "error",
                            causes=causes,
                        )
                    )
                    continue
                texte = _texte_element(element).strip()
                attendus = _sequence_texte(texte)
                if not attendus:
                    continue
                trouves, bbox_sortie = _mots_et_bbox_dans_zone(page_out, element.bbox)
                occurrences_source, occurrences_sortie = Counter(attendus), Counter(trouves)
                communs = sum((occurrences_source & occurrences_sortie).values())
                recall = communs / len(attendus)
                precision = communs / len(trouves) if trouves else 0.0
                visible = bool(communs)
                sequence_matches = attendus == trouves
                occurrences_match = occurrences_source == occurrences_sortie
                causes = []
                if not occurrences_match:
                    causes.append("text-occurrence-mismatch")
                elif not sequence_matches:
                    causes.append("text-order-mismatch")
                style_mismatches = _comparer_style_texte(element, page_out) if visible else []
                bbox_drift_pt = 0.0
                if bbox_sortie is not None:
                    bbox_drift_pt = max(
                        abs(emu_vers_pt(getattr(element.bbox, side)) - emu_vers_pt(getattr(bbox_sortie, side)))
                        for side in ("x0", "y0", "x1", "y1")
                    )
                if not visible:
                    causes.append("text-not-visible")
                if recall < 0.80:
                    causes.append("text-recall-low")
                if bbox_sortie is not None and iou(element.bbox, bbox_sortie) < 0.50:
                    causes.append("bbox-divergence")
                if bbox_sortie is not None and iou(element.bbox, bbox_sortie) < 0.70:
                    causes.append("bbox-drift-strict")
                causes.extend(style_mismatches)
                causes.extend(_auditer_geometrie_texte(element, page_out))
                if _orientation_texte(element) != "horizontal" and not visible:
                    causes.append("orientation-not-rendered")
                status = (
                    "ok"
                    if visible and sequence_matches and recall >= 0.95 and not style_mismatches and not any(
                        cause in {
                            "line-geometry-loss",
                            "exclusion-geometry-mismatch",
                            "variable-width-geometry-flattened",
                        }
                        for cause in causes
                    ) and (bbox_sortie is None or iou(element.bbox, bbox_sortie) >= 0.70)
                    else "error"
                    if not sequence_matches or not visible or recall < 0.95 or style_mismatches or (bbox_sortie is not None and iou(element.bbox, bbox_sortie) < 0.70)
                    else "warning"
                )
                rapport.records.append(
                    AuditRecord(
                        element_id=_element_id_audit(element, page_index, index),
                        page_index=page_index,
                        output_page_index=output_index,
                        kind=type(element).__name__,
                        output_present=visible,
                        token_recall=recall,
                        token_precision=precision,
                        text_sequence_matches=sequence_matches,
                        text_occurrences_match=occurrences_match,
                        bbox_iou=iou(element.bbox, bbox_sortie) if bbox_sortie is not None else 0.0,
                        expected_orientation=_orientation_texte(element),
                        expected_geometry=geometry_kind(element),
                        expected_alignment=block_alignment(element),
                        visible=visible,
                        editable=not _texte_imprime_dans_visuel(element, page_source.elements),
                        bbox_drift_pt=bbox_drift_pt,
                        style_mismatches=style_mismatches,
                        occluded=not visible and bool(trouves),
                        status=status,
                        causes=causes,
                    )
                )
    finally:
        if fermer:
            handle.close()
        if fermer_source:
            source_handle.close()
    return rapport


def _taille_texte(element) -> float:
    tailles = [
        span.size_pt
        for ligne in getattr(element, "lignes", None) or []
        for span in getattr(ligne, "spans", None) or []
        if span.texte.strip()
    ]
    return max(tailles, default=float(getattr(element, "size_pt", 0.0) or 0.0))


def _normaliser_nom_style(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _sortie_styles(page, bbox: BBox) -> list[dict]:
    """Retourne les spans effectivement peints dans la region attendue."""
    rect = pymupdf.Rect(
        emu_vers_pt(bbox.x0) - 2,
        emu_vers_pt(bbox.y0) - 2,
        emu_vers_pt(bbox.x1) + 2,
        emu_vers_pt(bbox.y1) + 2,
    )
    styles: list[dict] = []
    try:
        donnees = page.get_text("dict", clip=rect)
        for bloc in donnees.get("blocks", []):
            for ligne in bloc.get("lines", []):
                for span in ligne.get("spans", []):
                    if str(span.get("text", "")).strip():
                        styles.append(span)
    except (AttributeError, TypeError, ValueError):
        return []
    return styles


def _comparer_style_texte(element, page_out) -> list[str]:
    attendus = [
        span
        for ligne in getattr(element, "lignes", None) or []
        for span in getattr(ligne, "spans", None) or []
        if str(span.texte or "").strip()
    ]
    if not attendus:
        return []
    sorties = _sortie_styles(page_out, element.bbox)
    if not sorties:
        return ["style-not-rendered"]
    erreurs: list[str] = []
    signatures_sortie = {
        (
            _normaliser_nom_style(item.get("font", "")),
            round(float(item.get("size", 0.0) or 0.0), 1),
            f"{int(item.get('color', 0)) & 0xFFFFFF:06X}",
        )
        for item in sorties
    }
    for attendu in attendus:
        expected_font = _normaliser_nom_style(getattr(attendu.police, "famille", ""))
        expected_size = round(float(getattr(attendu, "size_pt", 0.0) or 0.0), 1)
        expected_color = str(getattr(attendu, "couleur", "") or "").lstrip("#").upper()
        if expected_color == "":
            expected_color = "000000"
        if not any(
            (
                (not expected_font or not output_font or expected_font in output_font or output_font in expected_font)
                and abs(expected_size - output_size) <= 1.0
                and expected_color == output_color
            )
            for output_font, output_size, output_color in signatures_sortie
        ):
            erreurs.append("style-run-mismatch")
            break
    return erreurs


def _texte_imprime_dans_visuel(element, elements: Sequence[object]) -> bool:
    """Ignore les labels déjà présents dans une image/raster de la page."""
    role = str(getattr(element, "semantic_role", None) or "").casefold()
    if role in {"title", "subtitle", "heading", "caption", "credit"}:
        return False
    orientation = str(getattr(element, "orientation", "horizontal") or "horizontal")
    if orientation != "horizontal" or getattr(element, "curved", False):
        return False
    if _taille_texte(element) > 16.0:
        return False
    for visuel in elements:
        if not isinstance(visuel, (ImageEl, RasterEl)):
            continue
        if _ratio_couverture(element.bbox, visuel.bbox) >= 0.92:
            return True
    return False


def _auditer_structure_ir(document: Document, resultat: CertificationFinale) -> None:
    """Contrôle géométrique avant rendu, sans confondre décor et texte imprimé."""
    for page in document.pages:
        for element in page.elements:
            bbox = getattr(element, "bbox", None)
            if bbox is None:
                continue
            if (
                bbox.x0 < -pt_vers_emu(2)
                or bbox.y0 < -pt_vers_emu(2)
                or bbox.x1 > page.largeur_emu + pt_vers_emu(2)
                or bbox.y1 > page.hauteur_emu + pt_vers_emu(2)
            ):
                resultat.elements_hors_page += 1
                resultat.issues.append(
                    IssueCertificationFinale(
                        page=page.index + 1,
                        categorie="geometry",
                        message="élément IR hors des limites de la page",
                        bbox=[bbox.x0, bbox.y0, bbox.x1, bbox.y1],
                        severite="error",
                    )
                )


def auditer_overflow(document: Document) -> list[dict]:
    """Retourne les débordements source et les bboxes internes incohérentes."""
    diagnostics = []
    tolerance = pt_vers_emu(2)
    for page in document.pages:
        for index, element in enumerate(page.elements):
            bbox = getattr(element, "bbox", None)
            if bbox is None:
                continue
            if (
                bbox.x0 < -tolerance
                or bbox.y0 < -tolerance
                or bbox.x1 > page.largeur_emu + tolerance
                or bbox.y1 > page.hauteur_emu + tolerance
            ):
                diagnostics.append(
                    {
                        "page": page.index,
                        "element_id": _element_id_audit(element, page.index, index),
                        "kind": type(element).__name__,
                        "cause": "element-out-of-page",
                    }
                )
            for line in getattr(element, "lignes", None) or []:
                if line.bbox.x0 < bbox.x0 - tolerance or line.bbox.x1 > bbox.x1 + tolerance:
                    diagnostics.append(
                        {
                            "page": page.index,
                            "element_id": _element_id_audit(element, page.index, index),
                            "kind": type(element).__name__,
                            "cause": "line-out-of-container",
                        }
                    )
                    break
    return diagnostics


def auditer_z_order(document: Document) -> list[dict]:
    """Signale les couches ambiguës sans réordonner les éléments source."""
    diagnostics = []
    for page in document.pages:
        values = [getattr(element, "z_index", None) for element in page.elements]
        values = [value for value in values if value is not None]
        duplicates = {value for value in values if values.count(value) > 1}
        for value in sorted(duplicates):
            diagnostics.append(
                {"page": page.index, "z_order": value, "cause": "ambiguous-z-order"}
            )
    return diagnostics


def auditer_font_metrics(document: Document) -> list[dict]:
    """Vérifie les métriques impossibles avant comparaison typographique."""
    diagnostics = []
    for page in document.pages:
        for index, element in enumerate(page.elements):
            for line in getattr(element, "lignes", None) or []:
                for span in line.spans:
                    if span.texte.strip() and float(span.size_pt or 0) <= 0:
                        diagnostics.append(
                            {
                                "page": page.index,
                                "element_id": _element_id_audit(element, page.index, index),
                                "cause": "invalid-font-size",
                            }
                        )
    return diagnostics


def auditer_editability(document: Document, docx_path=None) -> list[dict]:
    """Diagnostic global seulement; le mapping XML par source reste indisponible."""
    if docx_path is None or not Path(docx_path).exists():
        return [{"cause": "docx-package-unavailable"}]
    try:
        import zipfile

        with zipfile.ZipFile(docx_path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return [{"cause": "docx-package-invalid"}]
    diagnostics = []
    expected = sum(
        1
        for page in document.pages
        for element in page.elements
        if isinstance(element, (TextBox, FlowParagraph)) and _texte_element(element).strip()
    )
    actual = len(re.findall(r"<w:t(?:\s|>)", xml))
    if expected and actual == 0:
        diagnostics.append({"cause": "no-editable-text-runs", "expected": expected})
    return diagnostics


def _compter_mots_pdf(pdf_doc) -> int:
    """Compte les mots d'un PDF rendu, depuis un chemin ou un handle ouvert."""
    ouvert = pdf_doc if hasattr(pdf_doc, "page_count") else pymupdf.open(pdf_doc)
    fermer = ouvert is not pdf_doc
    try:
        return sum(len(page.get_text("words")) for page in ouvert)
    finally:
        if fermer:
            ouvert.close()


def _auditer_texte_visible(document: Document, pdf_docx, resultat: CertificationFinale) -> None:
    """Vérifie que chaque texte éditable attendu a réellement un mot au rendu."""
    document_ouvert = pdf_docx if hasattr(pdf_docx, "page_count") else pymupdf.open(pdf_docx)
    fermer = document_ouvert is not pdf_docx
    try:
        for page_index, page in enumerate(document.pages):
            if page_index >= document_ouvert.page_count:
                continue
            page_out = document_ouvert.load_page(page_index)
            mots = page_out.get_text("words")
            for element in page.elements:
                if not isinstance(element, (TextBox, FlowParagraph)):
                    continue
                if _texte_imprime_dans_visuel(element, page.elements):
                    continue
                orientation = _orientation_texte(element)
                lignes = getattr(element, "lignes", None) or []
                if not lignes and isinstance(element, FlowParagraph):
                    lignes = [element]
                for ligne in lignes:
                    texte = "".join(span.texte for span in getattr(ligne, "spans", [])).strip()
                    if not texte and isinstance(ligne, FlowParagraph):
                        texte = ligne.texte.strip()
                    attendus = _tokens_texte(texte)
                    if not attendus:
                        continue
                    bbox = getattr(ligne, "bbox", element.bbox)
                    if orientation != "horizontal":
                        # Les mots verticaux ne sont pas toujours exposes par
                        # PyMuPDF dans get_text("words"). On lit les caracteres
                        # du rendu sans filtrer les alphabets ou les symboles.
                        trouves = _tokens_visibles_dans_bbox(page_out, bbox)
                        if attendus.isdisjoint(trouves):
                            resultat.textes_non_visibles += 1
                            resultat.issues.append(
                                IssueCertificationFinale(
                                    page=page.index + 1,
                                    categorie="text-vertical",
                                    message=f"texte oriente non visible au rendu: {texte[:80]}",
                                    bbox=[bbox.x0, bbox.y0, bbox.x1, bbox.y1],
                                    severite="error",
                                )
                            )
                        continue
                    rect = pymupdf.Rect(
                        emu_vers_pt(bbox.x0) - 2,
                        emu_vers_pt(bbox.y0) - 2,
                        emu_vers_pt(bbox.x1) + 2,
                        emu_vers_pt(bbox.y1) + 2,
                    )
                    trouves = set()
                    for mot in mots:
                        mot_rect = pymupdf.Rect(mot[0], mot[1], mot[2], mot[3])
                        if mot_rect.intersects(rect):
                            trouves.update(_tokens_texte(mot[4]))
                    if attendus.isdisjoint(trouves):
                        resultat.textes_non_visibles += 1
                        resultat.issues.append(
                            IssueCertificationFinale(
                                page=page.index + 1,
                                categorie="text",
                                message=f"texte non visible au rendu: {texte[:80]}",
                                bbox=[bbox.x0, bbox.y0, bbox.x1, bbox.y1],
                                severite="error",
                            )
                        )
    finally:
        if fermer:
            document_ouvert.close()


def _auditer_texte(source_pdf, pdf_docx, document: Document, resultat: CertificationFinale) -> None:
    with pymupdf.open(source_pdf) as src, pymupdf.open(pdf_docx) as out:
        source_total = 0
        converti_total = 0
        for sortie_index, page_doc in enumerate(document.pages):
            if page_doc.index < src.page_count:
                source_total += len(src.load_page(page_doc.index).get_text("words"))
            if sortie_index < out.page_count:
                converti_total += len(out.load_page(sortie_index).get_text("words"))
        resultat.mots_source = source_total
        resultat.mots_converti = converti_total
        if source_total == 0 and converti_total == 0:
            resultat.ratio_texte = 1.0
        elif source_total == 0 or converti_total == 0:
            resultat.ratio_texte = 0.0
        else:
            resultat.ratio_texte = min(converti_total / source_total, source_total / converti_total)
        if resultat.ratio_texte < 0.97:
            resultat.issues.append(
                IssueCertificationFinale(
                    page=0,
                    categorie="text",
                    message=f"couverture texte faible: {converti_total}/{source_total} mots",
                    severite="error",
                )
            )


def _auditer_similarite_zones_finales(
    doc_source,
    pdf_docx,
    document: Document,
    pages_layout: Sequence[LayoutAIPage],
    resultat: CertificationFinale,
    *,
    dpi: int,
    native_rewriter: bool = False,
) -> None:
    resultat.zones_visuelles_comparees = 0
    resultat.score_zone_visuelle_min = None
    with pymupdf.open(pdf_docx) as doc_converti:
        for sortie_index, (page_doc, page_layout) in enumerate(zip(document.pages, pages_layout, strict=False)):
            if page_doc.index >= doc_source.page_count or sortie_index >= doc_converti.page_count:
                continue
            page_pdf = doc_source.load_page(page_doc.index)
            page_convertie = doc_converti.load_page(sortie_index)
            for zone in page_layout.zones:
                zone_normale = _normaliser_zone_visuelle(zone, page_doc.largeur_emu, page_doc.hauteur_emu)
                if zone_normale is None or zone_normale.role not in _ROLES_VISUELS_RECUPERABLES:
                    continue
                score = _similarite_zone(page_pdf, page_convertie, zone_normale.bbox, dpi=dpi)
                resultat.zones_visuelles_comparees += 1
                resultat.score_zone_visuelle_min = (
                    score
                    if resultat.score_zone_visuelle_min is None
                    else min(resultat.score_zone_visuelle_min, score)
                )
                if score < _SEUIL_SIMILARITE_ZONE:
                    resultat.zones_visuelles_non_couvertes += 1
                    resultat.issues.append(
                        IssueCertificationFinale(
                            page=page_doc.index + 1,
                            categorie=zone_normale.role,
                            message=f"zone {zone_normale.label} encore différente après récupération: {score:.3f}",
                            bbox=[
                                zone_normale.bbox.x0,
                                zone_normale.bbox.y0,
                                zone_normale.bbox.x1,
                                zone_normale.bbox.y1,
                            ],
                            severite="error",
                        )
                    )


def _auditer_similarite_visuelle(source_pdf, pdf_docx, document: Document, resultat: CertificationFinale, *, dpi: int) -> None:
    scores = []
    with pymupdf.open(source_pdf) as src, pymupdf.open(pdf_docx) as out:
        for sortie_index, page_doc in enumerate(document.pages):
            if page_doc.index >= src.page_count or sortie_index >= out.page_count:
                continue
            scores.append(_similarite_page(src.load_page(page_doc.index), out.load_page(sortie_index), dpi=dpi))
    if scores:
        resultat.score_visuel_min = min(scores)
        if resultat.score_visuel_min < _SEUIL_SIMILARITE:
            resultat.issues.append(
                IssueCertificationFinale(
                    page=scores.index(resultat.score_visuel_min) + 1,
                    categorie="visual",
                    message=f"similarité visuelle faible: {resultat.score_visuel_min:.3f}",
                    severite="error",
                )
            )


def _exporter_docx_pdf(docx_produit) -> Path | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    racine = Path(mkdtemp(prefix="pdfexact-final-audit-"))
    dossier = racine / "out"
    profile = racine / "lo-profile"
    home = racine / "home"
    xdg_config = racine / "xdg-config"
    xdg_cache = racine / "xdg-cache"
    xdg_runtime = racine / "xdg-runtime"
    for chemin in (dossier, profile, home, xdg_config, xdg_cache, xdg_runtime):
        chemin.mkdir(parents=True, exist_ok=True)
    xdg_runtime.chmod(0o700)
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_RUNTIME_DIR": str(xdg_runtime),
        "SAL_USE_VCLPLUGIN": "svp",
        # Prevent LibreOffice/GSettings from touching the host runtime in CI or
        # a sandbox.  The rendered PDF is the audit input, never the user's
        # desktop profile.
        "GSETTINGS_BACKEND": "memory",
        "OOO_FORCE_DESKTOP": "none",
    }
    try:
        resultat = subprocess.run(
            [
                soffice,
                "--headless",
                "--norestore",
                "--nodefault",
                "--nolockcheck",
                "--nofirststartwizard",
                f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(dossier),
                str(Path(docx_produit).resolve()),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        shutil.rmtree(racine, ignore_errors=True)
        return None
    sortie = dossier / (Path(docx_produit).stem + ".pdf")
    if resultat.returncode != 0 or not sortie.exists():
        shutil.rmtree(racine, ignore_errors=True)
        return None
    return sortie


def _supprimer_fichier_temporaire(path: Path) -> None:
    shutil.rmtree(path.parent.parent, ignore_errors=True)


def _similarite_page(page_a, page_b, *, dpi: int) -> float:
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        return 1.0
    pix_a = page_a.get_pixmap(dpi=dpi, alpha=False)
    pix_b = page_b.get_pixmap(dpi=dpi, alpha=False)
    image_a = Image.frombytes("RGB", (pix_a.width, pix_a.height), pix_a.samples).convert("L")
    image_b = Image.frombytes("RGB", (pix_b.width, pix_b.height), pix_b.samples).convert("L")
    if image_a.size != image_b.size:
        image_b = image_b.resize(image_a.size)
    arr_a = np.asarray(image_a, dtype=np.float32)
    arr_b = np.asarray(image_b, dtype=np.float32)
    return max(0.0, 1.0 - float(np.mean(np.abs(arr_a - arr_b))) / 255.0)


def _similarite_zone(page_a, page_b, bbox: BBox, *, dpi: int) -> float:
    try:
        import numpy as np
        from PIL import Image
    except Exception:  # noqa: BLE001
        return 1.0
    rect_a = pymupdf.Rect(
        emu_vers_pt(bbox.x0),
        emu_vers_pt(bbox.y0),
        emu_vers_pt(bbox.x1),
        emu_vers_pt(bbox.y1),
    ).intersect(page_a.rect)
    rect_b = pymupdf.Rect(rect_a).intersect(page_b.rect)
    if rect_a.is_empty or rect_b.is_empty:
        return 0.0
    pix_a = page_a.get_pixmap(clip=rect_a, dpi=dpi, alpha=False)
    pix_b = page_b.get_pixmap(clip=rect_b, dpi=dpi, alpha=False)
    if pix_a.width <= 2 or pix_a.height <= 2 or pix_b.width <= 2 or pix_b.height <= 2:
        return 0.0
    image_a = Image.frombytes("RGB", (pix_a.width, pix_a.height), pix_a.samples).convert("L")
    image_b = Image.frombytes("RGB", (pix_b.width, pix_b.height), pix_b.samples).convert("L")
    if image_a.size != image_b.size:
        image_b = image_b.resize(image_a.size)
    arr_a = np.asarray(image_a, dtype=np.float32)
    arr_b = np.asarray(image_b, dtype=np.float32)
    return max(0.0, 1.0 - float(np.mean(np.abs(arr_a - arr_b))) / 255.0)


def _ratio_couverture(a: BBox, b: BBox) -> float:
    return overlap_ratio(a, b)


def _aire(bbox: BBox) -> int:
    return bbox_area(bbox)


def bbox_debug_pt(bbox: BBox) -> tuple[float, float, float, float]:
    return (emu_vers_pt(bbox.x0), emu_vers_pt(bbox.y0), emu_vers_pt(bbox.x1), emu_vers_pt(bbox.y1))
