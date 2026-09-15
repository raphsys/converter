"""Téléchargement contrôlé des polices manquantes.

Le fetcher ne télécharge pas depuis des miroirs arbitraires : sources déclarées dans le
manifest local, puis dépôt officiel Google Fonts pour les familles libres.
"""
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote
from urllib.request import Request, urlopen

from pdfexact.fontlib import (
    _cle_famille,
    _decouper_nom_postscript,
    _lire_noms_sfnt,
    _normaliser_style,
    _table_alias,
    normaliser_nom,
)

FICHIER_SOURCES = Path(__file__).parent / "data" / "font_sources.json"
EXTENSIONS_TELECHARGEABLES = {".ttf", ".otf", ".ttc"}


@dataclass(frozen=True)
class PoliceTelechargee:
    demandee: str
    fichier: Path
    source: str


@dataclass
class RapportTelechargement:
    telechargees: list[PoliceTelechargee] = field(default_factory=list)
    introuvables: list[str] = field(default_factory=list)
    erreurs: dict[str, str] = field(default_factory=dict)
    alias_utilises: dict[str, str] = field(default_factory=dict)


def cle_famille_police(nom_pdf: str) -> str:
    nom = normaliser_nom(nom_pdf).strip()
    famille, _style = _decouper_nom_postscript(nom)
    return _cle_famille(famille)


def _cles_sources_candidates(nom_pdf: str) -> list[tuple[str, str | None]]:
    cle = cle_famille_police(nom_pdf)
    candidates: list[tuple[str, str | None]] = []
    if cle:
        candidates.append((cle, None))

    familles, _styles = _table_alias()
    alias = familles.get(cle)
    if alias:
        cle_alias = re.sub(r"[^a-z0-9]", "", alias.lower())
        if cle_alias and cle_alias != cle:
            candidates.append((cle_alias, alias))
    return candidates


def _charger_sources_manifest() -> dict:
    try:
        return json.loads(FICHIER_SOURCES.read_text(encoding="utf-8")).get("sources", {})
    except (OSError, ValueError):
        return {}


def _sources_google_fonts(cle_famille: str, timeout: int = 30) -> list[dict]:
    sources = []
    for dossier, licence in (("ofl", "OFL-1.1"), ("apache", "Apache-2.0"), ("ufl", "UFL-1.0")):
        url_api = f"https://api.github.com/repos/google/fonts/contents/{dossier}/{quote(cle_famille)}"
        try:
            with urlopen(Request(url_api, headers={"User-Agent": "pdfexact-font-fetcher"}), timeout=timeout) as reponse:
                if getattr(reponse, "status", 200) >= 400:
                    continue
                entrees = json.loads(reponse.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for entree in entrees:
            nom = entree.get("name", "")
            suffixe = Path(nom).suffix.lower()
            if suffixe in EXTENSIONS_TELECHARGEABLES and entree.get("download_url"):
                sources.append(
                    {
                        "url": entree["download_url"],
                        "filename": nom,
                        "source": f"google-fonts/{dossier}",
                        "license": licence,
                    }
                )
    return sources


def _telecharger(url: str, destination: Path, timeout: int) -> Path:
    with urlopen(Request(url, headers={"User-Agent": "pdfexact-font-fetcher"}), timeout=timeout) as reponse:
        donnees = reponse.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(delete=False, suffix=destination.suffix, dir=destination.parent) as tmp:
        tmp.write(donnees)
        temporaire = Path(tmp.name)
    if _lire_noms_sfnt(temporaire) is None:
        temporaire.unlink(missing_ok=True)
        raise ValueError("fichier téléchargé non reconnu comme police sfnt")
    shutil.move(str(temporaire), destination)
    return destination


def _style_demande(nom_pdf: str) -> str:
    _famille, style = _decouper_nom_postscript(normaliser_nom(nom_pdf).strip())
    return style


def _style_source(source: dict) -> str | None:
    style = source.get("style")
    if style:
        return _normaliser_style(str(style))

    nom = Path(source.get("filename") or source.get("url", "")).stem
    if "-" not in nom:
        return None
    _famille, _, suffixe = nom.partition("-")
    return _normaliser_style(suffixe)


def _priorite_source(source: dict, style_demande: str) -> int:
    style = _style_source(source)
    if style is None:
        return 50
    if style == style_demande:
        return 0
    if style_demande == "medium italic" and style in {"italic", "regular"}:
        return 10 if style == "italic" else 20
    if style_demande == "medium" and style == "regular":
        return 10
    if style_demande == "bold italic" and style in {"bold", "italic", "regular"}:
        return {"bold": 10, "italic": 20, "regular": 30}[style]
    if style_demande == "italic" and style == "regular":
        return 10
    if style_demande == "bold" and style in {"medium", "regular"}:
        return 10 if style == "medium" else 20
    if style == "regular":
        return 40
    return 45


def _trier_sources_pour_style(sources: list[dict], style_demande: str) -> list[dict]:
    return sorted(enumerate(sources), key=lambda item: (_priorite_source(item[1], style_demande), item[0]))


def telecharger_polices_manquantes(
    noms_polices: list[str],
    destination: Path | str = "fonts/local",
    timeout: int = 30,
) -> RapportTelechargement:
    destination = Path(destination)
    manifest = _charger_sources_manifest()
    rapport = RapportTelechargement()
    traitees: set[str] = set()

    for nom in noms_polices:
        candidates = _cles_sources_candidates(nom)
        cle_originale = candidates[0][0] if candidates else ""
        style_demande = _style_demande(nom)
        cle_traitement = f"{cle_originale}:{style_demande}"
        if not cle_originale or cle_traitement in traitees:
            continue
        traitees.add(cle_traitement)

        sources = []
        alias_utilise = None
        for cle, alias in candidates:
            sources = list(manifest.get(cle, []))
            if not sources:
                try:
                    sources = _sources_google_fonts(cle, timeout=timeout)
                except Exception as erreur:  # noqa: BLE001
                    rapport.erreurs[nom] = str(erreur)
                    continue
            if sources:
                alias_utilise = alias
                break

        if not sources:
            rapport.introuvables.append(nom)
            continue

        telecharge = False
        for _position, source in _trier_sources_pour_style(sources, style_demande):
            url = source.get("url")
            if not url:
                continue
            filename = source.get("filename") or Path(url).name
            suffixe = Path(filename).suffix.lower()
            if suffixe not in EXTENSIONS_TELECHARGEABLES:
                continue
            cible = destination / filename
            try:
                if not cible.exists():
                    _telecharger(url, cible, timeout)
                rapport.telechargees.append(
                    PoliceTelechargee(nom, cible, source.get("source", url))
                )
                if alias_utilise is not None:
                    rapport.alias_utilises[nom] = alias_utilise
                telecharge = True
            except Exception as erreur:  # noqa: BLE001
                rapport.erreurs[nom] = str(erreur)
            if telecharge:
                break

        if not telecharge and nom not in rapport.erreurs:
            rapport.introuvables.append(nom)

    return rapport
