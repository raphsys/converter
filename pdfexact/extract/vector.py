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


def _chemin_depuis_item(item) -> list:
    """Traduit une primitive PyMuPDF en commandes de chemin."""
    operateur = item[0]

    if operateur == "l":
        return [("move", (_point(item[1]),)), ("line", (_point(item[2]),))]

    if operateur == "c":
        return [
            ("move", (_point(item[1]),)),
            ("cubic", (_point(item[2]), _point(item[3]), _point(item[4]))),
        ]

    if operateur == "re":
        rect = item[1]
        coins = [
            (rect.x0, rect.y0),
            (rect.x1, rect.y0),
            (rect.x1, rect.y1),
            (rect.x0, rect.y1),
        ]
        commandes = [("move", (_point(coins[0]),))]
        commandes += [("line", (_point(coin),)) for coin in coins[1:]]
        commandes.append(("close", ()))
        return commandes

    if operateur == "qu":
        quad = item[1]
        sommets = [quad.ul, quad.ur, quad.lr, quad.ll]
        commandes = [("move", (_point((sommets[0].x, sommets[0].y)),))]
        commandes += [("line", (_point((s.x, s.y)),)) for s in sommets[1:]]
        commandes.append(("close", ()))
        return commandes

    return []


def _boite_rendable(rect) -> BBox:
    """Une ligne parfaitement horizontale a une bbox plate : on lui donne une épaisseur."""
    boite = bbox_depuis_rect(rect)
    return BBox(
        boite.x0,
        boite.y0,
        max(boite.x1, boite.x0 + 1),
        max(boite.y1, boite.y0 + 1),
    )


def extraire_vectoriel(page) -> list[ShapeEl]:
    """Retourne les formes vectorielles de la page, en EMU."""
    formes: list[ShapeEl] = []

    for dessin in page.get_drawings():
        chemins = [
            commandes
            for commandes in (_chemin_depuis_item(item) for item in dessin.get("items", []))
            if commandes
        ]
        if not chemins:
            continue

        dashes = dessin.get("dashes")
        formes.append(
            ShapeEl(
                bbox=_boite_rendable(dessin["rect"]),
                chemins=chemins,
                remplissage=_couleur_hexa(dessin.get("fill")),
                contour=_couleur_hexa(dessin.get("color")),
                epaisseur_emu=pt_vers_emu(dessin.get("width") or 0),
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
