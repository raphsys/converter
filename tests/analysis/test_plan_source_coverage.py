import pytest

from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.provenance import expliquer_filtrage
from pdfexact.analysis.semantic import regrouper_listes, regrouper_paragraphes
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, FontRef, Line, Page, Span, TextBox
from pdfexact.render.package import GestionnaireRelations
from pdfexact.render.reflow import prepare_page_elements
from pdfexact.render.render_plan import RenderPlan, build_document_render_plan, build_render_plan
from pdfexact.render.word_native_rewriter import rewrite_document_xml


def box(text, ident, y=10, x=10, width=160):
    bbox = BBox(u(x), u(y), u(x + width), u(y + 12))
    span = Span(text, FontRef('Arial', 'Arial', False, False), 12, '000000', bbox=bbox, source_id=ident + ':span')
    line = Line(bbox, [span], u(12), bbox.largeur, source_id=ident + ':line')
    return TextBox(bbox, [line], source_id=ident, semantic_role='body')


def document(*elements, discarded=()):
    return Document([Page(3, u(300), u(200), list(elements), discarded_elements=list(discarded))])


def test_empty_plan_cannot_cover_nonempty_source_document():
    doc = document(box('visible', 'visible'))
    plan = RenderPlan({}, AnalysisOptions())
    assert plan.validate(doc)
    with pytest.raises(ValueError):
        rewrite_document_xml(doc, GestionnaireRelations(), render_plan=plan)


def test_historical_warning_does_not_cover_discarded_source():
    discarded = box('unresolved', 'discarded', 30)
    expliquer_filtrage(discarded, 'covered-by-zone')
    plan = build_render_plan(document(box('visible', 'visible'), discarded=[discarded]))
    assert any('uncovered-source:discarded' in error for error in plan.validate())


def test_claimed_duplicate_requires_actual_equivalence():
    original = box('visible', 'visible')
    duplicate = box('different text', 'duplicate')
    duplicate.duplicate_of = 'visible'
    duplicate.duplicate_verified = True
    plan = build_render_plan(document(original, discarded=[duplicate]))
    assert any('duplicate' in error for error in plan.validate())


def test_true_duplicate_maps_every_observation_to_same_materialization():
    original = box('same text', 'visible')
    duplicate = box('same text', 'duplicate')
    duplicate.duplicate_of = 'visible'
    duplicate.duplicate_verified = True
    plan = build_render_plan(document(original, discarded=[duplicate]))
    assert plan.validate() == []
    assert {'duplicate', 'duplicate:line', 'duplicate:span'} <= set(plan.source_coverage)
    assert plan.source_coverage['duplicate'].target_ids == ('visible',)


def test_actual_duplicate_filter_has_verified_complete_coverage():
    from pdfexact.extract.document import _dedoublonner_textes_positionnes

    doc = document(box('same text', 'visible'), box('same text', 'duplicate'))
    _dedoublonner_textes_positionnes(doc.pages[0])
    assert len(doc.pages[0].discarded_elements) == 1
    plan = build_render_plan(doc)
    assert plan.validate(doc) == []
    assert plan.source_coverage['duplicate'].relationship == 'duplicate'


def test_verified_merge_preserves_all_source_children():
    doc = document(box('first part', 'first'), box('next part', 'second', 24))
    plan = build_document_render_plan(doc)
    assert len(plan.for_page(3)) == 1
    assert plan.validate(doc) == []
    assert {'first', 'second', 'second:span'} <= set(plan.source_coverage)


@pytest.mark.parametrize("claimed_pixel_verification", [False, True])
def test_raster_capture_trace_does_not_prove_output_pixel_verification(claimed_pixel_verification):
    from pdfexact.analysis.provenance import Evidence
    from pdfexact.ir import RasterEl, ShapeEl
    from pdfexact.scene import capture_source_observations

    source = ShapeEl(BBox(u(10), u(10), u(90), u(90)), [], 'FF0000', None, 0, source_id='vector')
    raster = RasterEl(source.bbox, 'capture', purpose='local-fallback', source_id='raster')
    doc = document(source)
    capture_source_observations(doc.pages[0], [source])
    doc.pages[0].elements = [raster]
    doc.pages[0].discarded_elements = [source]
    raster.source_ids = ('raster', 'vector')
    assert build_render_plan(doc).validate()
    raster.attributes['replaces'] = ('vector',)
    raster.evidence.append(Evidence('raster-replacement', 'source-producer', None, (
        ('source_ids', ('vector',)), ('output_id', 'raster'), ('reason', 'unsupported-source-paint'),
        ('capture_method', 'source-page-region-render'), ('dpi', 200), ('pixel_equivalence_verified', claimed_pixel_verification),
    )))
    plan = build_render_plan(doc)
    assert plan.validate(doc) == ['unverified-raster-replacement:vector']
    assert plan.source_coverage['vector'].relationship == 'raster-replacement'
    assert build_render_plan(doc, AnalysisOptions(allow_local_raster_fallback=False)).validate()


