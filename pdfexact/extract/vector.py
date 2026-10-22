"""Extraction des graphiques vectoriels et regroupement en clusters.

Les primitives de PyMuPDF se transposent une à une en commandes DrawingML. Rien n'est
approximé : ce qui n'est pas transposable relève du repli raster, décidé ici mais exécuté
dans pdfexact.fallback.
"""
from pdfexact.geometry import BBox, PageGeometry, bbox_depuis_rect, pt_vers_emu, se_chevauchent, union
from pdfexact.ir import ShapeEl
from pdfexact.extract.images import (
    _graphic_paint_operations,
    _graphic_requires_raster,
    _rectangular_fill,
    _visible_paint_rect,
)

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
                z_index=dessin.get("seqno"),
            )
        )
    return formes


def _paint_commands(operation, geometrie=None):
    import pymupdf

    m = pymupdf.mupdf
    ctm = operation["ctm"]
    matrix = pymupdf.Matrix(ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f)

    class Walker(m.FzPathWalker2):
        def __init__(self):
            super().__init__()
            self.commands = []
            for name in ("moveto", "lineto", "curveto", "closepath"):
                getattr(self, "use_virtual_" + name)()

        def point(self, x, y):
            point = pymupdf.Point(x, y) * matrix
            return _point_transforme(point, geometrie)

        def moveto(self, ctx, x, y):
            self.commands.append(("move", (self.point(x, y),)))

        def lineto(self, ctx, x, y):
            self.commands.append(("line", (self.point(x, y),)))

        def curveto(self, ctx, x1, y1, x2, y2, x3, y3):
            self.commands.append(("cubic", (self.point(x1, y1), self.point(x2, y2), self.point(x3, y3))))

        def closepath(self, ctx):
            self.commands.append(("close", ()))

    walker = Walker()
    m.fz_walk_path(operation["path"], walker, walker.m_internal)
    return walker.commands


def _formes_depuis_peinture(operations, geometrie):
    import pymupdf

    formes = []
    for operation in operations:
        if operation["kind"] not in {"fill_path", "stroke_path"} or _graphic_requires_raster(operation):
            continue
        visible = _visible_paint_rect(operation, geometrie)
        if visible.is_empty:
            continue
        stroke = operation["stroke"]
        width = stroke.m_internal.linewidth * pymupdf.mupdf.fz_matrix_expansion(operation["ctm"]) if stroke else 0
        if stroke and width > 20:
            native = _paint_commands(operation)
            items = [
                ("l", pymupdf.Point(points[0][0] / 12700, points[0][1] / 12700), pymupdf.Point(following[0][0] / 12700, following[0][1] / 12700))
                for (kind, points), (next_kind, following) in zip(native, native[1:])
                if kind == "move" and next_kind == "line"
            ]
            special = _formes_traits_larges_verticaux({
                "items": items, "width": width, "color": operation["color"],
                "fill_opacity": operation["alpha"], "seqno": operation["seqno"],
            }, geometrie)
            if special:
                formes.extend(special)
                continue
        if operation["clips"] and _rectangular_fill(operation):
            rect = visible
            commands = _chemin_depuis_item(("re", rect), geometrie)
        else:
            rect = operation["path_rect"]
            commands = _paint_commands(operation, geometrie)
        if not commands:
            continue
        formes.append(ShapeEl(
            bbox=_boite_rendable(rect, geometrie), chemins=[commands],
            remplissage=_couleur_hexa(operation["color"]) if stroke is None else None,
            contour=_couleur_hexa(operation["color"]) if stroke else None,
            epaisseur_emu=pt_vers_emu(1 if width > 20 else width),
            pointilles="dash" if stroke and stroke.m_internal.dash_len else None,
            alpha=operation["alpha"], z_index=operation["seqno"],
        ))
    return formes


def extraire_vectoriel(page, geometrie=None) -> list[ShapeEl]:
    """Retourne les formes vectorielles de la page, en EMU."""
    geometrie = geometrie or PageGeometry.depuis_page(page)
    operations = _graphic_paint_operations(page)
    if operations:
        # Actual callbacks keep fill/stroke apart even when get_drawings merges
        # matching paths across an intervening image or text paint. Graphics
        # needing alpha clips/groups are emitted by extraire_images instead.
        return _formes_depuis_peinture(operations, geometrie)
    formes: list[ShapeEl] = []

    # Compatibility for page-like callers without the native device interface.
    for dessin in page.get_drawings(extended=True):
        if dessin.get("type") not in {"f", "s", "fs"}:
            continue
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
                alpha=float(
                    dessin.get("fill_opacity")
                    if dessin.get("fill_opacity") is not None
                    else dessin.get("stroke_opacity", 1.0)
                ),
                z_index=dessin.get("seqno"),
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

    La présence d'une ressource shading sur la page n'est pas une preuve que ce
    cluster en dépend : le shading peut être une décoration locale indépendante.
    Les shadings effectivement peints sont extraits séparément par le fallback
    visuel. La décision du cluster repose donc sur sa complexité propre.

    ``page_a_des_degrades`` reste accepté pour compatibilité avec les appelants
    historiques, mais ne force plus la rasterisation d'une forme représentable.
    """
    return sum(len(forme.chemins) for forme in cluster) > seuil
