"""Mesure de fidélité visuelle.

La fidélité se mesure, elle ne s'affirme pas. Le docx produit est reconverti en PDF par
LibreOffice, les deux PDF sont rendus en images, et comparés page à page par similarité
structurelle (SSIM).

LibreOffice n'est requis qu'ici, en développement — jamais à l'exécution du convertisseur.

Le SSIM plutôt qu'une différence de pixels : un décalage d'un pixel sur un glyphe ruine
une comparaison exacte alors qu'il est invisible à l'œil. Le SSIM compare des structures
locales — c'est plus proche de ce que voit un lecteur.
"""
import subprocess
from pathlib import Path

import numpy as np
import pymupdf
from skimage.metrics import structural_similarity

SEUIL_PAR_DEFAUT = 0.95
DPI_PAR_DEFAUT = 150


def docx_vers_pdf(chemin_docx, dossier_sortie) -> Path:
    """Convertit un .docx en PDF via LibreOffice headless.

    Attention : une conversion réussie ne prouve PAS que le docx est un package OOXML
    valide. Mesuré — LibreOffice accepte un fichier contenant du texte brut renommé en
    .docx et produit un PDF sans erreur ni code retour non nul. La validité structurelle
    se vérifie ailleurs : parties obligatoires présentes et XML bien formé, dans
    tests/render/test_package.py.
    """
    dossier_sortie = Path(dossier_sortie)
    resultat = subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(dossier_sortie),
            str(chemin_docx),
        ],
        capture_output=True,
        timeout=300,
    )
    if resultat.returncode != 0:
        raise RuntimeError(
            "LibreOffice a échoué : " + resultat.stderr.decode(errors="replace")
        )

    produit = dossier_sortie / (Path(chemin_docx).stem + ".pdf")
    if not produit.exists():
        raise RuntimeError(f"PDF attendu absent : {produit}")
    return produit


def rendre_en_images(chemin_pdf, dpi: int = DPI_PAR_DEFAUT) -> list:
    """Rend chaque page en niveaux de gris, sous forme de tableau numpy dans [0, 1]."""
    doc = pymupdf.open(chemin_pdf)
    images = []
    try:
        for page in doc:
            pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            tableau = np.frombuffer(pixmap.samples, dtype=np.uint8)
            images.append(
                tableau.reshape(pixmap.height, pixmap.width).astype(np.float64) / 255.0
            )
    finally:
        doc.close()
    return images


def score_ssim(image_a, image_b) -> float:
    """Similarité structurelle entre deux images.

    Le résultat vit dans [-1, 1], pas dans [0, 1] : deux images sans rapport tombent
    autour de zéro et peuvent passer légèrement en négatif quand leurs structures locales
    sont anticorrélées. Aucun écrêtage n'est appliqué — un score négatif est une
    information, pas une anomalie à masquer.

    Les tailles peuvent différer de quelques pixels — LibreOffice recale les pages sur son
    format normalisé le plus proche. On compare alors l'intersection.
    """
    hauteur = min(image_a.shape[0], image_b.shape[0])
    largeur = min(image_a.shape[1], image_b.shape[1])
    a = image_a[:hauteur, :largeur]
    b = image_b[:hauteur, :largeur]

    cote = min(hauteur, largeur)
    if cote < 7:
        return 1.0 if np.allclose(a, b) else 0.0

    # La fenêtre du SSIM doit être impaire et tenir dans l'image.
    fenetre = min(7, cote if cote % 2 else cote - 1)
    return float(structural_similarity(a, b, data_range=1.0, win_size=fenetre))


def comparer(pdf_source, docx_produit, dpi: int = DPI_PAR_DEFAUT) -> list[float]:
    """Retourne un score SSIM par page, entre le PDF d'origine et le docx converti."""
    dossier = Path(docx_produit).parent
    pdf_du_docx = docx_vers_pdf(docx_produit, dossier)

    images_source = rendre_en_images(pdf_source, dpi=dpi)
    images_produit = rendre_en_images(pdf_du_docx, dpi=dpi)

    nombre = min(len(images_source), len(images_produit))
    return [score_ssim(images_source[i], images_produit[i]) for i in range(nombre)]


def rapport_de_comparaison(scores, seuil: float = SEUIL_PAR_DEFAUT) -> str:
    """Message d'échec lisible : quelle page, quel score, quel écart au seuil."""
    lignes = []
    for numero, score in enumerate(scores, start=1):
        marque = "ok " if score >= seuil else "ECHEC"
        lignes.append(f"  page {numero} : SSIM {score:.4f}  [{marque}]")
    return "\n".join(lignes)


def origines_de_page(chemin_pdf, page: int = 0) -> list[tuple[str, float, float, float]]:
    """Retourne (texte, x, baseline_y, largeur) de chaque span, en points."""
    doc = pymupdf.open(chemin_pdf)
    releve = []
    try:
        for bloc in doc[page].get_text("dict").get("blocks", []):
            if bloc.get("type") != 0:
                continue
            for ligne in bloc["lines"]:
                for span in ligne["spans"]:
                    texte = span["text"].strip()
                    if texte:
                        releve.append(
                            (
                                texte,
                                span["origin"][0],
                                span["origin"][1],
                                span["bbox"][2] - span["bbox"][0],
                            )
                        )
    finally:
        doc.close()
    return releve


def ecarts_de_placement(pdf_source, docx_produit, page_source: int = 0) -> dict:
    """Compare les positions de texte entre le PDF source et le docx reconverti.

    Bien plus sévère que le SSIM : on lit les coordonnées réelles des baselines au lieu
    de comparer des images. Un décalage d'un dixième de point se voit ici, pas à l'œil.

    Les spans sont appariés par texte identique, puis par abscisse la plus proche — un
    même mot apparaissant plusieurs fois sur la page fausserait sinon la mesure.
    """
    dossier = Path(docx_produit).parent
    pdf_produit = docx_vers_pdf(docx_produit, dossier)

    source = origines_de_page(pdf_source, page_source)
    produit = origines_de_page(pdf_produit, 0)

    par_texte: dict[str, list] = {}
    for texte, x, y, largeur in produit:
        par_texte.setdefault(texte, []).append((x, y, largeur))

    dx, dy, dlargeur = [], [], []
    for texte, x, y, largeur in source:
        candidats = par_texte.get(texte)
        if not candidats:
            continue
        X, Y, L = min(candidats, key=lambda c: abs(c[0] - x))
        dx.append(X - x)
        dy.append(Y - y)
        if largeur > 1:
            dlargeur.append((L - largeur) / largeur * 100.0)

    def _mediane(valeurs):
        return float(np.median(valeurs)) if valeurs else float("nan")

    return {
        "apparies": len(dx),
        "total_source": len(source),
        "dx_median_pt": _mediane(dx),
        "dy_median_pt": _mediane(dy),
        "dlargeur_median_pct": _mediane(dlargeur),
        "dy_max_pt": max((abs(v) for v in dy), default=float("nan")),
    }
