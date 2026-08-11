"""Imprime les structures réellement retournées par la version installée de PyMuPDF.

Le plan d'implémentation cite ces API de mémoire ; cette sonde dit ce qu'elles renvoient
vraiment. En cas de divergence, la sonde a raison.

Usage : python scripts/probe_pymupdf.py <fichier.pdf> [numero_page]
"""
import json
import sys

import pymupdf


def _titre(texte):
    print(f"\n{'=' * 70}\n{texte}\n{'=' * 70}")


def sonder(chemin_pdf, numero_page=0):
    print("version PyMuPDF :", pymupdf.version)

    doc = pymupdf.open(chemin_pdf)
    page = doc[numero_page]

    _titre("page.rect")
    print(page.rect, "| largeur", page.rect.width, "| hauteur", page.rect.height)

    _titre("get_text('dict') : clés du premier span")
    donnees = page.get_text("dict")
    for bloc in donnees.get("blocks", []):
        if bloc.get("type") == 0 and bloc.get("lines"):
            ligne = bloc["lines"][0]
            print("clés de bloc  :", sorted(bloc.keys()))
            print("clés de ligne :", sorted(ligne.keys()))
            print("premier span  :")
            print(json.dumps(ligne["spans"][0], default=str, indent=2, ensure_ascii=False))
            break
    else:
        print("aucun bloc de texte")

    _titre("get_drawings() : premier dessin")
    dessins = page.get_drawings()
    print("nombre de dessins :", len(dessins))
    if dessins:
        print("clés :", sorted(dessins[0].keys()))
        print(json.dumps(dessins[0], default=str, indent=2, ensure_ascii=False))
        operateurs = {item[0] for dessin in dessins for item in dessin.get("items", [])}
        print("opérateurs rencontrés :", sorted(operateurs))

    _titre("get_images(full=True)")
    images = page.get_images(full=True)
    print("entrées :", len(images), "| xrefs uniques :", sorted({e[0] for e in images}))
    for entree in images[:3]:
        print(" ", entree)
        print("    placements :", len(page.get_image_rects(entree[0])))

    _titre("get_links()")
    for lien in page.get_links():
        print(json.dumps(lien, default=str, ensure_ascii=False))

    _titre("get_fonts(full=True) et extract_font()")
    for police in page.get_fonts(full=True):
        print(police)
        try:
            nom, extension, type_police, tampon = doc.extract_font(police[0])
        except Exception as erreur:  # noqa: BLE001 — la sonde doit survivre à tout
            print("    extract_font a échoué :", erreur)
            continue
        print(f"    -> nom={nom!r} ext={extension!r} type={type_police!r} octets={len(tampon)}")
        if tampon:
            _sonder_cmap(tampon)

    _titre("xref_get_key(page, 'Resources/Shading')")
    print(doc.xref_get_key(page.xref, "Resources/Shading"))

    doc.close()


def _sonder_cmap(octets):
    """Dit si la police embarquée porte une table cmap exploitable.

    C'est le risque principal identifié dans la spec : les sous-ensembles de polices PDF
    ont souvent un cmap absent ou arbitraire, ce qui rend l'embarquement direct inutile.
    """
    import io

    from fontTools.ttLib import TTFont

    try:
        police = TTFont(io.BytesIO(octets), fontNumber=0, lazy=True)
        cmap = police.getBestCmap()
    except Exception as erreur:  # noqa: BLE001
        print("    cmap : illisible —", type(erreur).__name__, erreur)
        return
    print(f"    cmap : {len(cmap or {})} entrées", "(VIDE — embarquement inutilisable)" if not cmap else "")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    sonder(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
