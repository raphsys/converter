"""Écriture du package OOXML.

Un .docx est un zip de parties XML. On l'écrit à la main plutôt qu'avec python-docx :
cette bibliothèque ne sait produire ni ancres flottantes ni géométries personnalisées,
qui sont exactement ce dont l'approche a besoin.
"""
import json
import mimetypes
import os
import posixpath
import stat
import tempfile
import zipfile
from xml.etree import ElementTree
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pdfexact.analysis.options import PackageOptions
from pdfexact.ir import Document
from pdfexact.render.fonts_embed import nouveau_guid, obfusquer_police
from pdfexact.render.docx_writer import construire_document_xml_compat

TYPES_RELATIONS = {
    "image": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
    "hyperlink": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    "font": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font",
    "fontTable": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable",
    "styles": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
    "settings": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
    "numbering": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering",
    "renderManifest": "urn:pdfexact:relationships:render-manifest",
}

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_MANIFEST_PART = "pdfexact/render-manifest.json"


def _xml(root):
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _target_part(source, target):
    uri = urlsplit(target)
    if uri.scheme or uri.netloc or uri.query or "\\" in target:
        raise ValueError("invalid-internal-target")
    path = unquote(uri.path)
    if path.startswith("/"):
        path = path[1:]
    elif path:
        path = posixpath.join(posixpath.dirname(source), path)
    else:
        path = source
    normalized = posixpath.normpath(path)
    if normalized in {"", ".", ".."} or normalized.startswith("../") or "\\" in normalized:
        raise ValueError("target-outside-package")
    return normalized


def _target_key(source, target):
    fragment = urlsplit(target).fragment
    return _target_part(source, target) + ("#" + fragment if fragment else "")

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
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
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
<w:doNotExpandShiftReturn/>
<w:doNotUseHTMLParagraphAutoSpacing/>
<w:compatSetting w:name="compatibilityMode"
 w:uri="http://schemas.microsoft.com/office/word" w:val="15"/>
<w:compatSetting w:name="useWord2013TrackBottomHyphenation"
 w:uri="http://schemas.microsoft.com/office/word" w:val="1"/>
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
    source_ids: tuple[str, ...] = ()


class GestionnaireRelations:
    """Attribue les identifiants rId et collecte les relations de document.xml."""

    def __init__(self, source_part="word/document.xml"):
        self._entrees: list[Relation] = []
        self._par_cible: dict[tuple[str, str, bool], str] = {}
        self.source_part = source_part

    @property
    def source_mapping(self):
        return {entry.identifiant: entry.source_ids for entry in self._entrees}

    def ajouter(self, cible: str, type_rel: str, externe: bool = False, *, source_ids=()) -> str:
        """Retourne l'identifiant de relation, en réutilisant celui d'une cible connue."""
        if type_rel not in TYPES_RELATIONS:
            raise ValueError(f"unknown-relation-type:{type_rel}")
        if not cible:
            raise ValueError("missing-relation-target")
        target = cible if externe else _target_key(self.source_part, cible)
        cle = (target, TYPES_RELATIONS[type_rel], externe)
        if cle in self._par_cible:
            identifiant = self._par_cible[cle]
            for index, entry in enumerate(self._entrees):
                if entry.identifiant == identifiant:
                    ids = tuple(dict.fromkeys((*entry.source_ids, *source_ids)))
                    self._entrees[index] = replace(entry, source_ids=ids)
                    break
            return identifiant

        identifiant = f"rId{len(self._entrees) + 1}"
        self._entrees.append(Relation(identifiant, TYPES_RELATIONS[type_rel], cible, externe, tuple(source_ids)))
        self._par_cible[cle] = identifiant
        return identifiant

    def vers_xml(self) -> str:
        root = ElementTree.Element("Relationships", xmlns=_REL)
        for relation in self._entrees:
            attributes = {"Id": relation.identifiant, "Type": relation.type_rel, "Target": relation.cible}
            if relation.externe:
                attributes["TargetMode"] = "External"
            ElementTree.SubElement(root, "Relationship", attributes)
        return _xml(root).decode("utf-8")

    def deduplicer_medias(self, aliases):
        entries = []
        for entry in self._entrees:
            if not entry.externe and entry.type_rel == TYPES_RELATIONS["image"]:
                target = _target_part(self.source_part, entry.cible)
                if target in aliases:
                    fragment = urlsplit(entry.cible).fragment
                    relative = posixpath.relpath(aliases[target], posixpath.dirname(self.source_part))
                    entry = replace(entry, cible=relative + ("#" + fragment if fragment else ""))
            entries.append(entry)
        self._entrees = entries
        self._par_cible = {
            (entry.cible if entry.externe else _target_key(self.source_part, entry.cible),
             entry.type_rel, entry.externe): entry.identifiant
            for entry in self._entrees
        }


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
    embedded: dict[bytes, tuple[str, str]] = {}
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

        if octets not in embedded:
            guid = nouveau_guid()
            nom_fichier = f"font{compteur}.odttf"
            compteur += 1
            fichiers[nom_fichier] = obfusquer_police(octets, guid)
            embedded[octets] = (nom_fichier, guid)
        nom_fichier, guid = embedded[octets]
        rel_id = relations.ajouter(f"fonts/{nom_fichier}", "font", source_ids=(asset.font_id,))
        familles[famille][style] = (rel_id, guid)

    root = ElementTree.Element("w:fonts", {"xmlns:w": _W, "xmlns:r": _R})
    for famille in sorted(familles):
        font = ElementTree.SubElement(root, "w:font", {"w:name": famille})
        for style, attribut in _FONT_ATTR_PAR_STYLE.items():
            if style in familles[famille]:
                rel_id, guid = familles[famille][style]
                ElementTree.SubElement(font, f"w:{attribut}", {"r:id": rel_id, "w:fontKey": guid})
    return _xml(root).decode("utf-8"), fichiers


