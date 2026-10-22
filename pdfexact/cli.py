"""Interface en ligne de commande."""
import argparse
import os
import sys
from pathlib import Path

import pymupdf

from pdfexact.extract.document import extraire
from pdfexact.extract.fonts import collecter_polices
from pdfexact.extract.vector import SEUIL_CHEMINS_PAR_DEFAUT
from pdfexact.font_fetcher import telecharger_polices_manquantes
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.layout.text_comprehension import (
    configurer_fournisseur_comprehension_texte,
    contexte_comprehension_texte,
)
from pdfexact.layout.text_comprehension_ai import (
    creer_fournisseur_comprehension_texte_ai,
    creer_fournisseur_orientation_ai,
)
from pdfexact.extract.orientation import configurer_fournisseur_orientation
from pdfexact.render.native_contract import inspecter_docx_word_native, valider_contrat_word_native
from pdfexact.render.package import ecrire_docx
from pdfexact.report import CorrectionWordNative, DiagnosticWordNative, Rapport
from pdfexact.model_paths import resolve_ai_models_root


def analyser_pages(expression: str) -> list[int]:
    """Traduit « 1-3,7 » en indices 0-based [0, 1, 2, 6]."""
    indices: list[int] = []
    for morceau in expression.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if "-" in morceau:
            debut, _, fin = morceau.partition("-")
            premier, dernier = int(debut), int(fin)
            if premier > dernier:
                raise ValueError(f"intervalle inversé : {morceau}")
            indices.extend(range(premier - 1, dernier))
        else:
            indices.append(int(morceau) - 1)

    if any(index < 0 for index in indices):
        raise ValueError("les pages se numérotent à partir de 1")
    return indices


