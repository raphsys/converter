
import pytest

from pdfexact.analysis.semantic import est_frontiere_de_paragraphe, est_texte_de_corps, ends_sentence, normaliser_script_et_langue, starts_list_marker
from pdfexact.geometry import BBox, pt_vers_emu
from pdfexact.ir import FontRef, Line, Span, TextBox
from pdfexact.layout import text_comprehension as comprehension


@pytest.fixture(autouse=True)
def no_provider():
    with comprehension.contexte_comprehension_texte():
        comprehension.configurer_fournisseur_comprehension_texte(None)
        yield


def block(texts):
    font = FontRef("Test", "Arial", False, False)
    lines = []
    for index, text in enumerate(texts):
        bbox = BBox(pt_vers_emu(10), pt_vers_emu(20 + 12 * index), pt_vers_emu(200), pt_vers_emu(30 + 12 * index))
        lines.append(Line(bbox, [Span(text, font, 10, "123456")], bbox.hauteur, bbox.largeur))
    return TextBox(BBox(lines[0].bbox.x0, lines[0].bbox.y0, lines[-1].bbox.x1, lines[-1].bbox.y1), lines)


@pytest.mark.parametrize("text", [
    "Это обычный русский текст который описывает работу системы и её ограничения.",
    "这是说明系统运行过程以及限制条件的普通中文段落。",
    "これはシステムの動作と制限について説明する通常の文章です。",
])
def test_unicode_prose_is_not_automatically_a_diagram_label(text):
    assert est_texte_de_corps(text)
    decision = comprehension.comprendre_ligne_texte(text, frame_role="text-column", frame_strategy="word-text")
    assert decision.action == "candidate-paragraph-line"


@pytest.mark.parametrize("lines", [
    ("Система получает входные данные и проверяет их", "перед обработкой и сохранением результата."),
    ("Пользователь может выбрать несколько документов для обработки,", "после чего программа последовательно проверяет каждый файл."),
    ("Эта функция возвращает подробное описание всех найденных ошибок", "и позволяет исправить данные перед повторной проверкой."),
])
def test_russian_fallback_prose_is_not_lost_to_latin_only_label_rules(lines):
    assert comprehension._score_label_ou_schema(lines) < comprehension._score_prose(lines)
    group = comprehension.comprendre_groupe_lignes(lines, frame_role="text-column", frame_strategy="word-text")
    assert group.action == "merge-paragraph" and group.fallback_used and not group.ai_used
    for line in lines:
        decision = comprehension.comprendre_ligne_texte(line, frame_role="text-column")
        assert decision.kind != "label"
        if len(comprehension.unicode_text_units(line)) >= 7:
            assert decision.action == "candidate-paragraph-line"


@pytest.mark.parametrize("text", ["Температура", "Давление", "Скорость", "输入", "温度"])
def test_unicode_labels_stay_labels_in_fallback(text):
    decision = comprehension.comprendre_ligne_texte(text, frame_role="text-column")
    assert decision.action == "preserve-line" and decision.fallback_used


def test_unicode_units_keep_combining_marks_and_never_rewrite_source():
    text = "e\u0301cole данные 用户 한국어"
    assert comprehension.unicode_text_units(text) == ["e\u0301cole", "данные", "用", "户", "한국어"]
    assert text == "e\u0301cole данные 用户 한국어"


@pytest.mark.parametrize("text", ["終わり。", "结束！", "質問？"])
def test_cjk_sentence_boundaries(text):
    assert ends_sentence(text)


@pytest.mark.parametrize("text", ["а) пункт", "一、项目", "（二）项目"])
def test_unicode_list_boundaries(text):
    assert starts_list_marker(text)


def test_script_annotation_never_invents_russian_language():
    element = block(["Український текст і приклад"])
    normaliser_script_et_langue(element)
    assert element.script == "cyrillic" and element.language == "auto"
    element.language = "uk"
    normaliser_script_et_langue(element)
    assert element.language == "uk"






def test_explicit_hard_break_cannot_be_overridden_by_provider():
    comprehension.configurer_fournisseur_comprehension_texte(lambda *_args:
        comprehension.TextUnderstandingDecision("paragraph", "paragraph-reflow", 0.95, line_joins=("no_space",)))
    decision = comprehension.comprendre_reflow_paragraphe(("中文\n", "继续"), frame_role="text-column")
    assert decision.line_joins == ("preserve_break",)
    assert decision.fallback_used and not decision.ai_used


def test_cjk_spacing_conflict_abstains_and_uses_source_character_fallback():
    comprehension.configurer_fournisseur_comprehension_texte(lambda *_args:
        comprehension.TextUnderstandingDecision("paragraph", "paragraph-reflow", 0.99, line_joins=("space",)))
    decision = comprehension.comprendre_reflow_paragraphe(("中文段落", "继续说明"), frame_role="text-column")
    assert decision.line_joins == ("no_space",) and decision.fallback_used and not decision.ai_used


@pytest.mark.parametrize("explicit_role", [None, "label"])
def test_short_russian_labels_cannot_be_merged_by_a_confident_provider(explicit_role):
    comprehension.configurer_fournisseur_comprehension_texte(lambda *_args:
        comprehension.TextUnderstandingDecision("paragraph", "merge-paragraph", 0.99))
    first, second = block(("Давление",)), block(("Температура",))
    for element in (first, second):
        element.layout_frame_role = "text-column"
        element.layout_frame_strategy = "word-text"
        element.layout_frame_id = "same"
        element.semantic_role = explicit_role
    second.bbox = BBox(first.bbox.x0, first.bbox.y1 + 1, first.bbox.x1, first.bbox.y1 + first.bbox.hauteur + 1)
    assert est_frontiere_de_paragraphe(first, second)
    group = comprehension.comprendre_groupe_lignes(("Давление", "Температура"), frame_role="text-column")
    assert group.action == "preserve-lines" and group.fallback_used and not group.ai_used


def test_provider_receives_verbatim_unicode_and_whitespace():
    seen = []
    def provider(kind, lines, *_args):
        seen.append(lines)
        return None
    comprehension.configurer_fournisseur_comprehension_texte(provider)
    comprehension.comprendre_reflow_paragraphe(("  中文  ", "次の行"), frame_role="text-column")
    assert seen == [("  中文  ", "次の行")]