def ecrire_docx(
    document: Document,
    chemin,
    *,
    native_rewriter: bool = False,
    render_plan=None,
    package_options: dict | PackageOptions | None = None,
):
    """Écrit le package après validation du plan et de sa couverture source.

    Pendant la migration, un plan explicite exige ``native_rewriter=True`` : le
    writer de compatibilité ne sait pas encore consommer ses décisions.
    ``include_scene_manifest`` exporte les contrats disponibles. La provenance
    XML stricte reste un refus explicite en attendant le mapping du backend.
    """
    options = _package_options(package_options)
    if options["strict_provenance"]:
        raise ValueError("incomplete-provenance:xml-source-mapping-unavailable")
    contract_report = None
    if native_rewriter or render_plan is not None:
        from pdfexact.render.native_contract import valider_contrat_word_native

        if render_plan is None:
            from pdfexact.render.render_plan import build_document_render_plan

            render_plan = build_document_render_plan(document)
        contract_report = valider_contrat_word_native(document, render_plan)
        if not contract_report.conforme:
            errors = contract_report.errors + tuple(
                f"declared-non-representable:{source_id}:{reason}"
                for source_id, reason in contract_report.nonrepresentable_sources
            )
            raise ValueError("invalid-word-native-contract: " + "; ".join(errors))
        if not native_rewriter:
            raise ValueError("render-plan-requires-native-rewriter")

    relations = GestionnaireRelations()
    relations_polices = GestionnaireRelations("word/fontTable.xml")
    # Déclarée en premier : une partie référencée dans [Content_Types] sans relation
    # correspondante fait échouer l'ouverture.
    relations.ajouter("styles.xml", "styles")
    relations.ajouter("settings.xml", "settings")
    table_polices, fichiers_polices = (
        _table_polices_xml(document, relations_polices) if options["embed_fonts"] else ("", {})
    )
    if fichiers_polices:
        relations.ajouter("fontTable.xml", "fontTable")
    if native_rewriter:
        from pdfexact.render.word_native_rewriter import rewrite_document_xml

        rewrite_result = rewrite_document_xml(document, relations, render_plan=render_plan)
        rewrite_result.diagnostics.reader_risks.extend(
            {"kind": "non-representable-source", "element_id": source_id, "reason": reason}
            for source_id, reason in contract_report.nonrepresentable_sources
        )
        corps = rewrite_result.xml
    else:
        rewrite_result = None
        corps = construire_document_xml_compat(document, relations)

    media, aliases, media_manifest = _media_parts(document)
    relations.deduplicer_medias(aliases)
    parts = {
        "_rels/.rels": _RELS_RACINE,
        "word/document.xml": corps,
        "word/styles.xml": _STYLES,
        "word/settings.xml": _SETTINGS,
        **media,
    }
    if rewrite_result is not None and rewrite_result.numbering_xml:
        parts["word/numbering.xml"] = rewrite_result.numbering_xml
    if fichiers_polices:
        parts["word/fontTable.xml"] = table_polices
        parts["word/_rels/fontTable.xml.rels"] = relations_polices.vers_xml()
        parts.update({f"word/fonts/{name}": data for name, data in fichiers_polices.items()})
    if options["include_scene_manifest"]:
        relations.ajouter("../" + _MANIFEST_PART, "renderManifest")
        manifest = exporter_manifest_render(
            chemin, render_plan, document=document, package_options=options,
            media_manifest=media_manifest,
        )
        manifest["font_relations"] = relations_polices.source_mapping
        parts[_MANIFEST_PART] = json.dumps(manifest, ensure_ascii=True, sort_keys=True, allow_nan=False)
    parts["word/_rels/document.xml.rels"] = relations.vers_xml()
    parts["[Content_Types].xml"] = _content_types_for(parts)
    target = Path(chemin)
    previous_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    with tempfile.TemporaryDirectory(prefix=f".{target.name}.", dir=target.parent) as directory:
        temporary = Path(directory) / "package.docx"
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        errors = valider_package_ooxml(temporary)
        if errors:
            raise ValueError("invalid-ooxml-package: " + "; ".join(errors))
        if previous_mode is not None:
            temporary.chmod(previous_mode)
        os.replace(temporary, target)
    return rewrite_result