@contexte_comprehension_texte()
def convertir(
    source,
    destination,
    pages=None,
    dpi: int = 300,
    seuil_raster: int = SEUIL_CHEMINS_PAR_DEFAUT,
    strict: bool = False,
    dossiers_polices=None,
    rasteriser_pages: bool = False,
    text_mode: str = "spans",
    ocr_layer: bool = False,
    ocr_lang: str = "eng",
    ocr_visible: bool = False,
    ocr_granularity: str = "word",
    ocr_layout: str = "blocks",
    layout_ai: bool = True,
    layout_provider: str | None = None,
    layout_model: str | None = None,
    layout_model_root: str | None = None,
    layout_device: str | None = None,
    text_understanding_ai: bool = False,
    text_understanding_url: str | None = None,
    text_understanding_timeout: float = 3.0,
    text_orientation_ai: bool = False,
    text_orientation_url: str | None = None,
    text_orientation_timeout: float = 3.0,
    fetch_missing_fonts: bool = False,
    font_cache_dir: str = "fonts/local",
    final_audit: bool = False,
    final_audit_dpi: int = 120,
    native_rewriter: bool = False,
    verbose: bool = False,
    ai_models_root: str | None = None,
    ocr_language: str = "auto",
    experimental_local_text_understanding: bool = False,
) -> Rapport:
    """Convertit un PDF en docx. Retourne le rapport de conversion."""
    # Un endpoint configure est un engagement explicite du runtime : les
    # decisions semantiques et d'orientation passent alors automatiquement par
    # l'IA, meme si le drapeau historique n'a pas ete repete sur la commande.
    text_understanding_ai = text_understanding_ai or bool(
        os.environ.get("PDFEXACT_TEXT_UNDERSTANDING_URL", "").strip()
    )
    text_orientation_ai = text_orientation_ai or bool(
        os.environ.get("PDFEXACT_TEXT_ORIENTATION_URL", "").strip()
    )
    # ``word-native`` décrit le renderer final, pas seulement la granularité
    # OCR. L'option historique --native-rewriter reste acceptée, mais ne doit
    # plus être obligatoire pour obtenir réellement le document Word-native.
    native_rewriter = native_rewriter or (
        text_mode == "rapidocr" and ocr_layout == "word-native"
    )
    rapport = Rapport()
    destination = Path(destination)
    if destination.parent != Path("."):
        destination.parent.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"[1/4] Indexation des polices...", file=sys.stderr)
    dossiers = list(dossiers_par_defaut()) + [Path(d) for d in (dossiers_polices or [])]
    bibliotheque = construire(dossiers=dossiers)
    if fetch_missing_fonts and not rasteriser_pages:
        doc_polices = pymupdf.open(source)
        try:
            polices_source = collecter_polices(doc_polices, bibliotheque)
        finally:
            doc_polices.close()
        manquantes = [
            a.font_id
            for a in polices_source.values()
            if a.mode_resolution not in {"exact", "famille_style"}
        ]
        if manquantes:
            if verbose:
                print(f"      téléchargement polices: {', '.join(manquantes)}", file=sys.stderr)
            telechargement = telecharger_polices_manquantes(
                manquantes,
                destination=Path(font_cache_dir),
            )
            if verbose:
                for item in telechargement.telechargees:
                    alias = telechargement.alias_utilises.get(item.demandee)
                    suffixe = f" (alias libre: {alias})" if alias else ""
                    print(f"      police téléchargée: {item.demandee} -> {item.fichier}{suffixe}", file=sys.stderr)
                for nom in telechargement.introuvables:
                    print(f"      police introuvable en source libre: {nom}", file=sys.stderr)
                for nom, erreur in telechargement.erreurs.items():
                    print(f"      échec téléchargement police {nom}: {erreur}", file=sys.stderr)
            if telechargement.telechargees:
                dossiers = list(dict.fromkeys(dossiers + [Path(font_cache_dir)]))
                bibliotheque = construire(dossiers=dossiers)

    if verbose:
        print(f"[2/4] Extraction PDF -> IR: {source}", file=sys.stderr)
    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"} and ocr_granularity == "word":
        ocr_granularity = "line"
        if verbose:
            print(f"      {ocr_layout}: granularité OCR forcée à line", file=sys.stderr)
    provider_texte = creer_fournisseur_comprehension_texte_ai(
        url=text_understanding_url,
        timeout=text_understanding_timeout,
        model_root=(resolve_ai_models_root(ai_models_root if ai_models_root is not None else layout_model_root)
                    if ai_models_root is not None or layout_model_root is not None else None),
        experimental_local=experimental_local_text_understanding,
    )
    configurer_fournisseur_comprehension_texte(provider_texte, annoncer=True)
    provider_orientation = None
    if text_understanding_ai or text_orientation_ai:
        endpoint_orientation = text_orientation_url or text_understanding_url
        timeout_orientation = (
            text_orientation_timeout
            if text_orientation_ai
            else text_understanding_timeout
        )
        provider_orientation = creer_fournisseur_orientation_ai(
            url=endpoint_orientation,
            timeout=timeout_orientation,
        )
        configurer_fournisseur_orientation(provider_orientation)
        if verbose:
            statut = "active" if provider_orientation is not None else "inactive"
            print(f"      compréhension IA orientation: {statut}", file=sys.stderr)
    if verbose:
        diagnostics = getattr(provider_texte, "diagnostics", {})
        statut = (diagnostics.get("status") if isinstance(diagnostics, dict) else None) or (
            "configuree" if provider_texte is not None else "indisponible (repli geometrique)"
        )
        print(f"      compréhension IA intra-bloc: {statut}", file=sys.stderr)
    try:
        document = extraire(
            source,
            pages=pages,
            bibliotheque=bibliotheque,
            dpi=dpi,
            seuil_raster=seuil_raster,
            strict=strict,
            rasteriser_pages=rasteriser_pages,
            text_mode=text_mode,
            ocr_layer=ocr_layer,
            ocr_lang=ocr_lang,
            ocr_visible=ocr_visible,
            ocr_granularity=ocr_granularity,
            ocr_layout=ocr_layout,
            layout_ai=layout_ai,
            layout_provider=layout_provider,
            layout_model=layout_model,
            layout_model_root=layout_model_root if layout_model_root is not None else ai_models_root,
            layout_device=layout_device,
            verbose=verbose,
            rapport=rapport,
            ai_models_root=resolve_ai_models_root(ai_models_root if ai_models_root is not None else layout_model_root),
            ocr_language=ocr_language,
        )
        if verbose:
            print(f"[3/4] Écriture DOCX: {destination}", file=sys.stderr)
        if text_mode == "rapidocr" and ocr_layout == "word-native":
            contract = valider_contrat_word_native(document)
            if verbose and not contract.conforme:
                print(
                    "      contrat Word-native avant écriture: "
                    f"erreurs={len(contract.plan_errors) + len(contract.missing_bbox) + len(contract.unsupported_modes)}",
                    file=sys.stderr,
                )
        rewrite_result = ecrire_docx(document, destination, native_rewriter=native_rewriter)
        if verbose and rewrite_result is not None:
            diagnostic = rewrite_result.diagnostics
            print(
                "      réécriture Word-native: "
                f"flow={diagnostic.flow_paragraphs + diagnostic.positioned_flow_paragraphs}, "
                f"cadres ancrés={diagnostic.anchored_frames}, "
                f"cadres inline={diagnostic.inline_frames}, tables={diagnostic.real_tables}, "
                f"images ancrées={diagnostic.anchored_images}",
                file=sys.stderr,
            )
        if final_audit:
            if verbose:
                print("[3/4] Audit final IA + récupération: actif", file=sys.stderr)
            from pdfexact.final_audit import certifier_et_reparer

            rapport.certification_finale = certifier_et_reparer(
                source,
                destination,
                document,
                dpi=final_audit_dpi,
                layout_provider=layout_provider,
                layout_model=layout_model,
                layout_model_root=layout_model_root,
                layout_device=layout_device,
                native_rewriter=native_rewriter,
                verbose=verbose,
            )
    finally:
        if text_understanding_ai or text_orientation_ai:
            configurer_fournisseur_orientation(None)
    if text_mode == "rapidocr" and ocr_layout == "word-native":
        if native_rewriter and rewrite_result is not None:
            diagnostic = rewrite_result.diagnostics
            rapport.diagnostic_word_native = DiagnosticWordNative(
                conforme=diagnostic.conforme,
                paragraphes=diagnostic.direct_body_paragraphs,
                tableaux=diagnostic.real_tables,
                images=diagnostic.anchored_images,
                ancres=diagnostic.anchored_frames + diagnostic.anchored_images + diagnostic.anchored_shapes,
                ancres_derriere=0,
                frames=0,
                textboxes=diagnostic.anchored_frames + diagnostic.inline_frames,
                tableaux_positionnes=diagnostic.positioned_tables,
                runs_compresses=0,
                elements_manquants=list(diagnostic.missing_elements),
                elements_hors_page=list(diagnostic.out_of_page_elements),
                doublons_ignores=diagnostic.skipped_duplicates,
                risques_lecteur=list(diagnostic.reader_risks),
            )
            if verbose:
                statut = "OK" if diagnostic.conforme else "NON CONFORME"
                print(
                    "      audit Word-native réécrit: "
                    f"{statut}, body-p={diagnostic.direct_body_paragraphs}, "
                    f"cadres autorisés={diagnostic.anchored_frames + diagnostic.inline_frames}, "
                    f"manquants={len(diagnostic.missing_elements)}, "
                    f"hors-page={len(diagnostic.out_of_page_elements)}",
                    file=sys.stderr,
                )
        else:
            diagnostic = inspecter_docx_word_native(destination)
            conforme = diagnostic.conforme
            rapport.diagnostic_word_native = DiagnosticWordNative(
                conforme=conforme,
                paragraphes=diagnostic.paragraphes,
                tableaux=diagnostic.tableaux,
                images=diagnostic.images,
                ancres=diagnostic.ancres,
                ancres_derriere=diagnostic.ancres_derriere,
                frames=diagnostic.frames,
                textboxes=diagnostic.textboxes,
                tableaux_positionnes=diagnostic.tableaux_positionnes,
                runs_compresses=diagnostic.runs_compresses,
            )
            if verbose:
                statut = "OK" if conforme else "NON CONFORME"
                print(
                    "      contrat Word native page-exact: "
                    f"{statut}, frames={diagnostic.frames}, ancres={diagnostic.ancres}, "
                    f"textboxes éditables={diagnostic.textboxes}, tableaux positionnés={diagnostic.tableaux_positionnes}, "
                    f"runs compressés={diagnostic.runs_compresses}",
                    file=sys.stderr,
                )
    if verbose:
        print("[4/4] Conversion terminée.", file=sys.stderr)
    return rapport


