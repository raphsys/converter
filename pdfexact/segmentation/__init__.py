"""SEGMENTATION : module du pipeline qui découpe un PDF en éléments et en bboxes.

Entrée : un PDF et des ``OptionsSegmentation``. Sortie : un
``ResultatSegmentation`` (le Document segmenté et ses diagnostics), base sur
laquelle s'appuie l'identification. Son comportement est verrouillé par
``tests/segmentation/test_non_regression.py``.
"""
from pdfexact.segmentation.pipeline import (
    OptionsSegmentation,
    ResultatSegmentation,
    enregistrer_catalogue,
    segmenter,
)

__all__ = ["OptionsSegmentation", "ResultatSegmentation", "enregistrer_catalogue", "segmenter"]