def _package_options(options):
    supplied = asdict(options) if isinstance(options, PackageOptions) else dict(options or {})
    defaults = {"embed_fonts": True, "include_scene_manifest": False, "validate_xml": True, "strict_provenance": False}
    unknown = set(supplied) - set(defaults)
    if unknown:
        raise ValueError("unknown-package-option:" + ",".join(sorted(unknown)))
    if any(not isinstance(value, bool) for value in supplied.values()):
        raise ValueError("invalid-package-option-type")
    defaults.update(supplied)
    if not defaults["validate_xml"]:
        raise ValueError("package-validation-required")
    return defaults


def _content_types_for(parts):
    root = ElementTree.fromstring(_CONTENT_TYPES)
    for node in list(root):
        if node.tag == f"{{{_CT}}}Override" and node.get("PartName", "").lstrip("/") not in parts:
            root.remove(node)
    extensions = {node.get("Extension") for node in root.findall(f"{{{_CT}}}Default")}
    for name in sorted(parts):
        extension = _part_extension(name)
        if extension and extension not in extensions:
            content_type = "application/json" if extension == "json" else mimetypes.guess_type(name)[0] or "application/octet-stream"
            ElementTree.SubElement(root, f"{{{_CT}}}Default", Extension=extension, ContentType=content_type)
            extensions.add(extension)
    # LO 25.2 rejects prefixed ContentTypes names. Keep this lexical choice local;
    # tostring(default_namespace=...) rejects these unqualified XML attributes.
    for node in root.iter():
        node.tag = node.tag.removeprefix(f"{{{_CT}}}")
    root.set("xmlns", _CT)
    return _xml(root)


def _part_extension(name):
    return "rels" if name.endswith(".rels") else posixpath.splitext(name)[1].lstrip(".").lower()


def _media_parts(document):
    parts, aliases, by_content, metadata = {}, {}, {}, {}
    for item in document.media.values():
        name = f"word/media/{item.media_ref}.{item.extension}"
        if _target_part("", "/" + name) != name:
            raise ValueError(f"invalid-media-part:{name}")
        digest = sha256(item.donnees).hexdigest()
        if item.content_hash is not None and item.content_hash != digest:
            raise ValueError(f"source-media-hash-mismatch:{item.media_ref}")
        key = (item.extension.lower(), digest)
        canonical = by_content.setdefault(key, name)
        if canonical in parts and parts[canonical] != item.donnees:
            raise ValueError(f"conflicting-media-part:{canonical}")
        parts[canonical] = item.donnees
        aliases[name] = canonical
        entry = metadata.setdefault(canonical, {
            "part": canonical, "sha256": digest, "aliases": [], "source_ids": [], "assets": [],
        })
        entry["aliases"].append(name)
        entry["source_ids"] = list(dict.fromkeys((*entry["source_ids"], *item.source_ids)))
        entry["assets"].append({key: value for key, value in asdict(item).items() if key != "donnees"})
    return parts, aliases, list(metadata.values())


