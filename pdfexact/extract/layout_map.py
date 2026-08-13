"""Carte geometrique fine d'une page PDF.

La carte ne rend rien elle-meme. Elle sert de verite spatiale commune aux extracteurs :
chaque objet observe dans le PDF est ramene sur une grille de 0,1 mm, puis le mode
hybride peut recaler l'OCR sur les positions natives au lieu de faire confiance aux
boites OCR seules.
"""
from dataclasses import dataclass, field
from math import ceil, floor

from pdfexact.geometry import BBox, bbox_depuis_rect, pt_vers_emu, se_chevauchent, union

GRILLE_DIXIEME_MM_EMU = 3600


@dataclass(frozen=True)
class LayoutItem:
    kind: str
    bbox: BBox
    qbbox: BBox
    source: str
    z_index: int
    text: str = ""
    font_name: str | None = None
    size_pt: float | None = None
    color: int | tuple | None = None
    flags: int = 0


@dataclass
class PageLayoutMap:
    largeur_emu: int
    hauteur_emu: int
    grille_emu: int = GRILLE_DIXIEME_MM_EMU
    items: list[LayoutItem] = field(default_factory=list)

    def ajouter(
        self,
        kind: str,
        bbox: BBox,
        source: str,
        z_index: int = 0,
        text: str = "",
        font_name: str | None = None,
        size_pt: float | None = None,
        color: int | tuple | None = None,
        flags: int = 0,
    ) -> None:
        if bbox.largeur <= 0 or bbox.hauteur <= 0:
            return
        self.items.append(
            LayoutItem(
                kind=kind,
                bbox=_limiter_page(bbox, self.largeur_emu, self.hauteur_emu),
                qbbox=quantifier_bbox(bbox, self.grille_emu),
                source=source,
                z_index=z_index,
                text=text,
                font_name=font_name,
                size_pt=size_pt,
                color=color,
                flags=flags,
            )
        )

    def lignes_natives(self) -> list[LayoutItem]:
        return [item for item in self.items if item.kind == "native-line"]

    def lignes_visuelles_natives(self) -> list[LayoutItem]:
        return [item for item in self.items if item.kind == "native-visual-line"]

    def zones_visuelles(self, marge_pt: float = 1.0) -> list[BBox]:
        marge = pt_vers_emu(marge_pt)
        return [
            _limiter_page(
                BBox(
                    item.bbox.x0 - marge,
                    item.bbox.y0 - marge,
                    item.bbox.x1 + marge,
                    item.bbox.y1 + marge,
                ),
                self.largeur_emu,
                self.hauteur_emu,
            )
            for item in self.items
            if item.kind in {"image", "inline-image", "vector-raster", "formula"}
        ]

    def recaler_ligne_ocr(self, bbox: BBox, texte: str) -> BBox:
        """Retourne la meilleure boite PDF native pour une ligne OCR.

        Le texte OCR est souvent meilleur que le decodage PDF, mais sa boite est moins
        fiable. Quand une ligne native est geometriquement proche, on garde donc le texte
        OCR et on reprend la boite native exacte.
        """
        candidat_visuel = self._meilleure_ligne_visuelle_native(bbox, texte)
        if candidat_visuel is not None:
            return candidat_visuel
        candidat = self._meilleure_ligne_native(bbox, texte)
        if candidat is not None:
            return candidat.bbox
        return self.contraindre_bbox_texte(bbox, texte)

    def contraindre_bbox_texte(self, bbox: BBox, texte: str) -> BBox:
        bbox = _limiter_page(quantifier_bbox(bbox, self.grille_emu), self.largeur_emu, self.hauteur_emu)
        if len(texte.strip()) < 24:
            return bbox

        # Une ligne OCR longue qui touche presque le bord droit provoque des coupures
        # Word. On garde sa position gauche, mais on la contraint au cadre textuel PDF
        # inféré depuis les lignes natives fiables quand il existe.
        cadre = self._cadre_texte_natif()
        droite = cadre.x1 if cadre is not None else self.largeur_emu - pt_vers_emu(24)
        droite = min(droite + pt_vers_emu(8), self.largeur_emu - pt_vers_emu(6))
        if bbox.x1 > droite:
            bbox = BBox(bbox.x0, bbox.y0, max(bbox.x0 + 1, droite), bbox.y1)
        return bbox

    def touche_visuel(self, bbox: BBox, seuil: float = 0.10) -> bool:
        return any(_ratio_couverture(bbox, zone) >= seuil for zone in self.zones_visuelles())

    def proche_petit_visuel(self, bbox: BBox, marge_pt: float = 36.0) -> bool:
        marge = pt_vers_emu(marge_pt)
        zone_elargie = BBox(
            max(0, bbox.x0 - marge),
            max(0, bbox.y0 - marge),
            min(self.largeur_emu, bbox.x1 + marge),
            min(self.hauteur_emu, bbox.y1 + marge),
        )
        for item in self.items:
            if item.kind not in {"image", "inline-image", "vector-raster", "formula"}:
                continue
            if item.bbox.largeur > pt_vers_emu(120) or item.bbox.hauteur > pt_vers_emu(120):
                continue
            if se_chevauchent(zone_elargie, item.bbox):
                return True
        return False

    def contredit_texte_natif(self, bbox: BBox, texte: str) -> bool:
        """Vrai si une OCR courte occupe une ligne native d'un autre texte."""
        texte_compact = _compact(texte)
        if len(texte_compact) > 12:
            return False
        for item in self.lignes_natives():
            if _ratio_vertical(bbox, item.bbox) < 0.45:
                continue
            if _ratio_intersection(bbox, item.bbox) < 0.08:
                continue
            if _similarite_simple(texte_compact, _compact(item.text)) < 0.45:
                return True
        return False

    def _meilleure_ligne_native(self, bbox: BBox, texte: str) -> LayoutItem | None:
        meilleur: LayoutItem | None = None
        meilleur_score = 0.0
        centre_y = (bbox.y0 + bbox.y1) / 2
        centre_x = (bbox.x0 + bbox.x1) / 2
        texte_compact = _compact(texte)

        for item in self.lignes_natives():
            if item.bbox.hauteur <= 0:
                continue
            distance_y = abs(((item.bbox.y0 + item.bbox.y1) / 2) - centre_y)
            if distance_y > max(item.bbox.hauteur, bbox.hauteur) * 1.2:
                continue
            recouvrement = _ratio_intersection(bbox, item.bbox)
            recouvrement_y = _ratio_vertical(bbox, item.bbox)
            if recouvrement_y < 0.35:
                continue
            if abs(item.bbox.x0 - bbox.x0) > pt_vers_emu(18):
                continue

            distance_x = abs(((item.bbox.x0 + item.bbox.x1) / 2) - centre_x)
            proximite_x = 1.0 / (1.0 + distance_x / max(item.bbox.largeur, bbox.largeur, 1))
            similarite = _similarite_simple(texte_compact, _compact(item.text))
            if len(texte_compact) <= 8 and similarite < 0.55:
                continue
            if len(texte_compact) > 8 and similarite < 0.55:
                continue
            score = recouvrement * 3.0 + recouvrement_y + proximite_x + similarite
            if score > meilleur_score:
                meilleur = item
                meilleur_score = score

        return meilleur if meilleur_score >= 1.25 else None

    def _meilleure_ligne_visuelle_native(self, bbox: BBox, texte: str) -> BBox | None:
        meilleur: BBox | None = None
        meilleur_score = 0.0
        centre_x = (bbox.x0 + bbox.x1) / 2
        texte_compact = _compact(texte)
        texte_long = len(texte_compact) >= 45

        for item in self.lignes_visuelles_natives():
            recouvrement_y = _ratio_vertical(bbox, item.bbox)
            if recouvrement_y < 0.55:
                continue
            if item.bbox.largeur < bbox.largeur * 0.92:
                continue

            marge = pt_vers_emu(8)
            bord_gauche_proche = abs(item.bbox.x0 - bbox.x0) <= marge
            bord_droit_proche = abs(item.bbox.x1 - bbox.x1) <= marge
            meme_largeur = 0.80 <= bbox.largeur / max(item.bbox.largeur, 1) <= 1.20
            if not texte_long and not (bord_gauche_proche and bord_droit_proche and meme_largeur):
                continue

            if not item.bbox.x0 - marge <= centre_x <= item.bbox.x1 + marge:
                continue
            distance_x0 = abs(item.bbox.x0 - bbox.x0)
            score = recouvrement_y + 1.0 / (1.0 + distance_x0 / max(item.bbox.largeur, 1))
            if score > meilleur_score:
                x0 = item.bbox.x0 if bord_gauche_proche else bbox.x0
                x1 = max(item.bbox.x1, bbox.x1)
                meilleur = BBox(x0, item.bbox.y0, x1, item.bbox.y1)
                meilleur_score = score

        return meilleur if meilleur_score >= 1.15 else None

    def _cadre_texte_natif(self) -> BBox | None:
        lignes = [
            item.bbox
            for item in self.lignes_natives()
            if item.text.strip() and len(item.text.strip()) >= 8 and item.bbox.largeur > pt_vers_emu(20)
        ]
        if not lignes:
            return None
        cadre = lignes[0]
        for bbox in lignes[1:]:
            cadre = union(cadre, bbox)
        return cadre


