def test_dependances_importables():
    import pymupdf

    assert pymupdf.__doc__


def test_paquet_importable():
    import pdfexact

    assert pdfexact.__name__ == "pdfexact"