@dataclass
class _Package:
    parts: dict[str, bytes] = field(default_factory=dict)
    trees: dict[str, ElementTree.Element] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    relationships: dict[str, dict[str, tuple[str, str, bool]]] = field(default_factory=dict)
    relation_errors: list[str] = field(default_factory=list)
    content_types: dict[str, str] = field(default_factory=dict)


def _source_part(rels_name):
    if rels_name == "_rels/.rels":
        return ""
    directory, name = posixpath.split(rels_name)
    if posixpath.basename(directory) != "_rels" or not name.endswith(".rels"):
        raise ValueError("invalid-rels-part")
    return posixpath.join(posixpath.dirname(directory), name[:-5])


def _load_package(chemin):
    if isinstance(chemin, _Package):
        return chemin
    package = _Package()
    try:
        with zipfile.ZipFile(chemin) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name in package.parts:
                    package.errors.append(f"duplicate-part:{name}")
                if name.startswith("/") or "\\" in name or posixpath.normpath(name) != name or name.startswith("../"):
                    package.errors.append(f"invalid-part-name:{name}")
                package.parts[name] = archive.read(info)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        package.errors.append("invalid-docx-zip")
        return package
    for name in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
        if name not in package.parts:
            package.errors.append(f"missing-part:{name}")
    for name, data in package.parts.items():
        if name.lower().endswith((".xml", ".rels", ".vml", ".svg")):
            try:
                package.trees[name] = ElementTree.fromstring(data)
            except ElementTree.ParseError:
                package.errors.append(f"invalid-xml:{name}")
    types = package.trees.get("[Content_Types].xml")
    if types is not None:
        defaults = {node.get("Extension", "").lower(): node.get("ContentType", "") for node in types.findall(f"{{{_CT}}}Default")}
        overrides = {unquote(node.get("PartName", "")).lstrip("/"): node.get("ContentType", "") for node in types.findall(f"{{{_CT}}}Override")}
        for name, data in package.parts.items():
            content_type = overrides.get(name, defaults.get(_part_extension(name), ""))
            package.content_types[name] = content_type
            if content_type.split(";", 1)[0].endswith(("/xml", "+xml")) and not name.lower().endswith((".xml", ".rels", ".vml", ".svg")):
                try:
                    package.trees[name] = ElementTree.fromstring(data)
                except ElementTree.ParseError:
                    package.errors.append(f"invalid-xml:{name}")
    _read_relationships(package)
    return package


def _read_relationships(package):
    errors = package.relation_errors
    for name, root in package.trees.items():
        if not name.lower().endswith(".rels") and package.content_types.get(name) != "application/vnd.openxmlformats-package.relationships+xml":
            continue
        try:
            source = _source_part(name)
        except ValueError:
            errors.append(f"invalid-rels-part:{name}")
            continue
        if source and source not in package.parts:
            errors.append(f"missing-relation-source:{source}")
        if root.tag != f"{{{_REL}}}Relationships":
            errors.append(f"invalid-relationships-root:{name}")
        entries = package.relationships.setdefault(source, {})
        for node in root:
            ident, kind, target = node.get("Id"), node.get("Type"), node.get("Target")
            if node.tag != f"{{{_REL}}}Relationship" or not all((ident, kind, target)):
                errors.append(f"invalid-relationship:{name}:{ident or 'missing-id'}")
                continue
            if ident in entries:
                errors.append(f"duplicate-relationship-id:{name}:{ident}")
            mode = node.get("TargetMode", "Internal")
            try:
                scheme = urlsplit(kind).scheme
            except ValueError:
                scheme = ""
            if mode not in {"Internal", "External"} or not scheme:
                errors.append(f"invalid-relationship-type-or-mode:{name}:{ident}")
            external = mode == "External"
            if not external:
                try:
                    target = _target_part(source, target)
                except ValueError:
                    errors.append(f"invalid-relation-target:{name}:{ident}")
                    continue
                if target not in package.parts:
                    errors.append(f"missing-relation-target:{target}")
            entries[ident] = (kind, target, external)