def quantifier_bbox(bbox: BBox, grille_emu: int = GRILLE_DIXIEME_MM_EMU) -> BBox:
    """Quantifie en conservant l'enveloppe : floor en haut/gauche, ceil en bas/droite."""
    return BBox(
        floor(bbox.x0 / grille_emu) * grille_emu,
        floor(bbox.y0 / grille_emu) * grille_emu,
        max(floor(bbox.x0 / grille_emu) * grille_emu + 1, ceil(bbox.x1 / grille_emu) * grille_emu),
        max(floor(bbox.y0 / grille_emu) * grille_emu + 1, ceil(bbox.y1 / grille_emu) * grille_emu),
    )


def construire_layout_map(
    page,
    zones_visuelles: list[BBox] | None = None,
    dpi: int | None = None,
) -> PageLayoutMap:
    carte = PageLayoutMap(
        largeur_emu=pt_vers_emu(page.rect.width),
        hauteur_emu=pt_vers_emu(page.rect.height),
    )
    z_index = 0

    for zone in zones_visuelles or []:
        carte.ajouter("vector-raster", zone, "pipeline-visual-zone", z_index)
        z_index += 1

    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") == 0:
            for ligne in bloc.get("lines", []):
                texte = "".join(span.get("text", "") for span in ligne.get("spans", [])).strip()
                if texte:
                    premier_span = (ligne.get("spans") or [{}])[0]
                    carte.ajouter(
                        "native-line",
                        _bbox_depuis_liste(ligne["bbox"]),
                        "pymupdf-dict",
                        z_index,
                        text=texte,
                        font_name=premier_span.get("font"),
                        size_pt=float(premier_span.get("size", 0.0) or 0.0),
                        color=premier_span.get("color"),
                        flags=int(premier_span.get("flags", 0) or 0),
                    )
                    z_index += 1
        elif bloc.get("type") == 1:
            carte.ajouter(
                "inline-image",
                _bbox_depuis_liste(bloc.get("bbox", (0, 0, 0, 0))),
                "pymupdf-dict",
                z_index,
            )
            z_index += 1

    z_index = _ajouter_lignes_visuelles_natives(carte, z_index)

    for trace in page.get_texttrace():
        font_name = trace.get("font")
        size_pt = float(trace.get("size", 0.0) or 0.0)
        for code, _gid, _origine, boite_pt in trace.get("chars", ()):
            try:
                texte = chr(code)
            except (TypeError, ValueError):
                texte = ""
            carte.ajouter(
                "glyph",
                _bbox_depuis_liste(boite_pt),
                "pymupdf-texttrace",
                z_index,
                text=texte,
                font_name=font_name,
                size_pt=size_pt,
                color=trace.get("color"),
                flags=int(trace.get("flags", 0) or 0),
            )
            z_index += 1

    # Les images XRef sont ajoutées pour l'analyse spatiale. Le rendu réel continue de
    # passer par l'extracteur d'images, qui gère les médias et les orientations.
    try:
        for xref in sorted({entree[0] for entree in page.get_images(full=True)}):
            for rect in page.get_image_rects(xref):
                carte.ajouter("image", bbox_depuis_rect(rect), f"pymupdf-image:{xref}", z_index)
                z_index += 1
    except Exception:  # noqa: BLE001
        pass

    return carte


