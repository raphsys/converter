def test_dependances_importables():
    import pymupdf
    import fontTools
    import PIL

    assert pymupdf.__doc__


def test_paquet_importable():
    import pdfexact

    assert pdfexact.__name__ == "pdfexact"
