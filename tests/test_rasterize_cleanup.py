from PIL import Image, ImageDraw

from pdfexact.fallback.rasterize import _couleur_fond_locale, _inpaint_regions


def test_couleur_fond_locale_garde_un_fond_clair_malgre_texte_noir():
    image = Image.new("RGB", (180, 80), (238, 234, 214))
    dessin = ImageDraw.Draw(image)
    for y in range(12, 68, 12):
        dessin.rectangle((8, y, 170, y + 5), fill=(15, 13, 12))

    couleur = _couleur_fond_locale(image, (42, 24, 138, 54))

    assert min(couleur) > 180


def test_inpainting_local_preserve_un_fond_uniforme():
    image = Image.new("RGB", (160, 120), "white")
    ImageDraw.Draw(image).rectangle((65, 48, 95, 72), fill="black")

    resultat = _inpaint_regions(image, [(65, 48, 95, 72)])

    assert resultat.getpixel((80, 60)) == (255, 255, 255)


def test_inpainting_local_preserve_un_fond_uniforme_fonce():
    image = Image.new("RGB", (160, 120), (0, 96, 166))
    dessin = ImageDraw.Draw(image)
    dessin.rectangle((65, 48, 95, 72), fill="white")
    dessin.rectangle((20, 80, 140, 83), fill="white")

    resultat = _inpaint_regions(image, [(65, 48, 95, 72)])

    assert resultat.getpixel((80, 60)) == (0, 96, 166)
    assert resultat.getpixel((80, 81)) == (255, 255, 255)