def _ajouter_lignes_visuelles_natives(carte: PageLayoutMap, z_index: int) -> int:
    """Fusionne les fragments PDF qui partagent la même ligne visuelle."""
    lignes = sorted(carte.lignes_natives(), key=lambda item: (item.bbox.y0, item.bbox.x0))
    groupes: list[list[LayoutItem]] = []
    for ligne in lignes:
        if not groupes:
            groupes.append([ligne])
            continue
        groupe = groupes[-1]
        reference = groupe[-1].bbox
        centre_delta = abs((ligne.bbox.y0 + ligne.bbox.y1) - (reference.y0 + reference.y1))
        meme_ligne = centre_delta <= max(ligne.bbox.hauteur, reference.hauteur) * 0.75
        if meme_ligne:
            groupe.append(ligne)
        else:
            groupes.append([ligne])

    for groupe in groupes:
        morceaux = sorted(groupe, key=lambda item: item.bbox.x0)
        bbox = morceaux[0].bbox
        for item in morceaux[1:]:
            bbox = union(bbox, item.bbox)
        texte = " ".join(item.text for item in morceaux if item.text.strip())
        if bbox.largeur < pt_vers_emu(20):
            continue
        premier = morceaux[0]
        carte.ajouter(
            "native-visual-line",
            bbox,
            "pymupdf-dict-merged-line",
            z_index,
            text=texte,
            font_name=premier.font_name,
            size_pt=premier.size_pt,
            color=premier.color,
            flags=premier.flags,
        )
        z_index += 1
    return z_index


