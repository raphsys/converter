"""Carte geometrique fine d'une page PDF.

La carte ne rend rien elle-meme. Elle sert de verite spatiale commune aux extracteurs :
chaque objet observe dans le PDF est ramene sur une grille de 0,1 mm, puis le mode
hybride peut recaler l'OCR sur les positions natives au lieu de faire confiance aux
boites OCR seules.
"""
from dataclasses import dataclass, field

import pymupdf

from pdfexact.geometry import (
    BBox,
    GRILLE_DIXIEME_MM_EMU,
    PageGeometry,
    bbox_depuis_rect,
    pt_vers_emu,
    quantifier_bbox,
    se_chevauchent,
    union,
)


@dataclass(frozen=True)
class LayoutSpan:
    text: str
    bbox: BBox
    font_name: str | None = None
    size_pt: float | None = None
    color: int | tuple | None = None
    flags: int = 0


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
    spans: tuple[LayoutSpan, ...] = ()


@dataclass(frozen=True)
class NativeTextReplacement:
    text: str
    bbox: BBox


@dataclass
class PageLayoutMap:
    largeur_emu: int
    hauteur_emu: int
    grille_emu: int = GRILLE_DIXIEME_MM_EMU
    items: list[LayoutItem] = field(default_factory=list)
    cadres_lecture_taxonomie: list[BBox] = field(default_factory=list)

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
        spans: tuple[LayoutSpan, ...] = (),
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
                spans=spans,
            )
        )

    def ajouter_cadre_lecture(self, bbox: BBox) -> None:
        bbox = _limiter_page(
            quantifier_bbox(bbox, self.grille_emu),
            self.largeur_emu,
            self.hauteur_emu,
        )
        if bbox.largeur < pt_vers_emu(20) or bbox.hauteur < pt_vers_emu(3):
            return
        self.cadres_lecture_taxonomie.append(bbox)

    def lignes_natives(self) -> list[LayoutItem]:
        return [item for item in self.items if item.kind == "native-line"]

    def lignes_visuelles_natives(self) -> list[LayoutItem]:
        return [item for item in self.items if item.kind == "native-visual-line"]

    def cadres_colonnes_natives(self) -> list[BBox]:
        return self._cadres_colonnes_natives()

    def cadres_lecture_natifs(self) -> list[BBox]:
        """Retourne les cadres de lecture effectifs de la page.

        Une colonne native peut contenir une image, un graphique ou une zone formule.
        Pour la reconstruction OCR, cette colonne doit alors être découpée en cadres
        de lecture au-dessus/en dessous de l'obstacle, sinon une ligne peut traverser
        l'image et se superposer aux autres colonnes.
        """
        return self._cadres_lecture_natifs()

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

    def remplacement_texte_natif(self, bbox: BBox, texte: str) -> NativeTextReplacement | None:
        """Restaure une ligne PDF native quand l'OCR a perdu une structure visible.

        Cas typique : les sommaires et listes de figures utilisent de longs leaders
        "-----" ou "....." entre le libelle et le numero. L'OCR lit souvent les mots et
        le numero, mais supprime le leader. Quand la ligne native confirme le meme
        contenu compact, on reprend cette ligne plus riche.
        """
        texte_compact = _compact(texte)
        if not texte_compact:
            return None

        meilleur: LayoutItem | None = None
        meilleur_score = 0.0
        for item in self.lignes_visuelles_natives() + self.lignes_natives():
            texte_natif = item.text.strip()
            if not texte_natif:
                continue
            if not _contient_leader(texte_natif) or _contient_leader(texte):
                continue
            if _ratio_vertical(bbox, item.bbox) < 0.50:
                continue
            if _ratio_horizontal(bbox, item.bbox) < 0.18 and _ratio_intersection(bbox, item.bbox) < 0.03:
                continue
            if not _texte_compatible(texte_compact, _compact(texte_natif)):
                continue
            gain = len(texte_natif) - len(texte)
            if gain < 8:
                continue
            score = _ratio_vertical(bbox, item.bbox) + _ratio_horizontal(bbox, item.bbox) + gain / 1000
            if score > meilleur_score:
                meilleur = item
                meilleur_score = score

        if meilleur is None:
            return None
        return NativeTextReplacement(text=meilleur.text.strip(), bbox=meilleur.bbox)

    def texte_natif_preferable(self, bbox: BBox, texte: str) -> str:
        remplacement = self.remplacement_texte_natif(bbox, texte)
        return remplacement.text if remplacement is not None else texte

    def contraindre_bbox_texte(self, bbox: BBox, texte: str) -> BBox:
        bbox = _limiter_page(quantifier_bbox(bbox, self.grille_emu), self.largeur_emu, self.hauteur_emu)

        # Une ligne OCR longue qui touche presque le bord droit provoque des coupures
        # Word. Sur les pages multi-colonnes, la limite fiable n'est pas le cadre global
        # mais le cadre de lecture natif dont part la ligne.
        cadre_lecture = self._cadre_lecture_pour_bbox(bbox)
        cadre_colonne = self._cadre_colonne_pour_bbox(bbox)
        if len(texte.strip()) < 24 and cadre_lecture is None and cadre_colonne is None:
            return bbox

        cadre = cadre_lecture or cadre_colonne or self._cadre_texte_natif()
        droite = cadre.x1 if cadre is not None else self.largeur_emu - pt_vers_emu(24)
        marge_droite = pt_vers_emu(2 if (cadre_lecture is not None or cadre_colonne is not None) else 8)
        droite = min(droite + marge_droite, self.largeur_emu - pt_vers_emu(6))
        if cadre_lecture is not None and bbox.x0 < cadre_lecture.x0 - pt_vers_emu(3):
            bbox = BBox(cadre_lecture.x0, bbox.y0, bbox.x1, bbox.y1)
        elif cadre_colonne is not None and bbox.x0 < cadre_colonne.x0 - pt_vers_emu(3):
            bbox = BBox(cadre_colonne.x0, bbox.y0, bbox.x1, bbox.y1)
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

    def _dans_zone_visuelle(self, bbox: BBox, zones: list[BBox]) -> bool:
        return any(
            _centre_dans(bbox, zone) or _ratio_couverture(bbox, zone) >= 0.30
            for zone in zones
        )

    def confirme_texte_natif(self, bbox: BBox, texte: str) -> bool:
        """Vrai quand la couche PDF native confirme que cette OCR est du texte.

        Cette preuve est plus forte que les heuristiques visuelles : un numéro de page,
        une entrée de sommaire ou un libellé sur fond coloré peut être court et proche
        d'un objet graphique, mais il doit rester du texte Word si le PDF contient les
        glyphes correspondants à cet endroit.
        """
        texte_compact = _compact(texte)
        if not texte_compact:
            return False

        for item in self.lignes_natives():
            if _ratio_vertical(bbox, item.bbox) < 0.35:
                continue
            if _ratio_horizontal(bbox, item.bbox) < 0.18 and _ratio_intersection(bbox, item.bbox) < 0.03:
                continue
            if _texte_compatible(texte_compact, _compact(item.text)):
                return True

        glyphes = [
            item
            for item in self.items
            if item.kind == "glyph"
            and item.text.strip()
            and _centre_dans(item.bbox, bbox)
        ]
        if not glyphes:
            return False
        glyphes.sort(key=lambda item: (item.bbox.y0, item.bbox.x0))
        texte_glyphes = _compact("".join(item.text for item in glyphes))
        if _texte_compatible(texte_compact, texte_glyphes):
            return True

        # Les petits marqueurs comme "5", "iii" ou "39" sont souvent isolés dans les
        # sommaires et pieds de page. La présence de glyphes natifs dans la même boîte
        # suffit à les préserver, même quand l'OCR ne donne pas exactement la même forme.
        return len(texte_compact) <= 4 and len(texte_glyphes) <= 6

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
        zones_visuelles = self.zones_visuelles(marge_pt=2.0)
        bbox_dans_visuel = self._dans_zone_visuelle(bbox, zones_visuelles)

        for item in self.lignes_natives():
            if item.bbox.hauteur <= 0:
                continue
            texte_item_compact = _compact(item.text)
            if (
                self._dans_zone_visuelle(item.bbox, zones_visuelles)
                and not bbox_dans_visuel
                and not _texte_compatible(texte_compact, texte_item_compact)
            ):
                continue
            distance_y = abs(((item.bbox.y0 + item.bbox.y1) / 2) - centre_y)
            if distance_y > max(item.bbox.hauteur, bbox.hauteur) * 1.2:
                continue
            recouvrement = _ratio_intersection(bbox, item.bbox)
            recouvrement_y = _ratio_vertical(bbox, item.bbox)
            if recouvrement_y < 0.35:
                continue
            distance_x = abs(((item.bbox.x0 + item.bbox.x1) / 2) - centre_x)
            proximite_x = 1.0 / (1.0 + distance_x / max(item.bbox.largeur, bbox.largeur, 1))
            similarite = _similarite_simple(texte_compact, texte_item_compact)
            if len(texte_compact) <= 8 and similarite < 0.55:
                continue
            if len(texte_compact) > 8 and similarite < 0.55:
                continue
            if (
                len(texte_compact) <= 12
                and abs(item.bbox.x0 - bbox.x0) > pt_vers_emu(18)
                and recouvrement < 0.10
            ):
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
        cadre_lecture = self._cadre_lecture_pour_bbox(bbox)
        cadre_colonne = self._cadre_colonne_pour_bbox(bbox)
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
                cadre = cadre_lecture or cadre_colonne
                if cadre is not None:
                    x0 = max(x0, cadre.x0)
                    x1 = min(x1, cadre.x1 + pt_vers_emu(2))
                meilleur = BBox(x0, item.bbox.y0, x1, item.bbox.y1)
                meilleur_score = score

        return meilleur if meilleur_score >= 1.15 else None

    def _cadre_lecture_pour_bbox(self, bbox: BBox) -> BBox | None:
        cadres = self._cadres_lecture_natifs()
        if not cadres:
            return None

        centre_y = (bbox.y0 + bbox.y1) // 2
        x_reference = bbox.x0 + min(max(bbox.largeur // 10, 0), pt_vers_emu(18))
        marge_x = pt_vers_emu(8)
        marge_y = pt_vers_emu(4)
        candidats = [
            cadre
            for cadre in cadres
            if cadre.x0 - marge_x <= x_reference <= cadre.x1 + marge_x
            and cadre.y0 - marge_y <= centre_y <= cadre.y1 + marge_y
        ]
        if candidats:
            return min(
                candidats,
                key=lambda cadre: (
                    abs(cadre.x0 - bbox.x0),
                    abs(((cadre.y0 + cadre.y1) // 2) - centre_y),
                ),
            )

        meilleur: BBox | None = None
        meilleur_score = 0.0
        for cadre in cadres:
            recouvrement_y = _ratio_vertical(bbox, cadre)
            recouvrement_x = _ratio_horizontal(bbox, cadre)
            if recouvrement_y < 0.12 or recouvrement_x < 0.12:
                continue
            score = recouvrement_y * 2.0 + recouvrement_x
            if score > meilleur_score:
                meilleur = cadre
                meilleur_score = score
        return meilleur or self._cadre_colonne_pour_bbox(bbox)

    def _cadre_colonne_pour_bbox(self, bbox: BBox) -> BBox | None:
        colonnes = self._cadres_colonnes_natives()
        if len(colonnes) < 2:
            return None

        # On choisit par l'origine de ligne, pas par le centre : une OCR trop large peut
        # traverser plusieurs colonnes et placer son centre dans le mauvais couloir.
        x_reference = bbox.x0 + min(max(bbox.largeur // 10, 0), pt_vers_emu(18))
        marge = pt_vers_emu(8)
        candidats = [
            colonne
            for colonne in colonnes
            if colonne.x0 - marge <= x_reference <= colonne.x1 + marge
        ]
        if candidats:
            return min(candidats, key=lambda colonne: abs(colonne.x0 - bbox.x0))

        meilleur: BBox | None = None
        meilleur_score = 0
        for colonne in colonnes:
            chevauchement = max(0, min(bbox.x1, colonne.x1) - max(bbox.x0, colonne.x0))
            if chevauchement > meilleur_score:
                meilleur = colonne
                meilleur_score = chevauchement
        return meilleur if meilleur_score > 0 else None

    def _cadres_lecture_natifs(self) -> list[BBox]:
        cadres_base = self._cadres_lecture_taxonomie()
        if cadres_base:
            cadres_base = self._completer_cadres_lecture_par_colonnes(cadres_base)
        else:
            cadres_base = self._cadres_colonnes_natives()
        if not cadres_base:
            cadre = self._cadre_texte_natif()
            cadres_base = [cadre] if cadre is not None else []
        if not cadres_base:
            return []

        obstacles = sorted(self.zones_visuelles(marge_pt=3.0), key=lambda boite: (boite.y0, boite.x0))
        hauteur_min = pt_vers_emu(12)
        largeur_min = pt_vers_emu(20)
        cadres: list[BBox] = []
        for cadre in cadres_base:
            segments = [cadre]
            for obstacle in obstacles:
                nouveaux: list[BBox] = []
                for segment in segments:
                    if not se_chevauchent(segment, obstacle):
                        nouveaux.append(segment)
                        continue
                    recouvrement_x = max(0, min(segment.x1, obstacle.x1) - max(segment.x0, obstacle.x0))
                    if recouvrement_x / max(segment.largeur, 1) < 0.25:
                        nouveaux.append(segment)
                        continue
                    haut = BBox(segment.x0, segment.y0, segment.x1, max(segment.y0, obstacle.y0))
                    bas = BBox(segment.x0, min(segment.y1, obstacle.y1), segment.x1, segment.y1)
                    bande_y0 = max(segment.y0, obstacle.y0)
                    bande_y1 = min(segment.y1, obstacle.y1)
                    gauche = BBox(segment.x0, bande_y0, max(segment.x0, obstacle.x0), bande_y1)
                    droite = BBox(min(segment.x1, obstacle.x1), bande_y0, segment.x1, bande_y1)
                    if haut.hauteur >= hauteur_min:
                        nouveaux.append(haut)
                    if gauche.largeur >= largeur_min and gauche.hauteur >= hauteur_min:
                        nouveaux.append(gauche)
                    if droite.largeur >= largeur_min and droite.hauteur >= hauteur_min:
                        nouveaux.append(droite)
                    if bas.hauteur >= hauteur_min:
                        nouveaux.append(bas)
                segments = nouveaux
            cadres.extend(
                segment
                for segment in segments
                if segment.largeur >= largeur_min and segment.hauteur >= hauteur_min
            )
        cadres.sort(key=lambda boite: (boite.x0, boite.y0))
        return cadres if len(cadres) >= len(cadres_base) else cadres_base

    def _completer_cadres_lecture_par_colonnes(self, cadres: list[BBox]) -> list[BBox]:
        colonnes = self._cadres_colonnes_natives()
        resultat = list(cadres)
        for colonne in colonnes:
            if any(
                _ratio_couverture(colonne, cadre) >= 0.65
                or _ratio_intersection(colonne, cadre) >= 0.65
                for cadre in resultat
            ):
                continue
            resultat.append(colonne)
        cadre_hors_taxonomie = self._cadre_lignes_natives_hors_cadres(resultat)
        if cadre_hors_taxonomie is not None and not any(
            _ratio_couverture(cadre_hors_taxonomie, cadre) >= 0.65
            for cadre in resultat
        ):
            resultat.append(cadre_hors_taxonomie)
        resultat.sort(key=lambda boite: (boite.x0, boite.y0))
        return resultat

    def _cadre_lignes_natives_hors_cadres(self, cadres: list[BBox]) -> BBox | None:
        zones_visuelles = self.zones_visuelles(marge_pt=2.0)
        lignes: list[BBox] = []
        for item in self.lignes_natives():
            texte = item.text.strip()
            if len(texte) < 2:
                continue
            if self._dans_zone_visuelle(item.bbox, zones_visuelles):
                continue
            centre_x = (item.bbox.x0 + item.bbox.x1) // 2
            centre_y = (item.bbox.y0 + item.bbox.y1) // 2
            if any(
                cadre.x0 <= centre_x <= cadre.x1 and cadre.y0 <= centre_y <= cadre.y1
                for cadre in cadres
            ):
                continue
            lignes.append(item.bbox)
        if len(lignes) < 8:
            return None

        cadre = lignes[0]
        for bbox in lignes[1:]:
            cadre = union(cadre, bbox)
        if cadre.largeur < pt_vers_emu(20) or cadre.hauteur < pt_vers_emu(24):
            return None
        return cadre

    def _cadres_lecture_taxonomie(self) -> list[BBox]:
        cadres: list[BBox] = []
        vus = set()
        for bbox in self.cadres_lecture_taxonomie:
            bbox = _limiter_page(
                quantifier_bbox(bbox, self.grille_emu),
                self.largeur_emu,
                self.hauteur_emu,
            )
            if bbox.largeur < pt_vers_emu(20) or bbox.hauteur < pt_vers_emu(3):
                continue
            cle = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            if cle in vus:
                continue
            vus.add(cle)
            cadres.append(bbox)
        cadres.sort(key=lambda boite: (boite.x0, boite.y0))
        return cadres

    def _cadres_colonnes_natives(self) -> list[BBox]:
        cadres_taxonomie = self._cadres_lecture_taxonomie()
        if len(cadres_taxonomie) >= 2:
            return cadres_taxonomie

        largeur_page = max(self.largeur_emu, 1)
        hauteur_page = max(self.hauteur_emu, 1)
        largeur_min = pt_vers_emu(28)
        zones_visuelles = self.zones_visuelles(marge_pt=2.0)
        lignes = [
            item.bbox
            for item in self.lignes_natives()
            if item.text.strip()
            and len(item.text.strip()) >= 8
            and item.bbox.largeur >= largeur_min
            and item.bbox.largeur <= largeur_page * 0.62
            and item.bbox.hauteur <= hauteur_page * 0.06
            and not self._dans_zone_visuelle(item.bbox, zones_visuelles)
        ]
        if len(lignes) < 6:
            return []

        clusters: list[BBox] = []
        tolerance = pt_vers_emu(20)
        for bbox in sorted(lignes, key=lambda boite: (boite.x0, boite.x1)):
            meilleur_index: int | None = None
            meilleur_score = 0
            for index, cluster in enumerate(clusters):
                chevauchement = max(0, min(bbox.x1, cluster.x1) - max(bbox.x0, cluster.x0))
                meme_ancrage = abs(bbox.x0 - cluster.x0) <= tolerance
                proche = bbox.x0 <= cluster.x1 + tolerance and cluster.x0 <= bbox.x1 + tolerance
                if chevauchement > meilleur_score or (meilleur_score == 0 and meme_ancrage and proche):
                    meilleur_index = index
                    meilleur_score = chevauchement
            if meilleur_index is None:
                clusters.append(bbox)
                continue
            clusters[meilleur_index] = union(clusters[meilleur_index], bbox)

        colonnes = [
            cluster
            for cluster in clusters
            if cluster.largeur >= largeur_min
            and cluster.hauteur >= pt_vers_emu(24)
            and cluster.largeur <= largeur_page * 0.72
        ]
        colonnes.sort(key=lambda boite: boite.x0)
        if len(colonnes) < 2:
            return []
        return colonnes

    def _cadre_texte_natif(self) -> BBox | None:
        zones_visuelles = self.zones_visuelles(marge_pt=2.0)
        lignes = [
            item.bbox
            for item in self.lignes_natives()
            if item.text.strip() and len(item.text.strip()) >= 8 and item.bbox.largeur > pt_vers_emu(20)
            and not self._dans_zone_visuelle(item.bbox, zones_visuelles)
        ]
        if not lignes:
            return None
        cadre = lignes[0]
        for bbox in lignes[1:]:
            cadre = union(cadre, bbox)
        return cadre


def construire_layout_map(
    page,
    zones_visuelles: list[BBox] | None = None,
    cadres_lecture: list[BBox] | None = None,
    dpi: int | None = None,
    geometrie: PageGeometry | None = None,
) -> PageLayoutMap:
    geometrie = geometrie or PageGeometry.depuis_page(page)
    carte = PageLayoutMap(
        largeur_emu=geometrie.largeur_emu,
        hauteur_emu=geometrie.hauteur_emu,
    )
    z_index = 0

    for cadre_lecture in cadres_lecture or []:
        carte.ajouter_cadre_lecture(cadre_lecture)

    for zone in zones_visuelles or []:
        carte.ajouter("vector-raster", zone, "pipeline-visual-zone", z_index)
        z_index += 1

    for bloc in page.get_text("dict").get("blocks", []):
        if bloc.get("type") == 0:
            for ligne in bloc.get("lines", []):
                texte = "".join(span.get("text", "") for span in ligne.get("spans", [])).strip()
                if texte:
                    premier_span = (ligne.get("spans") or [{}])[0]
                    spans = tuple(
                        LayoutSpan(
                            text=span.get("text", ""),
                            bbox=_bbox_depuis_liste(span.get("bbox", ligne["bbox"]), geometrie),
                            font_name=span.get("font"),
                            size_pt=float(span.get("size", 0.0) or 0.0),
                            color=span.get("color"),
                            flags=int(span.get("flags", 0) or 0),
                        )
                        for span in ligne.get("spans", [])
                        if span.get("text", "") != ""
                    )
                    carte.ajouter(
                        "native-line",
                        _bbox_depuis_liste(ligne["bbox"], geometrie),
                        "pymupdf-dict",
                        z_index,
                        text=texte,
                        font_name=premier_span.get("font"),
                        size_pt=float(premier_span.get("size", 0.0) or 0.0),
                        color=premier_span.get("color"),
                        flags=int(premier_span.get("flags", 0) or 0),
                        spans=spans,
                    )
                    z_index += 1
        elif bloc.get("type") == 1:
            carte.ajouter(
                "inline-image",
                _bbox_depuis_liste(bloc.get("bbox", (0, 0, 0, 0)), geometrie),
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
                _bbox_depuis_liste(boite_pt, geometrie),
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
                carte.ajouter(
                    "image",
                    geometrie.bbox_depuis_rect_natif(rect),
                    f"pymupdf-image:{xref}",
                    z_index,
                )
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
        ecart_horizontal = ligne.bbox.x0 - reference.x1
        rupture_horizontale = ecart_horizontal > max(
            pt_vers_emu(18),
            max(ligne.bbox.hauteur, reference.hauteur) * 2,
        )
        if meme_ligne and not rupture_horizontale:
            groupe.append(ligne)
        else:
            groupes.append([ligne])

    for groupe in groupes:
        morceaux = sorted(groupe, key=lambda item: item.bbox.x0)
        bbox = morceaux[0].bbox
        for item in morceaux[1:]:
            bbox = union(bbox, item.bbox)
        texte = " ".join(item.text for item in morceaux if item.text.strip())
        spans = tuple(span for item in morceaux for span in item.spans)
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
            spans=spans,
        )
        z_index += 1
    return z_index


def _bbox_depuis_liste(quadruplet, geometrie: PageGeometry | None = None) -> BBox:
    rect = pymupdf.Rect(
        float(quadruplet[0]),
        float(quadruplet[1]),
        float(quadruplet[2]),
        float(quadruplet[3]),
    )
    if geometrie is not None:
        return geometrie.bbox_depuis_rect_natif(rect)
    return bbox_depuis_rect(rect)


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


def _ratio_horizontal(a: BBox, b: BBox) -> float:
    intersection = max(0, min(a.x1, b.x1) - max(a.x0, b.x0))
    return intersection / max(min(a.largeur, b.largeur), 1)


def _centre_dans(bbox: BBox, zone: BBox) -> bool:
    x = (bbox.x0 + bbox.x1) // 2
    y = (bbox.y0 + bbox.y1) // 2
    return zone.x0 <= x <= zone.x1 and zone.y0 <= y <= zone.y1


def _compact(texte: str) -> str:
    return "".join(c.lower() for c in texte if c.isalnum())


def _contient_leader(texte: str) -> bool:
    compteur = 0
    for caractere in texte:
        if caractere in ".-_":
            compteur += 1
            if compteur >= 6:
                return True
        else:
            compteur = 0
    return False


def _texte_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    seuil = 0.55 if max(len(a), len(b)) > 4 else 0.45
    return _similarite_simple(a, b) >= seuil


def _similarite_simple(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    prefixe = 0
    for gauche, droite in zip(a, b):
        if gauche != droite:
            break
        prefixe += 1
    return prefixe / max(min(len(a), len(b)), 1)
