from pdfexact.web import _build_command


class Item:
    def __init__(self, value="", filename=None):
        self.value = value
        self.filename = filename


class Form(dict):
    pass


def test_web_build_command_active_audit_final_et_ia_cpu(tmp_path):
    form = Form(
        {
            "dpi": Item("100"),
            "final_audit_dpi": Item("100"),
            "text_mode": Item("rapidocr"),
            "ocr_layout": Item("word-native"),
            "ocr_granularity": Item("line"),
            "font_dir": Item("fonts/local"),
            "fetch_missing_fonts": Item("on"),
            "layout_ai": Item("on"),
            "layout_device": Item("cpu"),
            "layout_model": Item("ppstructurev3/PP-DocLayout_plus-L"),
            "layout_model_root": Item("/models"),
            "final_audit": Item("on"),
        }
    )

    cmd = _build_command(
        form,
        tmp_path / "source.pdf",
        tmp_path / "sortie.docx",
        tmp_path / "rapport.json",
    )

    assert "--layout-ai" in cmd
    assert "--layout-device" in cmd
    assert "cpu" in cmd
    assert "--final-audit" in cmd
    assert cmd[cmd.index("--final-audit-dpi") + 1] == "100"
    assert "--fetch-missing-fonts" in cmd
