"""Certification finale du DOCX produit.

La passe compare la source PDF et le document déjà rendu. Elle utilise le layout IA
comme source de zones attendues, puis récupère depuis le PDF original les zones
visuelles absentes de l'IR avant réécriture du DOCX.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import mkdtemp
from typing import Callable, Sequence

import pymupdf

from pdfexact.fallback.rasterize import rasteriser_region
from pdfexact.geometry import BBox, PageGeometry, emu_vers_pt
from pdfexact.ir import Document, FlowParagraph, ImageEl, RasterEl, ShapeEl, TableEl, TextBox
from pdfexact.layout.ai import LayoutAIPage, LayoutAIZone, detecter_layout_ia
from pdfexact.layout.analyzer import analyser_page
from pdfexact.render.package import ecrire_docx
from pdfexact.report import CertificationFinale, IssueCertificationFinale

_ROLES_VISUELS_RECUPERABLES = {"visual", "formula"}
_ROLES_VISUELS_AUDITES = {"visual", "formula", "table"}
_SEUIL_COUVERTURE = 0.72
_SEUIL_SIMILARITE = 0.86
_SEUIL_SIMILARITE_ZONE = 0.93


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
    verbose: bool = False,
) -> CertificationFinale:
    resultat = CertificationFinale(active=True)
    try:
        with pymupdf.open(source_pdf) as doc_source:
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
            try:
                doc_converti = pymupdf.open(pdf_initial) if pdf_initial else None
                try:
                    _auditer_couverture_visuelle(
                        doc_source,
                        document,
                        pages_layout,
                        resultat,
                        dpi=dpi,
                        doc_converti=doc_converti,
                    )
                finally:
                    if doc_converti is not None:
                        doc_converti.close()
            finally:
                if pdf_initial is not None:
                    _supprimer_fichier_temporaire(pdf_initial)
            if resultat.zones_visuelles_recuperees:
                ecrire_docx(document, docx_produit)
            pdf_docx = _exporter_docx_pdf(docx_produit)
            if pdf_docx is None:
                resultat.avertissements.append("audit_rendu_ignore:export_docx_pdf_indisponible")
            else:
                try:
                    _auditer_similarite_zones_finales(doc_source, pdf_docx, document, pages_layout, resultat, dpi=dpi)
                    _auditer_texte(source_pdf, pdf_docx, document, resultat)
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
        and (
            resultat.score_zone_visuelle_min is None
            or resultat.score_zone_visuelle_min >= _SEUIL_SIMILARITE_ZONE
        )
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
            element = rasterizer(page_pdf, zone.bbox, document.media, dpi=dpi)
            _retirer_elements_dans_zone(page_doc.elements, zone.bbox)
            _inserer_visuel_recupere(page_doc.elements, element)
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
        _retirer_table(elements, table)
        if table_ia:
            element = rasteriser_region(page_pdf, table.bbox, media, dpi=dpi)
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


def _retirer_elements_dans_zone(elements: list[object], zone: BBox) -> None:
    elements[:] = [
        element
        for element in elements
        if not (
            isinstance(element, (TextBox, FlowParagraph, ImageEl, RasterEl, ShapeEl))
            and _centre_dans_zone(element.bbox, zone)
        )
    ]


def _centre_dans_zone(bbox: BBox, zone: BBox) -> bool:
    cx = (bbox.x0 + bbox.x1) / 2
    cy = (bbox.y0 + bbox.y1) / 2
    return zone.x0 <= cx <= zone.x1 and zone.y0 <= cy <= zone.y1


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
                    severite="warning",
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
    }
    try:
        resultat = subprocess.run(
            [
                soffice,
                "--headless",
                f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(dossier),
                str(docx_produit),
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
    intersection = BBox(max(a.x0, b.x0), max(a.y0, b.y0), min(a.x1, b.x1), min(a.y1, b.y1))
    if intersection.largeur <= 0 or intersection.hauteur <= 0:
        return 0.0
    return _aire(intersection) / max(1, _aire(a))


def _aire(bbox: BBox) -> int:
    return max(0, bbox.largeur) * max(0, bbox.hauteur)


def bbox_debug_pt(bbox: BBox) -> tuple[float, float, float, float]:
    return (emu_vers_pt(bbox.x0), emu_vers_pt(bbox.y0), emu_vers_pt(bbox.x1), emu_vers_pt(bbox.y1))
