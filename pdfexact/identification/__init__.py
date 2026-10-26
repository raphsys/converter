"""IDENTIFICATION : module du pipeline qui dit ce qu'est chaque élément segmenté.

Entrée : un ``ResultatSegmentation`` et le PDF source. Sortie : un
``ResultatIdentification`` (type fermé du référentiel, statut, confiance,
alternatives et indices par bbox ; expressions localisées dans les textes),
consommé par l'extraction des attributs. Extensible : ``identifier(...,
identificateurs=[...])`` et ``detecteurs=`` ajoutent de nouvelles identités.
"""
from pdfexact.identification.base import Candidat, ContextePage, Decision, Identificateur, Registre
from pdfexact.identification.expressions import DetecteurExpression, RegistreExpressions, Trouvaille
from pdfexact.identification.pipeline import (
    ElementIdentifie,
    ExpressionIdentifiee,
    ResultatIdentification,
    enregistrer_identification,
    identifier,
)
from pdfexact.identification.rendu import annoter_pdf_types

__all__ = [
    "Candidat", "ContextePage", "Decision", "DetecteurExpression", "ElementIdentifie", "ExpressionIdentifiee",
    "Identificateur", "Registre", "RegistreExpressions", "ResultatIdentification", "Trouvaille",
    "annoter_pdf_types", "enregistrer_identification", "identifier",
]
