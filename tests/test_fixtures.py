import pymupdf


def test_les_fixtures_produisent_des_pdf_ouvrables(pdf_texte, pdf_vectoriel, pdf_image, pdf_liens):
    for chemin in (pdf_texte, pdf_vectoriel, pdf_image, pdf_liens):
        doc = pymupdf.open(chemin)
        assert doc.page_count == 1
        doc.close()


def test_la_fixture_texte_contient_bien_du_texte(pdf_texte):
    doc = pymupdf.open(pdf_texte)
    try:
        texte = doc[0].get_text()
    finally:
        doc.close()

    assert "Helvetica" in texte
    assert "Times" in texte


def test_la_fixture_image_place_deux_fois_la_meme_image(pdf_image):
    """get_images() liste une entrée par référence, pas par image unique.

    Les deux entrées portent le même xref : c'est get_image_rects() qui donne les
    placements. Tout code qui itère sur get_images() sans dédupliquer les xrefs
    compte donc chaque placement deux fois.
    """
    doc = pymupdf.open(pdf_image)
    try:
        images = doc[0].get_images(full=True)
        xrefs = {entree[0] for entree in images}
        rects = doc[0].get_image_rects(next(iter(xrefs)))
    finally:
        doc.close()

    assert len(images) == 2, "une entrée par référence dans les ressources"
    assert len(xrefs) == 1, "une seule ressource image sous-jacente"
    assert len(rects) == 2, "deux placements attendus"


def test_la_fixture_liens_porte_un_lien_uri(pdf_liens):
    doc = pymupdf.open(pdf_liens)
    try:
        liens = doc[0].get_links()
    finally:
        doc.close()

    assert len(liens) == 1
    assert liens[0]["uri"] == "https://example.org/"