def _bbox_depuis_liste(quadruplet) -> BBox:
    return BBox(
        pt_vers_emu(float(quadruplet[0])),
        pt_vers_emu(float(quadruplet[1])),
        pt_vers_emu(float(quadruplet[2])),
        pt_vers_emu(float(quadruplet[3])),
    )


def _limiter_page(bbox: BBox, largeur_emu: int, hauteur_emu: int) -> BBox:
    x0 = max(0, min(bbox.x0, largeur_emu - 1))
    y0 = max(0, min(bbox.y0, hauteur_emu - 1))
    x1 = max(x0 + 1, min(bbox.x1, largeur_emu))
    y1 = max(y0 + 1, min(bbox.y1, hauteur_emu))
    return BBox(x0, y0, x1, y1)


def _aire(bbox: BBox) -> int:
    return max(0, bbox.largeur) * max(0, bbox.hauteur)


def _ratio_intersection(a: BBox, b: BBox) -> float:
    if not se_chevauchent(a, b):
        return 0.0
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return (max(0, x1 - x0) * max(0, y1 - y0)) / max(min(_aire(a), _aire(b)), 1)


def _ratio_couverture(a: BBox, b: BBox) -> float:
    if not se_chevauchent(a, b):
        return 0.0
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    return (max(0, x1 - x0) * max(0, y1 - y0)) / max(_aire(a), 1)


def _ratio_vertical(a: BBox, b: BBox) -> float:
    intersection = max(0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return intersection / max(min(a.hauteur, b.hauteur), 1)


def _compact(texte: str) -> str:
    return "".join(c.lower() for c in texte if c.isalnum())


def _similarite_simple(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    prefixe = 0
    for gauche, droite in zip(a, b):
        if gauche != droite:
            break
        prefixe += 1
    return prefixe / max(min(len(a), len(b)), 1)
