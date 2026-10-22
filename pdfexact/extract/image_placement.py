"""Validation des placements bitmap dans le repere visible de la page.

Les PDF issus de PowerPoint et d'anciens pilotes PostScript peuvent exposer une
ressource image avec une bbox qui ne correspond pas a l'occurrence effectivement
peinte. Ce module ne remplace pas la geometrie PDF : il fournit un controle visuel
local et conserve la position PDF lorsque le controle ne peut pas conclure.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from pdfexact.geometry import BBox, PageGeometry, pt_vers_emu


# The rendered page and its descriptors are shared by every image placement on
# that page.  Re-rendering/re-detecting the complete page for each XRef made
# the placement witness both slow and needlessly dependent on resource order.
_PAGE_PROBE_CACHE: dict[tuple[int, int], tuple[object, object, object, object]] = {}
_PAGE_PROBE_CACHE_LIMIT = 8


def _image_rgba(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data)).convert("RGBA")


def preserve_alpha_and_remove_connected_white(data: bytes, extension: str) -> tuple[bytes, str]:
    """Preserve alpha and make only a white border-connected background transparent.

    A white pixel inside a logo remains white. Seuls les pixels proches du blanc et
    connectes au bord sont retires, ce qui evite le rectangle blanc artificiel autour
    d'un logo sans detruire son contenu.
    """
    try:
        image = _image_rgba(data)
    except Exception:  # noqa: BLE001
        return data, extension
    pixels = image.load()
    width, height = image.size
    if width < 3 or height < 3:
        return data, extension

    border = []
    for x in range(width):
        border.extend(((x, 0), (x, height - 1)))
    for y in range(1, height - 1):
        border.extend(((0, y), (width - 1, y)))

    def near_white(x: int, y: int) -> bool:
        r, g, b, a = pixels[x, y]
        return a > 0 and r >= 247 and g >= 247 and b >= 247

    white_border = sum(1 for x, y in border if near_white(x, y))
    if white_border / max(len(border), 1) < 0.20:
        return data, extension

    pending = list(dict.fromkeys((x, y) for x, y in border if near_white(x, y)))
    visited = set(pending)
    while pending:
        x, y = pending.pop()
        r, g, b, _a = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited and near_white(nx, ny):
                visited.add((nx, ny))
                pending.append((nx, ny))

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue(), "png"


def _matrix_values(matrix) -> tuple[float, ...]:
    if matrix is None:
        return ()
    return tuple(float(getattr(matrix, name)) for name in ("a", "b", "c", "d", "e", "f"))


def _projected_bbox(points, page_width_px: float, page_height_px: float, scale_x: float, scale_y: float) -> BBox | None:
    if len(points) < 4:
        return None
    xs = [float(point[0]) / scale_x for point in points]
    ys = [float(point[1]) / scale_y for point in points]
    x0, x1 = max(0.0, min(xs)), min(page_width_px / scale_x, max(xs))
    y0, y1 = max(0.0, min(ys)), min(page_height_px / scale_y, max(ys))
    if x1 <= x0 or y1 <= y0:
        return None
    return BBox(pt_vers_emu(x0), pt_vers_emu(y0), pt_vers_emu(x1), pt_vers_emu(y1))


def _page_probe_data(page, cv2, np):
    """Prepare one raster witness per page, independently of its resources."""
    key = (id(page), int(getattr(page, "number", -1)))
    cached = _PAGE_PROBE_CACHE.get(key)
    if cached is not None:
        return cached
    pixmap = page.get_pixmap(dpi=96, alpha=False)
    rendered = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )[:, :, :3]
    gray = cv2.cvtColor(rendered, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rendered, cv2.COLOR_RGB2HSV)
    detector = cv2.SIFT_create(nfeatures=1600)
    keypoints, descriptors = detector.detectAndCompute(gray, None)
    value = (pixmap, gray, hsv, (keypoints, descriptors))
    if len(_PAGE_PROBE_CACHE) >= _PAGE_PROBE_CACHE_LIMIT:
        _PAGE_PROBE_CACHE.pop(next(iter(_PAGE_PROBE_CACHE)))
    _PAGE_PROBE_CACHE[key] = value
    return value


def _template_bbox_from_chroma(source, rendered_hsv, cv2, np):
    """Find a strongly chromatic foreground when feature matching is sparse.

    This is a content-based fallback for logos, marks and other transparent or
    white-backed assets. It has no knowledge of their names or expected PDF
    locations. Plain photographs are left to SIFT because their chroma is not a
    stable foreground mask.
    """
    hsv_source = cv2.cvtColor(source, cv2.COLOR_RGB2HSV)
    saturation = hsv_source[:, :, 1]
    value = hsv_source[:, :, 2]
    chromatic = saturation >= 90
    mask = chromatic.astype(np.uint8) * 255
    ys, xs = np.where(mask > 0)
    if len(xs) < 24 or len(xs) / max(mask.size, 1) > 0.70:
        return None
    # A single dominant hue describes a logo/mark well.  A photograph with
    # many unrelated hues is deliberately left to feature matching.
    hue_values = hsv_source[:, :, 0][chromatic]
    if len(hue_values) < 24:
        return None
    dominant_hue = int(np.median(hue_values))
    hue_distance = np.minimum(
        (hue_values.astype(np.int16) - dominant_hue) % 180,
        (dominant_hue - hue_values.astype(np.int16)) % 180,
    )
    if float(np.mean(hue_distance <= 12)) < 0.65:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    template = source[y0:y1, x0:x1]
    template_mask = mask[y0:y1, x0:x1]
    target_hue = rendered_hsv[:, :, 0].astype(np.int16)
    target_saturation = rendered_hsv[:, :, 1]
    target_value = rendered_hsv[:, :, 2]
    distance = np.minimum(
        (target_hue - dominant_hue) % 180,
        (dominant_hue - target_hue) % 180,
    )
    target = ((distance <= 12) & (target_saturation >= 70) & (target_value >= 60)).astype(np.float32)
    source_signal = (
        (np.minimum(
            (hsv_source[y0:y1, x0:x1, 0].astype(np.int16) - dominant_hue) % 180,
            (dominant_hue - hsv_source[y0:y1, x0:x1, 0].astype(np.int16)) % 180,
        ) <= 12)
        & (hsv_source[y0:y1, x0:x1, 1] >= 70)
        & (hsv_source[y0:y1, x0:x1, 2] >= 60)
    ).astype(np.float32)
    best = None
    target_height, target_width = target.shape
    for scale in np.linspace(0.35, 1.35, 21):
        width = max(8, round(template.shape[1] * float(scale)))
        height = max(8, round(template.shape[0] * float(scale)))
        if width > target_width or height > target_height:
            continue
        resized_signal = cv2.resize(source_signal, (width, height), interpolation=cv2.INTER_AREA)
        resized_mask = cv2.resize(template_mask, (width, height), interpolation=cv2.INTER_NEAREST)
        if resized_mask.sum() < 255 * 24:
            continue
        # The mask is used to define the foreground crop.  Masked CCOEFF can
        # become numerically undefined for a nearly constant logo; correlation
        # on the chroma signal is stable and remains content-based.
        result = cv2.matchTemplate(target, resized_signal, cv2.TM_CCORR_NORMED)
        _minimum, maximum, _minimum_location, location = cv2.minMaxLoc(result)
        if best is None or maximum > best[0]:
            best = (maximum, location, width, height)
    if best is None or best[0] < 0.60:
        return None
    _score, (x, y), width, height = best
    return ((x, y), (x + width, y + height), float(best[0]))


def probe_visible_bbox(page, media_data: bytes, geometry: PageGeometry, expected: BBox) -> tuple[BBox, float] | None:
    """Cherche l'occurrence visible d'une image par correspondance locale SIFT.

    Le controle est volontairement opportuniste : une photo uniforme, une image tres
    petite ou une occurrence entierement recouverte conserve sa bbox PDF originale.
    """
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001
        return None
    try:
        source = np.asarray(_image_rgba(media_data).convert("RGB"))
        pixmap, gray_rendered, hsv_rendered, page_features = _page_probe_data(page, cv2, np)
    except Exception:  # noqa: BLE001
        return None
    if min(source.shape[:2]) < 24 or min(gray_rendered.shape[:2]) < 64:
        return None

    gray_source = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    detector = cv2.SIFT_create(nfeatures=1200)
    key_source, desc_source = detector.detectAndCompute(gray_source, None)
    key_rendered, desc_rendered = page_features
    if desc_source is None or desc_rendered is None or len(key_source) < 4 or len(key_rendered) < 4:
        return None
    matcher = cv2.BFMatcher()
    matches = matcher.knnMatch(desc_source, desc_rendered, k=2)
    good = [first for first, second in matches if first.distance < 0.72 * second.distance]
    scale_x = pixmap.width / max(geometry.largeur_pt, 1.0)
    scale_y = pixmap.height / max(geometry.hauteur_pt, 1.0)
    if len(good) >= 4:
        source_points = np.float32([key_source[item.queryIdx].pt for item in good]).reshape(-1, 1, 2)
        rendered_points = np.float32([key_rendered[item.trainIdx].pt for item in good]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(source_points, rendered_points, cv2.RANSAC, 5.0)
        if homography is not None and mask is not None:
            inliers = int(mask.ravel().sum())
            if inliers >= 4 and inliers / max(len(good), 1) >= 0.35:
                height, width = source.shape[:2]
                corners = np.float32([[[0, 0], [width, 0], [width, height], [0, height]]])
                projected = cv2.perspectiveTransform(corners, homography)[0]
                bbox = _projected_bbox(projected, pixmap.width, pixmap.height, scale_x, scale_y)
                if bbox is not None and bbox.largeur > pt_vers_emu(2) and bbox.hauteur > pt_vers_emu(2):
                    ratio = (bbox.largeur * bbox.hauteur) / max(expected.largeur * expected.hauteur, 1)
                    if 0.20 <= ratio <= 5.0:
                        confidence = min(1.0, (inliers / max(len(good), 1)) * min(1.0, len(good) / 20.0))
                        return bbox, confidence

    matched = _template_bbox_from_chroma(source, hsv_rendered, cv2, np)
    if matched is None:
        return None
    top_left, bottom_right, score = matched
    projected = [top_left, (bottom_right[0], top_left[1]), bottom_right, (top_left[0], bottom_right[1])]
    bbox = _projected_bbox(projected, pixmap.width, pixmap.height, scale_x, scale_y)
    if bbox is None:
        return None
    ratio = (bbox.largeur * bbox.hauteur) / max(expected.largeur * expected.hauteur, 1)
    if not 0.20 <= ratio <= 5.0:
        return None
    return bbox, min(1.0, score)


def quad_from_matrix(matrix, geometry: PageGeometry) -> tuple[tuple[int, int], ...]:
    """Conserve le quadrilatere du placement au lieu de garder sa seule enveloppe."""
    if matrix is None:
        return ()
    points = []
    for x, y in ((0, 0), (1, 0), (1, 1), (0, 1)):
        transformed = (x, y)
        try:
            import pymupdf
            value = pymupdf.Point(*point) * matrix
            transformed = (value.x, value.y)
        except Exception:  # noqa: BLE001
            return ()
        points.append(transformed)
    displayed = geometry.points_natifs_vers_affiches(points)
    return tuple((pt_vers_emu(x), pt_vers_emu(y)) for x, y in displayed)


def placement_metadata(page, xref: int, index: int, rect, matrix, geometry: PageGeometry) -> dict[str, object]:
    return {
        "placement_id": f"page:{page.number}:xref:{xref}:placement:{index}",
        "source_xref": xref,
        "transform": _matrix_values(matrix),
        "quad": quad_from_matrix(matrix, geometry),
        "coordinate_space": geometry.repere,
    }