def _content_type_errors(package):
    root = package.trees.get("[Content_Types].xml")
    if root is None:
        return []
    errors, defaults, overrides = [], {}, {}
    if root.tag != f"{{{_CT}}}Types":
        errors.append("invalid-content-types-root")
    for node in root:
        content_type = node.get("ContentType")
        if node.tag == f"{{{_CT}}}Default":
            key = node.get("Extension", "").lower()
            if not key or not content_type or key in defaults:
                errors.append(f"invalid-content-type-default:{key}")
            defaults[key] = content_type
        elif node.tag == f"{{{_CT}}}Override":
            part = node.get("PartName", "")
            try:
                key = _target_part("", part)
            except ValueError:
                errors.append(f"invalid-content-type-part:{part}")
                continue
            if not part.startswith("/") or not content_type or key in overrides or key not in package.parts:
                errors.append(f"invalid-content-type-override:{key}")
            overrides[key] = content_type
        else:
            errors.append("invalid-content-type-entry")
    for name in package.parts:
        if name != "[Content_Types].xml" and not overrides.get(name) and not defaults.get(_part_extension(name)):
            errors.append(f"missing-content-type:{name}")
    return errors


def valider_package_ooxml(chemin, *, strict_provenance=False) -> list[str]:
    """Valide les parties XML et leurs contrats avant publication du ZIP."""
    package = _load_package(chemin)
    errors = [*package.errors, *_content_type_errors(package)]
    expected_roots = {"word/document.xml": "document", "word/styles.xml": "styles", "word/settings.xml": "settings",
                      "word/fontTable.xml": "fonts", "word/numbering.xml": "numbering"}
    for name, local in expected_roots.items():
        root = package.trees.get(name)
        if root is not None and root.tag != f"{{{_W}}}{local}":
            errors.append(f"invalid-part-root:{name}")
    errors.extend(valider_relations(package))
    errors.extend(valider_medias(package))
    errors.extend(valider_fonts(package))
    errors.extend(valider_styles(package))
    errors.extend(valider_numbering(package))
    errors.extend(valider_provenance(package, strict=strict_provenance))
    return list(dict.fromkeys(errors))


def valider_relations(chemin) -> list[str]:
    """Resout toutes les relations par URI POSIX, puis leurs references XML."""
    package = _load_package(chemin)
    errors = [*package.errors, *package.relation_errors]
    office = [entry for entry in package.relationships.get("", {}).values() if entry[0] == _R + "/officeDocument"]
    if len(office) != 1 or office[0][1:] != ("word/document.xml", False):
        errors.append("missing-or-invalid-office-document-relationship")
    root_types = {"styles": "styles", "settings": "settings", "numbering": "numbering", "fontTable": "fonts"}
    for source, entries in package.relationships.items():
        for ident, (kind, target, external) in entries.items():
            local = root_types.get(kind.removeprefix(_R + "/"))
            if local is not None:
                tree = package.trees.get(target)
                if external or tree is None or tree.tag != f"{{{_W}}}{local}":
                    errors.append(f"invalid-related-part:{source}:{ident}:{target}")
    for name, root in package.trees.items():
        if name.endswith(".rels"):
            continue
        entries = package.relationships.get(name, {})
        for node in root.iter():
            for attribute, ident in node.attrib.items():
                if attribute in {f"{{{_R}}}id", f"{{{_R}}}embed", f"{{{_R}}}link", "{urn:schemas-microsoft-com:office:office}relid"}:
                    if not ident or ident not in entries:
                        errors.append(f"missing-relationship-id:{name}:{ident}")
                    elif node.tag == f"{{{_W}}}hyperlink" and entries[ident][0] != TYPES_RELATIONS["hyperlink"]:
                        errors.append(f"invalid-hyperlink-reference:{name}:{ident}")
    return list(dict.fromkeys(errors))


def _asset_errors(package, kind):
    errors = []
    expected = TYPES_RELATIONS[kind]
    for source, entries in package.relationships.items():
        for ident, (relation_type, target, external) in entries.items():
            if relation_type == expected and not external and target not in package.parts:
                errors.append(f"missing-{kind}:{source}:{ident}:{target}")
            if relation_type == expected and external and kind == "font":
                errors.append(f"external-font:{source}:{ident}")
            if relation_type == expected and not external and target in package.parts:
                content_type = package.content_types.get(target, "")
                if kind == "image" and not content_type.startswith("image/"):
                    errors.append(f"invalid-image-content-type:{source}:{ident}:{target}")
                if kind == "font" and (content_type.startswith("image/") or content_type.endswith(("/xml", "+xml"))):
                    errors.append(f"invalid-font-content-type:{source}:{ident}:{target}")
                if not package.parts[target]:
                    errors.append(f"empty-{kind}:{target}")
    return errors


