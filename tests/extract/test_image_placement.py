from io import BytesIO

from PIL import Image, ImageDraw
import pytest

from pdfexact.extract.image_placement import _template_bbox_from_chroma


def _png_logo() -> bytes:
    image = Image.new("RGBA", (120, 48), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 108, 38), fill=(220, 20, 20, 255))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()




@pytest.mark.parametrize("target_size", ((320, 96), (96, 320), (80, 80), (32, 32)))
def test_chroma_template_stays_within_target_dimensions(target_size, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = np.full((160, 160, 3), 255, dtype=np.uint8)
    source[:30, :30] = (220, 20, 20)
    source[-30:, -30:] = (220, 20, 20)
    width, height = target_size
    target = np.full((height, width, 3), 255, dtype=np.uint8)
    if min(target_size) >= 80:
        target[:80, :80] = cv2.resize(source, (80, 80), interpolation=cv2.INTER_NEAREST)
    calls = []
    original_match = cv2.matchTemplate

    def match_template(image, template, method):
        calls.append((image.shape, template.shape))
        return original_match(image, template, method)

    monkeypatch.setattr(cv2, "matchTemplate", match_template)

    matched = _template_bbox_from_chroma(
        source, cv2.cvtColor(target, cv2.COLOR_RGB2HSV), cv2, np
    )

    assert all(template[0] <= image[0] and template[1] <= image[1]
               for image, template in calls)
    if min(target_size) < 56:
        assert not calls
        assert matched is None
    else:
        assert calls
        assert matched is not None
        (x0, y0), (x1, y1), score = matched
        assert 0 <= x0 < x1 <= width
        assert 0 <= y0 < y1 <= height
        assert score > 0.99