def test_original_bitmap_image_is_not_a_forbidden_raster_fallback():
    from pdfexact.analysis.decisions import decider_mode_universel
    from pdfexact.scene import ElementKind, ElementRecord, SourceKind

    record = ElementRecord('bitmap', 3, ElementKind.IMAGE, BBox(0, 0, 100, 100), SourceKind.IMAGE, ('bitmap',))
    decision = decider_mode_universel(record, options=AnalysisOptions(allow_local_raster_fallback=False))
    assert decision.mode.value == 'anchored-image'
    assert not decision.constraints


def test_list_marker_is_proven_and_preserved_without_mutating_source():
    marker, body = box('*', 'marker', x=1, width=4), box('Body text', 'body')
    doc = document(marker, body)
    plan = build_document_render_plan(doc)
    assert plan.validate() == []
    assert {'marker', 'marker:line', 'marker:span', 'body'} <= set(plan.source_coverage)
    item = plan.for_page(3)[0]
    assert {'marker', 'body'} <= set(item.element.source_ids)
    assert getattr(body, 'list_marker', None) is None
    assert body.bbox.x0 == u(10)


def install_prepared(plan, doc):
    for page in doc.pages:
        page.elements = list(plan.elements_for_page(page.index))


def test_installed_list_marker_attachment_is_not_a_post_plan_mutation():
    doc = document(box('*', 'marker', x=1, width=4), box('Body text', 'body'))
    plan = build_document_render_plan(doc)
    install_prepared(plan, doc)
    assert getattr(doc.pages[0].elements[0], 'transformation', None) == 'list-marker-attachment'
    assert plan.validate(doc) == []


@pytest.mark.parametrize('tamper', ['body-text', 'bbox-beyond-marker'])
def test_installed_list_marker_attachment_still_rejects_real_mutation(tamper):
    doc = document(box('*', 'marker', x=1, width=4), box('Body text', 'body'))
    plan = build_document_render_plan(doc)
    install_prepared(plan, doc)
    body = doc.pages[0].elements[0]
    if tamper == 'body-text':
        body.lignes[0].spans[0].texte = 'Changed text'
    else:
        body.bbox = BBox(body.bbox.x0, body.bbox.y0, body.bbox.x1 + u(50), body.bbox.y1)
    assert 'source-mutated-after-plan:body' in plan.validate(doc)


@pytest.mark.parametrize('frame', [None, 'same-frame'])
def test_confidence_boundary_survives_column_and_frame_passes(frame):
    left, right = box('Premiere phrase.', 'left'), box('puis la suite', 'right', 24)
    for value in (left, right):
        value.layout_frame_id = frame
    result = prepare_page_elements([left, right], AnalysisOptions(semantic_group_min_confidence=.9))
    assert len(result) == 2


def test_always_boundaries_and_extra_override_use_same_policy():
    values = [box('first line', 'left'), box('next line', 'right', 24)]
    options = AnalysisOptions(extra={'preserve_line_boundaries': 'always'})
    assert [len(group) for group in regrouper_paragraphes(values, options)] == [1, 1]
    assert len(prepare_page_elements(values, options)) == 2
    explicit = AnalysisOptions(semantic_vertical_gap_factor=2.4)
    override = AnalysisOptions(extra={'semantic_vertical_gap_factor': 2.4})
    distant = [box('first line', 'left'), box('next line', 'right', 46)]
    assert [len(group) for group in regrouper_paragraphes(distant, explicit)] == [len(group) for group in regrouper_paragraphes(distant, override)]


def test_unknown_confidence_remains_unknown_and_known_zero_is_not_promoted():
    from pdfexact.analysis.decisions import decider_mode_universel
    from pdfexact.scene import ElementKind, ElementRecord, SourceKind

    record = ElementRecord('source', 3, ElementKind.TEXT, BBox(0, 0, 100, 100), SourceKind.INFERRED, source_ids=('source',))
    assert decider_mode_universel(record).confidence == 0.0
    assert record.confidence is None
    record.confidence = .9
    record.geometry_confidence = 0.0
    record.semantic_confidence = .8
    assert decider_mode_universel(record).confidence == 0.0


@pytest.mark.parametrize(('orientation', 'angle', 'mode'), [('vertical', 90, 'rotated-native-text'), ('oblique', -30, 'locked-native-paragraph'), ('curved', 15, 'curved-text')])
def test_always_boundaries_cannot_hide_orientation(orientation, angle, mode):
    from pdfexact.analysis.decisions import decider_mode_universel
    from pdfexact.scene import ElementKind, ElementRecord, SourceKind

    record = ElementRecord('source', 3, ElementKind.TEXT, BBox(0, 0, 100, 100), SourceKind.INFERRED, source_ids=('source',), orientation=orientation, angle_deg=angle)
    decision = decider_mode_universel(record, options=AnalysisOptions(preserve_line_boundaries='always'))
    assert decision.mode.value == mode
    assert decision.expected_angle_deg == angle
    assert decision.editable
