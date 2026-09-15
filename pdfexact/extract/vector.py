"""Extraction des graphiques vectoriels et regroupement en clusters.

Les primitives de PyMuPDF se transposent une à une en commandes DrawingML. Rien n'est
approximé : ce qui n'est pas transposable relève du repli raster, décidé ici mais exécuté
dans pdfexact.fallback.
"""
from pdfexact.geometry import BBox, bbox_depuis_rect, pt_vers_emu, se_chevauchent, union
from pdfexact.ir import ShapeEl

SEUIL_CHEMINS_PAR_DEFAUT = 300


def _couleur_hexa(composantes) -> str | None:
    if not composantes:
        return None
    rouge, vert, bleu = (max(0, min(255, round(canal * 255))) for canal in composantes[:3])
    return f"{rouge:02X}{vert:02X}{bleu:02X}"


def _point(couple) -> tuple[int, int]:
    return (pt_vers_emu(couple[0]), pt_vers_emu(couple[1]))


def _point_transforme(couple, geometrie=None) -> tuple[int, int]:
    if geometrie is None:
        return _point(couple)
    import pymupdf

    point = pymupdf.Point(couple[0], couple[1]) * geometrie.rotation_matrix
    return _point((point.x, point.y))


def _chemin_depuis_item(item, geometrie=None) -> list:
    """Traduit une primitive PyMuPDF en commandes de chemin."""
    operateur = item[0]

    if operateur == "l":
        return [
            ("move", (_point_transforme(item[1], geometrie),)),
            ("line", (_point_transforme(item[2], geometrie),)),
        ]

    if operateur == "c":
        return [
            ("move", (_point_transforme(item[1], geometrie),)),
            (
                "cubic",
                (
                    _point_transforme(item[2], geometrie),
                    _point_transforme(item[3], geometrie),
                    _point_transforme(item[4], geometrie),
                ),
            ),
        ]

    if operateur == "re":
        rect = item[1]
        coins = [
            (rect.x0, rect.y0),
            (rect.x1, rect.y0),
            (rect.x1, rect.y1),
            (rect.x0, rect.y1),
        ]
        commandes = [("move", (_point_transforme(coins[0], geometrie),))]
        commandes += [("line", (_point_transforme(coin, geometrie),)) for coin in coins[1:]]
        commandes.append(("close", ()))
        return commandes

    if operateur == "qu":
        quad = item[1]
        sommets = [quad.ul, quad.ur, quad.lr, quad.ll]
        commandes = [("move", (_point_transforme((sommets[0].x, sommets[0].y), geometrie),))]
        commandes += [("line", (_point_transforme((s.x, s.y), geometrie),)) for s in sommets[1:]]
        commandes.append(("close", ()))
        return commandes

    return []


def _boite_rendable(rect, geometrie=None) -> BBox:
    """Une ligne parfaitement horizontale a une bbox plate : on lui donne une épaisseur."""
    boite = geometrie.bbox_depuis_rect_natif(rect) if geometrie else bbox_depuis_rect(rect)
    return BBox(
        boite.x0,
        boite.y0,
        max(boite.x1, boite.x0 + 1),
        max(boite.y1, boite.y0 + 1),
    )


def _formes_traits_larges_verticaux(dessin, geometrie=None) -> list[ShapeEl]:
    """Certains PDF encodent une verticale comme un mini trait horizontal tres epais."""
    width_pt = float(dessin.get("width") or 0)
    if width_pt <= 20:
        return []

    formes: list[ShapeEl] = []
    for item in dessin.get("items", []):
        if item[0] != "l":
            continue
        p0 = item[1]
        p1 = item[2]
        dx = abs(float(p1.x) - float(p0.x))
        dy = abs(float(p1.y) - float(p0.y))
        if dx > 2.5 or dy > 0.5:
            continue
        cx = (float(p0.x) + float(p1.x)) / 2
        cy = (float(p0.y) + float(p1.y)) / 2
        y0 = cy - width_pt / 2
        y1 = cy + width_pt / 2
        chemin = [
            ("move", (_point_transforme((cx, y0), geometrie),)),
            ("line", (_point_transforme((cx, y1), geometrie),)),
        ]
        points = [point for _commande, pts in chemin for point in pts]
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        formes.append(
            ShapeEl(
                bbox=BBox(min(x_values), min(y_values), max(x_values) + 1, max(y_values) + 1),
                chemins=[chemin],
                remplissage=None,
                contour=_couleur_hexa(dessin.get("color")),
                epaisseur_emu=pt_vers_emu(1.0),
                pointilles=None,
                alpha=float(dessin.get("fill_opacity", 1.0) or 1.0),
            )
        )
    return formes


def extraire_vectoriel(page, geometrie=None) -> list[ShapeEl]:
    """Retourne les formes vectorielles de la page, en EMU."""
    formes: list[ShapeEl] = []

    for dessin in page.get_drawings():
        traits_verticaux = _formes_traits_larges_verticaux(dessin, geometrie)
        if traits_verticaux:
            formes.extend(traits_verticaux)
            continue

        chemins = [
            commandes
            for commandes in (_chemin_depuis_item(item, geometrie) for item in dessin.get("items", []))
            if commandes
        ]
        if not chemins:
            continue

        dashes = dessin.get("dashes")
        width_pt = float(dessin.get("width") or 0)
        if width_pt > 20:
            width_pt = 1.0
        formes.append(
            ShapeEl(
                bbox=_boite_rendable(dessin["rect"], geometrie),
                chemins=chemins,
                remplissage=_couleur_hexa(dessin.get("fill")),
                contour=_couleur_hexa(dessin.get("color")),
                epaisseur_emu=pt_vers_emu(width_pt),
                pointilles="dash" if dashes and dashes != "[] 0" else None,
                alpha=float(dessin.get("fill_opacity", 1.0) or 1.0),
            )
        )

    return formes


def regrouper(formes: list[ShapeEl]) -> list[list[ShapeEl]]:
    """Regroupe les formes dont les boîtes se chevauchent, transitivement.

    Le repli raster s'applique à un groupe visuel entier : ne rastériser qu'une moitié
    d'un graphique produirait une couture visible.
    """
    clusters: list[tuple[BBox, list[ShapeEl]]] = []

    for forme in formes:
        touches = [
            index
            for index, (boite, _membres) in enumerate(clusters)
            if se_chevauchent(boite, forme.bbox)
        ]

        if not touches:
            clusters.append((forme.bbox, [forme]))
            continue

        boite_fusionnee = forme.bbox
        membres_fusionnes = [forme]
        for index in sorted(touches, reverse=True):
            boite, membres = clusters.pop(index)
            boite_fusionnee = union(boite_fusionnee, boite)
            membres_fusionnes = membres + membres_fusionnes
        clusters.append((boite_fusionnee, membres_fusionnes))

    return [membres for _boite, membres in clusters]


def boite_du_cluster(cluster: list[ShapeEl]) -> BBox:
    boite = cluster[0].bbox
    for forme in cluster[1:]:
        boite = union(boite, forme.bbox)
    return boite


def doit_rasteriser(
    cluster: list[ShapeEl],
    page_a_des_degrades: bool,
    seuil: int = SEUIL_CHEMINS_PAR_DEFAUT,
) -> bool:
    """Décide si un cluster dépasse ce que DrawingML restitue fidèlement.

    Deux critères seulement, tous deux observables sans interprétation : la présence d'un
    dégradé sur la page, et la densité de chemins. Un score appris serait moins
    explicable pour un gain nul — la règle suffit et se justifie.
    """
    if page_a_des_degrades:
        return True

    return sum(len(forme.chemins) for forme in cluster) > seuil