def _analyseur() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="pdfexact",
        description="Convertit un PDF natif en DOCX visuellement fidèle.",
    )
    analyseur.add_argument("source", help="le PDF à convertir")
    analyseur.add_argument("destination", help="le .docx à produire")
    analyseur.add_argument("--pages", help="sélection de pages, par exemple 1-5,8")
    analyseur.add_argument(
        "--dpi", type=int, default=300, help="résolution des zones rastérisées"
    )
    analyseur.add_argument(
        "--raster-threshold",
        type=int,
        default=SEUIL_CHEMINS_PAR_DEFAUT,
        dest="seuil_raster",
        help="nombre de chemins déclenchant le repli raster",
    )
    analyseur.add_argument(
        "--font-dir",
        action="append",
        dest="dossiers_polices",
        metavar="CHEMIN",
        help="dossier de polices supplémentaire (répétable)",
    )
    analyseur.add_argument(
        "--fetch-missing-fonts",
        action="store_true",
        help="télécharge les polices libres manquantes depuis les sources autorisées",
    )
    analyseur.add_argument(
        "--font-cache-dir",
        default="fonts/local",
        help="dossier où placer les polices téléchargées",
    )
    analyseur.add_argument(
        "--strict", action="store_true", help="échoue au lieu de dégrader une page"
    )
    analyseur.add_argument(
        "--raster-pages",
        action="store_true",
        help="rend chaque page en image pleine page pour privilégier la fidélité visuelle",
    )
    analyseur.add_argument(
        "--visual-exact",
        "--exact",
        action="store_true",
        help=(
            "profil fidélité visuelle : comprend les blocs avec RapidOCR puis rend en "
            "hybrid ancré page par page ; c'est le mode recommandé pour l'aspect identique"
        ),
    )
    analyseur.add_argument(
        "--text-mode",
        choices=("spans", "glyphs", "glyph-images", "rapidocr"),
        default="spans",
        help="mode texte : spans rapide, glyphs Unicode, glyph-images visuel, rapidocr Word",
    )
    analyseur.add_argument(
        "--ocr-layer",
        action="store_true",
        help="ajoute une couche OCR positionnée, utile avec --raster-pages",
    )
    analyseur.add_argument(
        "--ocr-engine",
        choices=("tesseract", "fastocr"),
        default="tesseract",
        help="moteur de couche OCR ; fastocr n'est pas pris en charge localement",
    )
    analyseur.add_argument("--ocr-lang", "--ocr-language", default="auto",
                          help="RapidOCR: auto best-effort par région ou ru, zh, ja, ko, ru+ja ; couche Tesseract: eng/fra installés")
    analyseur.add_argument(
        "--ocr-granularity",
        choices=("line", "word", "char"),
        default="word",
        help="granularité RapidOCR en mode --text-mode rapidocr",
    )
    analyseur.add_argument(
        "--ocr-layout",
        choices=("blocks", "page", "reflow", "hybrid", "word-native"),
        default="blocks",
        help=(
            "organisation RapidOCR : blocs positionnés, page entière, vrais paragraphes "
            "Word, blocs hybrides page exacte, ou document Word natif éditable"
        ),
    )
    analyseur.add_argument(
        "--layout-ai",
        action="store_true",
        help="active la compréhension documentaire IA/fallback avant OCR/rendu",
    )
    analyseur.add_argument(
        "--no-layout-ai",
        action="store_true",
        help="désactive explicitement la compréhension documentaire IA/fallback",
    )
    analyseur.add_argument(
        "--layout-provider",
        default=None,
        help="provider layout IA, ex. paddlex",
    )
    analyseur.add_argument(
        "--layout-model",
        default=None,
        help="modèle layout IA, ex. ppstructurev3/PP-DocLayout_plus-L",
    )
    analyseur.add_argument(
        "--ai-models-root", default=None,
        help="racine IA commune locale (OCR, compréhension et layout), sans téléchargement",
    )
    analyseur.add_argument(
        "--layout-model-root",
        default=None,
        help="racine des modèles IA layout",
    )
    analyseur.add_argument(
        "--layout-device",
        default=None,
        help="device IA layout, ex. cpu/gpu",
    )
    analyseur.add_argument(
        "--experimental-local-text-understanding",
        action="store_true",
        help="active explicitement la compréhension Qwen locale expérimentale ; aucune garantie de qualité",
    )
    analyseur.add_argument(
        "--text-understanding-ai",
        action="store_true",
        help="active une IA locale optionnelle pour comprendre les lignes/blocs avant fusion",
    )
    analyseur.add_argument(
        "--text-understanding-url",
        default=None,
        help="endpoint HTTP JSON local pour la compréhension intra-bloc",
    )
    analyseur.add_argument(
        "--text-understanding-timeout",
        type=float,
        default=3.0,
        help="timeout par appel IA intra-bloc",
    )
    analyseur.add_argument(
        "--text-orientation-ai",
        action="store_true",
        help="active la compréhension IA sémantique des orientations et rôles de texte",
    )
    analyseur.add_argument(
        "--text-orientation-url",
        default=None,
        help="endpoint HTTP JSON local pour la compréhension sémantique de l'orientation",
    )
    analyseur.add_argument(
        "--text-orientation-timeout",
        type=float,
        default=3.0,
        help="timeout par appel IA d'orientation",
    )
    analyseur.add_argument(
        "--ocr-visible",
        action="store_true",
        help="rend la couche OCR visible pour debug au lieu de la masquer",
    )
    analyseur.add_argument(
        "--final-audit",
        action="store_true",
        help="compare le DOCX rendu à l'original et récupère les zones visuelles manquantes",
    )
    analyseur.add_argument(
        "--final-audit-dpi",
        type=int,
        default=120,
        help="résolution de l'audit final et des zones récupérées",
    )
    analyseur.add_argument(
        "--native-rewriter",
        action="store_true",
        help="reconstruit document.xml depuis l'IR avec paragraphes Word directs et cadres contrôlés",
    )
    analyseur.add_argument(
        "--verbose", "-v", action="store_true", help="affiche la progression détaillée"
    )
    analyseur.add_argument("--report", help="écrit le rapport JSON dans ce fichier")
    return analyseur