def valider_medias(chemin) -> list[str]:
    """Verifie les relations d'images DrawingML et VML dans chaque partie."""
    package = _load_package(chemin)
    errors = [*package.errors, *package.relation_errors, *_asset_errors(package, "image")]
    for name, root in package.trees.items():
        for node in root.iter():
            if node.tag not in {"{http://schemas.openxmlformats.org/drawingml/2006/main}blip", "{urn:schemas-microsoft-com:vml}imagedata"}:
                continue
            refs = [value for key, value in node.attrib.items() if key in {f"{{{_R}}}id", f"{{{_R}}}embed", f"{{{_R}}}link", "{urn:schemas-microsoft-com:office:office}relid"}]
            if not refs:
                errors.append(f"missing-image-reference:{name}")
            for ident in refs:
                entry = package.relationships.get(name, {}).get(ident)
                if entry is None or entry[0] != TYPES_RELATIONS["image"] or (f"{{{_R}}}embed" in node.attrib and entry[2]):
                    errors.append(f"invalid-image-reference:{name}:{ident}")
    return list(dict.fromkeys(errors))


def _related_xml_parts(package, kind, default):
    names = {
        target for entries in package.relationships.values()
        for relation_type, target, external in entries.values()
        if relation_type == TYPES_RELATIONS[kind] and not external
    }
    if default in package.trees:
        names.add(default)
    return [(name, package.trees[name]) for name in sorted(names) if name in package.trees]


def valider_fonts(chemin) -> list[str]:
    """Verifie fontTable, les IDs d'embedding, les cles et les parties binaires."""
    package = _load_package(chemin)
    errors = [*package.errors, *package.relation_errors, *_asset_errors(package, "font")]
    for part, root in _related_xml_parts(package, "fontTable", "word/fontTable.xml"):
        names = set()
        for font in root.findall(f"{{{_W}}}font"):
            name = font.get(f"{{{_W}}}name")
            if not name or name in names:
                errors.append(f"invalid-font-name:{name}")
            names.add(name)
            for node in font:
                if node.tag not in {f"{{{_W}}}{value}" for value in _FONT_ATTR_PAR_STYLE.values()}:
                    continue
                ident = node.get(f"{{{_R}}}id")
                entry = package.relationships.get(part, {}).get(ident)
                if entry is None or entry[0] != TYPES_RELATIONS["font"] or entry[2]:
                    errors.append(f"invalid-font-reference:{part}:{name}:{ident}")
                try:
                    UUID(node.get(f"{{{_W}}}fontKey", ""))
                except ValueError:
                    errors.append(f"invalid-font-key:{part}:{name}:{ident}")
    return list(dict.fromkeys(errors))


def valider_styles(chemin) -> list[str]:
    """Verifie les identifiants, references, types et cycles d'heritage des styles."""
    package = _load_package(chemin)
    errors, styles, parents, definitions = list(package.errors), {}, {}, []
    for part, root in _related_xml_parts(package, "styles", "word/styles.xml"):
        for node in root.findall(f"{{{_W}}}style"):
            ident, kind = node.get(f"{{{_W}}}styleId"), node.get(f"{{{_W}}}type")
            if not ident or ident in styles or kind not in {"paragraph", "character", "table", "numbering"}:
                errors.append(f"invalid-style-id-or-type:{ident}")
            styles[ident] = kind
            definitions.append((part, kind, node))
            parent = node.find(f"{{{_W}}}basedOn")
            if parent is not None:
                parents[ident] = parent.get(f"{{{_W}}}val")
    reference_types = {"pStyle": "paragraph", "rStyle": "character", "tblStyle": "table"}
    for name, tree in package.trees.items():
        for node in tree.iter():
            local = node.tag.removeprefix(f"{{{_W}}}")
            if local not in {*reference_types, "basedOn", "next", "link", "styleLink", "numStyleLink"}:
                continue
            ident = node.get(f"{{{_W}}}val")
            if ident not in styles or (local in reference_types and styles[ident] != reference_types[local]):
                errors.append(f"missing-or-invalid-style:{name}:{ident}")
    for name, kind, definition in definitions:
        expected = {"basedOn": kind, "next": "paragraph", "link": {"paragraph": "character", "character": "paragraph"}.get(kind)}
        for local, target_type in expected.items():
            for node in definition.findall(f"{{{_W}}}{local}"):
                ident = node.get(f"{{{_W}}}val")
                if target_type is None or styles.get(ident) != target_type:
                    errors.append(f"invalid-style-reference-type:{name}:{local}:{ident}")
    for ident in parents:
        seen, current = set(), ident
        while current in parents:
            if current in seen:
                errors.append(f"style-inheritance-cycle:{ident}")
                break
            seen.add(current)
            current = parents[current]
    return errors


