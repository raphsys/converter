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
from pdfexact.render.fonts_embed import nouveau_guid, obfusquer_police
from pdfexact.render.docx_writer import construire_document_xml

TYPES_RELATIONS = {
    "image": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "hyperlink": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    "font": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
    "fontTable": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable",
    "styles": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
    "settings": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
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
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>
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

_SETTINGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:zoom w:percent="100"/>
<w:defaultTabStop w:val="720"/>
<w:compat>
<w:compatSetting w:name="compatibilityMode"
 w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>
<w:doNotExpandShiftReturn/>
<w:doNotUseHTMLParagraphAutoSpacing/>
<w:useWord2013TrackBottomHyphenation/>
</w:compat>
</w:settings>"""

_FONT_ATTR_PAR_STYLE = {
    (False, False): "embedRegular",
    (True, False): "embedBold",
    (False, True): "embedItalic",
    (True, True): "embedBoldItalic",
}


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


def _style_police(nom: str) -> tuple[bool, bool]:
    minuscule = nom.lower()
    gras = any(
        mot in minuscule
        for mot in ("bold", "demi", "black", "heavy", "extrabold", "semibold")
    )
    italique = any(mot in minuscule for mot in ("italic", "oblique"))
    return gras, italique


def _table_polices_xml(document: Document, relations) -> tuple[str, dict[str, bytes]]:
    """Construit fontTable.xml et les fichiers .odttf a embarquer."""
    familles: dict[str, dict[tuple[bool, bool], tuple[str, str]]] = {}
    fichiers: dict[str, bytes] = {}
    compteur = 1

    for asset in sorted(document.polices.values(), key=lambda item: item.font_id):
        if not asset.reconnue or asset.chemin is None:
            continue
        try:
            octets = Path(asset.chemin).read_bytes()
        except OSError:
            continue

        style = _style_police(asset.font_id)
        famille = asset.famille
        if style in familles.setdefault(famille, {}):
            continue

        guid = nouveau_guid()
        nom_fichier = f"font{compteur}.odttf"
        compteur += 1
        fichiers[nom_fichier] = obfusquer_police(octets, guid)
        rel_id = relations.ajouter(f"fonts/{nom_fichier}", "font")
        familles[famille][style] = (rel_id, guid)

    lignes = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
    ]
    for famille in sorted(familles):
        lignes.append(f'<w:font w:name="{escape(famille)}">')
        for style, (rel_id, guid) in sorted(familles[famille].items()):
            attribut = _FONT_ATTR_PAR_STYLE[style]
            lignes.append(f'<w:{attribut} r:id="{rel_id}" w:fontKey="{guid}"/>')
        lignes.append("</w:font>")
    lignes.append("</w:fonts>")
    return "".join(lignes), fichiers


def ecrire_docx(document: Document, chemin) -> None:
    """Écrit le package complet à l'emplacement indiqué."""
    relations = GestionnaireRelations()
    relations_polices = GestionnaireRelations()
    # Déclarée en premier : une partie référencée dans [Content_Types] sans relation
    # correspondante fait échouer l'ouverture.
    relations.ajouter("styles.xml", "styles")
    relations.ajouter("settings.xml", "settings")
    table_polices, fichiers_polices = _table_polices_xml(document, relations_polices)
    if fichiers_polices:
        relations.ajouter("fontTable.xml", "fontTable")
    corps = construire_document_xml(document, relations)

    with zipfile.ZipFile(Path(chemin), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS_RACINE)
        z.writestr("word/document.xml", corps)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/settings.xml", _SETTINGS)
        if fichiers_polices:
            z.writestr("word/fontTable.xml", table_polices)
            z.writestr("word/_rels/fontTable.xml.rels", relations_polices.vers_xml())
            for nom_fichier, octets in fichiers_polices.items():
                z.writestr(f"word/fonts/{nom_fichier}", octets)
        z.writestr("word/_rels/document.xml.rels", relations.vers_xml())
        for item in document.media.values():
            z.writestr(f"word/media/{item.media_ref}.{item.extension}", item.donnees)
