"""Interface en ligne de commande."""
import argparse
import sys
from pathlib import Path

from pdfexact.extract.document import extraire
from pdfexact.extract.vector import SEUIL_CHEMINS_PAR_DEFAUT
from pdfexact.fontlib import construire, dossiers_par_defaut
from pdfexact.render.package import ecrire_docx
from pdfexact.report import Rapport


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
    verbose: bool = False,
) -> Rapport:
    """Convertit un PDF en docx. Retourne le rapport de conversion."""
    rapport = Rapport()
    destination = Path(destination)
    if destination.parent != Path("."):
        destination.parent.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"[1/4] Indexation des polices...", file=sys.stderr)
    dossiers = list(dossiers_par_defaut()) + [Path(d) for d in (dossiers_polices or [])]
    bibliotheque = construire(dossiers=dossiers)

    if verbose:
        print(f"[2/4] Extraction PDF -> IR: {source}", file=sys.stderr)
    if text_mode == "rapidocr" and ocr_layout in {"hybrid", "word-native"} and ocr_granularity == "word":
        ocr_granularity = "line"
        if verbose:
            print(f"      {ocr_layout}: granularité OCR forcée à line", file=sys.stderr)
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
        verbose=verbose,
        rapport=rapport,
    )
    if verbose:
        print(f"[3/4] Écriture DOCX: {destination}", file=sys.stderr)
    ecrire_docx(document, destination)
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
        help="moteur OCR demandé ; fastocr est installé mais ne fournit pas de boîtes locales",
    )
    analyseur.add_argument("--ocr-lang", default="eng", help="langue OCR, ex. eng ou fra")
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
        "--ocr-visible",
        action="store_true",
        help="rend la couche OCR visible pour debug au lieu de la masquer",
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

    try:
        if arguments.ocr_engine == "fastocr":
            raise ValueError(
                "fastocr est installé, mais ce paquet expose des API distantes sans "
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
            ocr_lang=arguments.ocr_lang,
            ocr_visible=arguments.ocr_visible,
            ocr_granularity=arguments.ocr_granularity,
            ocr_layout=arguments.ocr_layout,
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