def main(argv=None) -> int:
    arguments = _analyseur().parse_args(argv)

    source = Path(arguments.source)
    if not source.exists():
        print(f"fichier introuvable : {source}", file=sys.stderr)
        return 2

    try:
        pages = analyser_pages(arguments.pages) if arguments.pages else None
    except ValueError as erreur:
        print(f"sélection de pages invalide : {erreur}", file=sys.stderr)
        return 2

    if arguments.visual_exact:
        arguments.text_mode = "rapidocr"
        arguments.ocr_layout = "hybrid"
        arguments.ocr_granularity = "line"
        if arguments.verbose:
            print(
                "[profil] fidélité visuelle : --text-mode rapidocr "
                "--ocr-layout hybrid --ocr-granularity line",
                file=sys.stderr,
            )
    # L'analyse de layout est une étape obligatoire du contrat universel.
    # L'option historique --no-layout-ai est conservée pour compatibilité de
    # parsing, mais elle ne peut plus retirer l'analyse; en cas d'indisponibilité
    # du moteur, document.py signale le warning et active son repli géométrique.
    arguments.layout_ai = True

    try:
        if arguments.ocr_engine == "fastocr":
            raise ValueError(
                "fastocr n'est pas pris en charge par cette installation et ne fournit pas de "
                "boîtes de mots locales ; utilisez --ocr-engine tesseract pour une "
                "couche positionnée"
            )
        rapport = convertir(
            source,
            Path(arguments.destination),
            pages=pages,
            dpi=arguments.dpi,
            seuil_raster=arguments.seuil_raster,
            strict=arguments.strict,
            dossiers_polices=arguments.dossiers_polices,
            rasteriser_pages=arguments.raster_pages,
            text_mode=arguments.text_mode,
            ocr_layer=arguments.ocr_layer,
            ocr_lang="eng" if arguments.ocr_lang == "auto" else arguments.ocr_lang,
            ocr_language=arguments.ocr_lang,
            ai_models_root=arguments.ai_models_root,
            ocr_visible=arguments.ocr_visible,
            ocr_granularity=arguments.ocr_granularity,
            ocr_layout=arguments.ocr_layout,
            layout_ai=True,
            layout_provider=arguments.layout_provider,
            layout_model=arguments.layout_model,
            layout_model_root=arguments.layout_model_root,
            layout_device=arguments.layout_device,
            text_understanding_ai=arguments.text_understanding_ai,
            experimental_local_text_understanding=arguments.experimental_local_text_understanding,
            text_understanding_url=arguments.text_understanding_url,
            text_understanding_timeout=arguments.text_understanding_timeout,
            text_orientation_ai=arguments.text_orientation_ai,
            text_orientation_url=arguments.text_orientation_url,
            text_orientation_timeout=arguments.text_orientation_timeout,
            fetch_missing_fonts=arguments.fetch_missing_fonts,
            font_cache_dir=arguments.font_cache_dir,
            final_audit=arguments.final_audit,
            final_audit_dpi=arguments.final_audit_dpi,
            native_rewriter=arguments.native_rewriter,
            verbose=arguments.verbose,
        )
    except Exception as erreur:  # noqa: BLE001 — la CLI rend un code, pas une trace
        print(f"échec de la conversion : {erreur}", file=sys.stderr)
        return 1

    print(rapport.resume())
    if arguments.report:
        rapport_path = Path(arguments.report)
        if rapport_path.parent != Path("."):
            rapport_path.parent.mkdir(parents=True, exist_ok=True)
        rapport_path.write_text(rapport.vers_json(), encoding="utf-8")

    if (
        arguments.final_audit
        and rapport.certification_finale is not None
        and not rapport.certification_finale.conforme
    ):
        print(
            "échec de certification visuelle : le DOCX n'est pas conforme ou "
            "n'a pas pu être rendu/audité",
            file=sys.stderr,
        )
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
