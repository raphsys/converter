"""Écriture du package OOXML.

Un .docx est un zip de parties XML. On l'écrit à la main plutôt qu'avec python-docx :
cette bibliothèque ne sait produire ni ancres flottantes ni géométries personnalisées,
qui sont exactement ce dont l'approche a besoin.
"""
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from pdfexact.ir import Document
from pdfexact.render.docx_writer import construire_document_xml

TYPES_RELATIONS = {
    "image": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "hyperlink": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    "font": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
    "styles": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
}

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

_RELS_RACINE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

# Un style par défaut sans marge ni interligne : tout écart viendrait s'ajouter aux
# positions absolues et décalerait le contenu.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:pPrDefault><w:pPr>
<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>
</w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
<w:name w:val="Normal"/>
<w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr>
</w:style>
</w:styles>"""


@dataclass(frozen=True)
class Relation:
    identifiant: str
    type_rel: str
    cible: str
    externe: bool


class GestionnaireRelations:
    """Attribue les identifiants rId et collecte les relations de document.xml."""

    def __init__(self):
        self._entrees: list[Relation] = []
        self._par_cible: dict[tuple[str, str, bool], str] = {}

    def ajouter(self, cible: str, type_rel: str, externe: bool = False) -> str:
        """Retourne l'identifiant de relation, en réutilisant celui d'une cible connue."""
        cle = (cible, type_rel, externe)
        if cle in self._par_cible:
            return self._par_cible[cle]

        identifiant = f"rId{len(self._entrees) + 1}"
        self._entrees.append(Relation(identifiant, TYPES_RELATIONS[type_rel], cible, externe))
        self._par_cible[cle] = identifiant
        return identifiant

    def vers_xml(self) -> str:
        lignes = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        ]
        for relation in self._entrees:
            mode = ' TargetMode="External"' if relation.externe else ""
            cible = escape(relation.cible, {'"': "&quot;"})
            lignes.append(
                f'<Relationship Id="{relation.identifiant}" Type="{relation.type_rel}" '
                f'Target="{cible}"{mode}/>'
            )
        lignes.append("</Relationships>")
        return "".join(lignes)


def ecrire_docx(document: Document, chemin) -> None:
    """Écrit le package complet à l'emplacement indiqué."""
    relations = GestionnaireRelations()
    # Déclarée en premier : une partie référencée dans [Content_Types] sans relation
    # correspondante fait échouer l'ouverture.
    relations.ajouter("styles.xml", "styles")
    corps = construire_document_xml(document, relations)

    with zipfile.ZipFile(Path(chemin), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS_RACINE)
        z.writestr("word/document.xml", corps)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/_rels/document.xml.rels", relations.vers_xml())
        for item in document.media.values():
            z.writestr(f"word/media/{item.media_ref}.{item.extension}", item.donnees)
