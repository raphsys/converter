"""Layout zones below the confidence floor are dropped, as in vysi (VYSI_PDF_LAYOUT_MIN_CONFIDENCE)."""
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.layout import ai
from pdfexact.layout.ai import LayoutAIZone


def _zone(confiance):
    return LayoutAIZone("z", "text", "text", confiance, BBox(u(10), u(10), u(100), u(50)), "paddlex", "t")


def test_zones_below_the_confidence_floor_are_dropped():
    assert ai.CONFIANCE_MIN_ZONE == 0.20
    gardees = ai.filtrer_confiance([_zone(0.1), _zone(0.2), _zone(0.9), _zone(None)])
    assert [z.confidence for z in gardees] == [0.2, 0.9, None]
