"""Représentation intermédiaire — le contrat entre extraction et rendu.

Les extracteurs produisent ces objets, le writer les consomme. Aucun des deux côtés ne
connaît l'autre. Toutes les dimensions sont en EMU, à l'exception de Span.size_pt, en
points, parce que Word exprime les corps de police en demi-points.
"""
from dataclasses import dataclass, field
from pathlib import Path as CheminFichier
from typing import Union

from pdfexact.geometry import BBox

# Attention : `Path` désigne ici un tracé vectoriel, pas un chemin de fichier — d'où
# l'import de pathlib sous le nom CheminFichier.
# Une commande de chemin : un opérateur et ses points, en EMU absolus.
# Opérateurs : "move", "line", "cubic", "quad", "close".
PathCommand = tuple[str, tuple[tuple[int, int], ...]]
Path = list[PathCommand]


@dataclass(frozen=True)
class FontAsset:
    """Une police du document, embarquée ou substituée par une police système.

    `font_id` est le nom PostScript relevé dans le PDF : c'est le seul point de jonction
    avec les spans, dont le dictionnaire ne porte aucun xref.
    """

    font_id: str
    famille: str
    donnees: bytes | None
    extension: str
    embarquee: bool
    # Fichier de police retrouvé par la bibliothèque. C'est lui qui fournit les métriques
    # réelles ; sans lui, on ne peut que retomber sur une approximation.
    chemin: CheminFichier | None = None
    reconnue: bool = False


@dataclass(frozen=True)
class FontRef:
    """Référence d'un span vers une police, avec son style."""

    font_id: str
    famille: str
    gras: bool
    italique: bool


@dataclass(frozen=True)
class MediaItem:
    """Un binaire à écrire dans word/media/."""

    media_ref: str
    donnees: bytes
    extension: str


@dataclass
class Span:
    texte: str
    police: FontRef
    size_pt: float
    couleur: str
    espacement_twips: int = 0
    lien: str | None = None
    invisible: bool = False
    souligne: bool = False
    barre: bool = False
    capitales: bool = False
    exposant: bool = False
    indice: bool = False
    surlignage: str | None = None


@dataclass
class Line:
    """Une ligne de texte. Devient une zone de texte OOXML à elle seule."""

    bbox: BBox
    spans: list[Span]
    hauteur_ligne_emu: int
    largeur_cible_emu: int
    alignement: str = "left"


@dataclass
class TextBox:
    """Bloc logique de texte. Regroupement seulement — le writer rend ligne par ligne."""

    bbox: BBox
    lignes: list[Line]


@dataclass
class FlowParagraph:
    """Paragraphe Word réel, dans le flux, reconstruit depuis des lignes OCR."""

    bbox: BBox
    texte: str
    police: FontRef
    size_pt: float
    couleur: str
    alignement: str = "left"
    retrait_gauche_emu: int = 0
    retrait_droite_emu: int = 0
    retrait_premiere_ligne_emu: int = 0
    espace_avant_emu: int = 0
    espace_apres_emu: int = 0
    interligne_emu: int = 0
    souligne: bool = False
    barre: bool = False
    capitales: bool = False
    surlignage: str | None = None


@dataclass
class ImageEl:
    bbox: BBox
    media_ref: str


@dataclass
class ShapeEl:
    bbox: BBox
    chemins: list[Path]
    remplissage: str | None
    contour: str | None
    epaisseur_emu: int
    pointilles: str | None = None
    alpha: float = 1.0


@dataclass
class RasterEl:
    """Région rastérisée en repli. Jamais produit par un extracteur."""

    bbox: BBox
    media_ref: str


@dataclass
class TableBorder:
    couleur: str = "000000"
    sz: int = 4
    visible: bool = True


@dataclass
class TableCell:
    bbox: BBox
    texte: str
    col_span: int = 1
    fond: str | None = None
    spans: list[Span] = field(default_factory=list)
    alignement: str = "center"
    bordures: dict[str, TableBorder] = field(default_factory=dict)


@dataclass
class TableRow:
    bbox: BBox
    cells: list[TableCell]


@dataclass
class TableEl:
    bbox: BBox
    rows: list[TableRow]
    col_widths_emu: list[int]
    police: FontRef
    size_pt: float
    couleur: str = "000000"
    bordure_couleur: str = "000000"
    bordure_sz: int = 4


@dataclass
class LinkZone:
    """Lien couvrant une zone sans texte. Les liens sur du texte vivent dans Span.lien."""

    bbox: BBox
    uri: str | None = None
    page_cible: int | None = None


Element = Union[TextBox, FlowParagraph, ImageEl, ShapeEl, RasterEl, TableEl, LinkZone]


@dataclass
class Page:
    index: int
    largeur_emu: int
    hauteur_emu: int
    elements: list[Element] = field(default_factory=list)


@dataclass
class Document:
    pages: list[Page] = field(default_factory=list)
    media: dict[str, MediaItem] = field(default_factory=dict)
    polices: dict[str, FontAsset] = field(default_factory=dict)