def _number_id(value, *, positive=False):
    if value is None or not value.isascii() or not value.isdecimal() or (positive and int(value) == 0):
        return None
    return int(value)


def valider_numbering(chemin) -> list[str]:
    """Verifie les IDs numeriques, les definitions abstraites et leurs references."""
    package = _load_package(chemin)
    errors, abstracts, nums = list(package.errors), {}, {}
    for _, root in _related_xml_parts(package, "numbering", "word/numbering.xml"):
        for tag, attr, output in (("abstractNum", "abstractNumId", abstracts), ("num", "numId", nums)):
            for node in root.findall(f"{{{_W}}}{tag}"):
                ident = _number_id(node.get(f"{{{_W}}}{attr}"), positive=tag == "num")
                if ident is None or ident in output:
                    errors.append(f"invalid-numbering-id:{tag}:{ident}")
                output[ident] = node
        for ident, node in nums.items():
            links = node.findall(f"{{{_W}}}abstractNumId")
            if len(links) != 1 or _number_id(links[0].get(f"{{{_W}}}val")) not in abstracts:
                errors.append(f"missing-numbering-abstract:{ident}")
            overrides = [_number_id(value.get(f"{{{_W}}}ilvl")) for value in node.findall(f"{{{_W}}}lvlOverride")]
            if len(overrides) != len(set(overrides)) or any(value is None or value > 8 for value in overrides):
                errors.append(f"invalid-numbering-level-overrides:{ident}")
        for ident, node in abstracts.items():
            levels = [_number_id(level.get(f"{{{_W}}}ilvl")) for level in node.findall(f"{{{_W}}}lvl")]
            if len(levels) != len(set(levels)) or any(value is None or value > 8 for value in levels):
                errors.append(f"invalid-numbering-levels:{ident}")
    for name, tree in package.trees.items():
        for node in tree.iter(f"{{{_W}}}numId"):
            ident = _number_id(node.get(f"{{{_W}}}val"))
            if ident is None or (ident != 0 and ident not in nums):
                errors.append(f"missing-numbering-reference:{name}:{ident}")
        for properties in tree.iter(f"{{{_W}}}numPr"):
            node = properties.find(f"{{{_W}}}numId")
            ident = _number_id(node.get(f"{{{_W}}}val")) if node is not None else None
            if ident not in nums:
                continue
            level_node = properties.find(f"{{{_W}}}ilvl")
            level = _number_id(level_node.get(f"{{{_W}}}val")) if level_node is not None else 0
            number = nums[ident]
            link = number.find(f"{{{_W}}}abstractNumId")
            abstract = abstracts.get(_number_id(link.get(f"{{{_W}}}val"))) if link is not None else None
            levels = {_number_id(value.get(f"{{{_W}}}ilvl")) for value in number.findall(f"{{{_W}}}lvlOverride")}
            if abstract is not None:
                levels.update(_number_id(value.get(f"{{{_W}}}ilvl")) for value in abstract.findall(f"{{{_W}}}lvl"))
            if level is None or level > 8 or level not in levels:
                errors.append(f"missing-numbering-level:{name}:{ident}:{level}")
    return errors


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate-json-key:{key}")
        result[key] = value
    return result


def valider_provenance(chemin, *, strict=False) -> list[str]:
    """Verifie les contrats serialises; aucun mapping XML absent n'est infere."""
    package = _load_package(chemin)
    errors = list(package.errors)
    if strict:
        errors.append("incomplete-provenance:xml-source-mapping-unavailable")
    if _MANIFEST_PART not in package.parts:
        return errors
    try:
        manifest = json.loads(package.parts[_MANIFEST_PART], object_pairs_hook=_unique_json_object)
        if manifest["schema_version"] != 1 or manifest["provenance"]["status"] != "incomplete":
            errors.append("unsupported-provenance-schema")
        if not manifest["provenance"].get("reason"):
            errors.append("missing-provenance-reason")
        known_sources = set(manifest["sources"])
        known_sources.update(source_id for source in manifest["sources"].values() for source_id in source.get("source_ids", ()))
        planned = {}
        for page_index, items in manifest["pages"].items():
            for item in items:
                ident = item["element_id"]
                if not ident or ident in planned or not item["reason_codes"]:
                    errors.append(f"invalid-manifest-element:{ident}")
                for source_id in item.get("source_ids", ()):
                    if source_id not in known_sources:
                        errors.append(f"unknown-manifest-source:{ident}:{source_id}")
                planned[ident] = page_index
        for ident, source in manifest["sources"].items():
            if source.get("element_id") != ident:
                errors.append(f"manifest-source-id-mismatch:{ident}")
            coverage = source.get("coverage")
            if not coverage or not coverage.get("reason"):
                errors.append(f"missing-manifest-source-coverage:{ident}")
            elif coverage["relationship"] not in {"retained", "transformed", "duplicate", "raster-replacement", "non-representable"}:
                errors.append(f"unknown-manifest-coverage-relationship:{ident}")
            elif coverage["relationship"] == "non-representable":
                if coverage["target_ids"] or not source.get("evidence"):
                    errors.append(f"invalid-manifest-nonrepresentable:{ident}")
            elif not coverage["target_ids"] or any(target not in planned for target in coverage["target_ids"]):
                errors.append(f"missing-manifest-target:{ident}")
            elif any(planned[target] != str(source.get("page_index")) for target in coverage["target_ids"]):
                errors.append(f"manifest-coverage-page-mismatch:{ident}")
        for entry in manifest["media"]:
            part = entry["part"]
            if part not in package.parts or sha256(package.parts[part]).hexdigest() != entry["sha256"]:
                errors.append(f"manifest-media-mismatch:{part}")
    except (ValueError, KeyError, TypeError, AttributeError):
        errors.append("invalid-render-manifest")
    return errors


def exporter_manifest_render(chemin, render_plan, *, document=None, package_options=None, media_manifest=None) -> dict:
    """Retourne un manifeste JSON stable pour l'audit et les golden tests."""
    manifeste = {
        "schema_version": 1,
        "provenance": {"status": "incomplete", "reason": "xml-source-mapping-unavailable" if render_plan is not None else "render-plan-unavailable"},
        "document": {
            "source_pdf_id": document.source_pdf_id, "scene_id": document.scene_id,
            "options_snapshot": document.options_snapshot,
        } if document is not None else {},
        "analysis_options": asdict(render_plan.options) if render_plan is not None else {},
        "package_options": dict(package_options or {}),
        "sources": {
            ident: {**source.snapshot(), "coverage": asdict(coverage) if (coverage := (render_plan.source_coverage or {}).get(ident)) else None}
            for ident, source in sorted((render_plan.source_inventory or {}).items())
        } if render_plan is not None else {},
        "media": media_manifest or [],
        "fonts": [
            {"font_id": asset.font_id, "family": asset.famille, "extension": asset.extension,
             "recognized": asset.reconnue, "metrics": dict(asset.metriques)}
            for asset in sorted(document.polices.values(), key=lambda value: value.font_id)
        ] if document is not None else [],
        "pages": {
            str(page_index): [
                {
                    "element_id": item.element.element_id,
                    "source_ids": list(item.element.source_ids),
                    "mode": item.decision.mode.value,
                    "reason_codes": list(item.decision.reason_codes),
                    "decision": asdict(item.decision),
                    "materialization_count": len(item.materialization.fragments) if item.materialization is not None else 0,
                    "bbox": {
                        "x0": item.element.bbox.x0,
                        "y0": item.element.bbox.y0,
                        "x1": item.element.bbox.x1,
                        "y1": item.element.bbox.y1,
                    },
                    "orientation": item.element.orientation,
                    "z_order": item.element.z_order,
                    "style": dict(item.element.style),
                }
                for item in items
            ]
            for page_index, items in sorted(render_plan.pages.items())
        } if render_plan is not None else {},
    }
    from pdfexact.scene import _snapshot_value

    return _snapshot_value(manifeste)
