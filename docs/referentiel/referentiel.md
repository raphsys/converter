# Référentiel des éléments, attributs et propriétés des bboxes

Rendu depuis `referentiel.json` (source unique) par `scripts/rendre_referentiel.py`. Ne pas éditer à la main.

- Convention des positions : [x, y, largeur, hauteur] en points, origine en haut à gauche, x vers la droite, y vers le bas.
- Politique des champs : present_null_when_unknown : chaque champ est toujours présent ; il vaut null quand la valeur n'est pas établie (jamais devinée).

**131 éléments, 244 attributs, 58 propriétés de bbox.** Colonne vysi : noms existants dans vysi ; « — » = absent de vysi.

## Sources

- **PDF** : ISO 32000-2 (PDF 2.0) : objets de contenu, XObjects, annotations, AcroForm, contenu optionnel
- **PDF-TAG** : ISO 32000-2 §14.8 : types de structure du PDF balisé (Tagged PDF)
- **OOXML-W** : ECMA-376 WordprocessingML (DOCX)
- **OOXML-D** : ECMA-376 DrawingML (formes, images, graphiques, SmartArt)
- **OOXML-P** : ECMA-376 PresentationML (PPTX)
- **OOXML-M** : ECMA-376 Office Math (OMML)
- **ODF** : OASIS OpenDocument 1.3
- **CSS** : CSS (modèle de boîte, CSS Text, Fonts, Backgrounds & Borders, Multi-column, Writing Modes)
- **HTML** : HTML Living Standard
- **VYSI** : vysi : taxonomie FT01, FT02 typographie, FT03 cadres, AD06-AD12, ADQ006, DS v2
- **PADDLEX** : PP-DocLayout_plus-L : étiquettes de zones (inference.yml)
- **PERFECT** : vysi/docs/archive/indication_docs_parser_pour_vysi/perfect_document_extractor.py (schéma perfect_extraction.v1)

## 1. Éléments

### Page et ses régions physiques (`page`)

| id | élément | sources | vysi |
|---|---|---|---|
| `document` | Document | PDF-TAG:Document, OOXML-W:document, HTML:html, PERFECT:document | document |
| `page` | Page | PDF:Page, OOXML-P:sld, PERFECT:pages[] | page, fixed_page |
| `section` | Section (mise en page propre : marges, colonnes, orientation) | OOXML-W:sectPr, ODF:text:section, PDF-TAG:Sect | section, flow_section |
| `en_tete` | En-tête de page | OOXML-W:hdr, PDF:Artifact/Pagination, PADDLEX:header, PERFECT:text.headers | header |
| `pied_de_page` | Pied de page | OOXML-W:ftr, PDF:Artifact/Pagination, PADDLEX:footer, PERFECT:text.footers | footer |
| `numero_page` | Numéro de page | OOXML-W:PAGE field, PDF:Artifact/Pagination, PADDLEX:number, PERFECT:text.page_numbers | page_number |
| `arriere_plan_page` | Arrière-plan de page | OOXML-W:background, PDF:Artifact/Background, CSS:background, PERFECT:background | — |
| `filigrane` | Filigrane | OOXML-W:VML watermark, PDF:Watermark annotation, PERFECT:background.watermark | — |
| `bordure_page` | Bordure de page | OOXML-W:pgBorders | — |
| `note_marginale` | Note ou texte en marge | PDF-TAG:Aside, PADDLEX:aside_text | marginalia |

### Régions de mise en page (colonnes, cadres, zones) (`region`)

| id | élément | sources | vysi |
|---|---|---|---|
| `region_contenu` | Région de contenu | VYSI:frame_type content_region | content_region |
| `colonne` | Colonne | OOXML-W:cols, CSS:column-count, ODF:style:columns, PERFECT:columns | column |
| `cadre_texte` | Cadre ou zone de texte positionné | OOXML-W:framePr, OOXML-D:wps:txbx, ODF:draw:text-box | text, framed_text |
| `encadre` | Encadré / callout | PDF-TAG:Aside, OOXML-D:callout shapes | callout |
| `barre_laterale` | Barre latérale | PDF-TAG:Aside, HTML:aside, PERFECT:columns.sidebar | sidebar |
| `groupe` | Groupe d'éléments | OOXML-D:grpSp, PDF:Form XObject, PDF-TAG:Div | group |
| `zone_decoupe` | Zone de découpe (clip) | PDF:clipping path, CSS:clip-path | clipping |
| `region_implicite` | Région de mise en page implicite | VYSI:frame_type implicit_layout | implicit_layout |
| `region_corps` | Corps de page (contenu principal) | PERFECT:regions[] type body, role main_content | body |
| `region_speciale` | Région spéciale préservée visuellement (code, formule) | PERFECT:formulas_and_specials[] | — |
| `objet_rendu` | Objet de rendu (texte, dessin, image, région spéciale) | PERFECT:render_objects[] | draw_text, draw_image, draw_vector |

### Blocs et éléments textuels (`texte`)

| id | élément | sources | vysi |
|---|---|---|---|
| `titre_document` | Titre du document | PDF-TAG:Title, OOXML-W:Title style, PADDLEX:doc_title | title |
| `sous_titre` | Sous-titre | OOXML-W:Subtitle style, HTML:hgroup | subtitle |
| `chapitre` | Chapitre | PDF-TAG:Part, VYSI:chapter | chapter |
| `intertitre` | Intertitre (niveaux 1 à n) | PDF-TAG:H/H1-H6, OOXML-W:outlineLvl, HTML:h1-h6, PADDLEX:paragraph_title, PERFECT:role heading | heading, section, subsection |
| `paragraphe` | Paragraphe | PDF-TAG:P, OOXML-W:p, HTML:p, PADDLEX:text, PERFECT:role paragraph | paragraph |
| `citation_bloc` | Citation en bloc | PDF-TAG:BlockQuote, HTML:blockquote | quote |
| `legende` | Légende de figure ou de tableau | PDF-TAG:Caption, OOXML-W:Caption style, PADDLEX:figure_title, PERFECT:caption_for_image/table | caption, figure_label |
| `resume` | Résumé (abstract) | PADDLEX:abstract | — |
| `note_bas_page` | Note de bas de page | PDF-TAG:FENote, OOXML-W:footnote, PADDLEX:footnote, PERFECT:document_profile.has_notes | footnote, note |
| `note_fin` | Note de fin | PDF-TAG:FENote, OOXML-W:endnote | endnote |
| `table_des_matieres` | Table des matières / sommaire | PDF-TAG:TOC, OOXML-W:TOC field, PADDLEX:content | toc_block |
| `entree_sommaire` | Entrée de sommaire | PDF-TAG:TOCI | toc_entry |
| `index` | Index | PDF-TAG:Index, OOXML-W:INDEX field | — |
| `entree_index` | Entrée d'index | OOXML-W:XE field | — |
| `glossaire` | Glossaire et ses entrées | HTML:dl | glossary_entry |
| `bibliographie` | Bibliographie | PADDLEX:reference, PERFECT:document_profile.has_references | bibliography_block |
| `entree_bibliographique` | Entrée bibliographique | PDF-TAG:BibEntry, PADDLEX:reference_content | bibliography_reference, reference |
| `bloc_code` | Bloc de code | PDF-TAG:Code, HTML:pre, PADDLEX:algorithm, PERFECT:role code / special_region code | code_block, code |
| `lettrine` | Lettrine | OOXML-W:framePr dropCap, CSS:initial-letter | dropcap |
| `etiquette` | Étiquette / libellé court | PDF-TAG:Lbl | label, graphic_label |
| `metadonnees` | Métadonnées visibles (auteur, date, référence) | PDF:Info/XMP, OOXML-W:core properties, PERFECT:metadata | metadata |
| `texte_dans_image` | Texte contenu dans une image | VYSI:AD05 source_kind ocr | — |
| `texte_sceau` | Texte de sceau / tampon | PADDLEX:seal | — |

### Éléments textuels en ligne (dans un paragraphe) (`en_ligne`)

| id | élément | sources | vysi |
|---|---|---|---|
| `citation_en_ligne` | Citation en ligne | PDF-TAG:Quote, HTML:q | — |
| `mise_en_evidence` | Mise en évidence (emphase, fort) | PDF-TAG:Em/Strong, HTML:em/strong | — |
| `appel_de_note` | Appel de note | OOXML-W:footnoteReference, PDF-TAG:Reference | — |
| `code_en_ligne` | Code en ligne | PDF-TAG:Code, HTML:code | code_literal |
| `ruby` | Annotation ruby (CJK) | PDF-TAG:Ruby/RB/RT/RP, OOXML-W:ruby, HTML:ruby | — |
| `warichu` | Warichu (commentaire en ligne japonais) | PDF-TAG:Warichu | — |
| `indice_exposant` | Indice / exposant | PDF-TAG:Sub, OOXML-W:vertAlign | subscript, superscript |
| `champ` | Champ calculé (date, page, renvoi) | OOXML-W:fldSimple/fldChar, ODF:text:page-number | field |
| `tabulation` | Tabulation et points de conduite | OOXML-W:tab, ODF:text:tab | — |
| `saut` | Saut de ligne, de colonne ou de page | OOXML-W:br, HTML:br | — |
| `symbole` | Symbole d'une police de symboles | OOXML-W:sym | scientific_symbol |

### Granularités du texte (ligne, run, mot, glyphe) (`granularite`)

| id | élément | sources | vysi |
|---|---|---|---|
| `ligne_texte` | Ligne de texte | PDF:text line, VYSI:AD06 text_line, PERFECT:lines[] | text_line, fixed_text_line, line |
| `run` | Segment de style homogène (run / span) | OOXML-W:r, PDF-TAG:Span, PERFECT:spans[] | run, span, text_span, fixed_text_span |
| `mot` | Mot | PDF:word (extraction), PERFECT:words[] | — |
| `glyphe` | Glyphe / grappe de glyphes | PDF:glyph, VYSI:AD06 glyph_cluster, PERFECT:chars[] | glyph_cluster |
| `phrase` | Phrase | VYSI:ADQ006 sentence | sentence |
| `segment_traduisible` | Segment de texte traduisible | PERFECT:text.translatable_segments | — |
| `segment_non_traduisible` | Segment de texte non traduisible (et sa raison) | PERFECT:text.non_translatable_segments | — |

### Listes (`liste`)

| id | élément | sources | vysi |
|---|---|---|---|
| `liste` | Liste | PDF-TAG:L, OOXML-W:numPr, HTML:ul/ol | list, list_block |
| `element_liste` | Élément de liste | PDF-TAG:LI, HTML:li, PERFECT:role list_item | list_item, list_line |
| `marqueur_liste` | Puce ou numéro de liste | PDF-TAG:Lbl, OOXML-W:lvlText | — |
| `corps_element_liste` | Corps d'un élément de liste | PDF-TAG:LBody | — |

### Tableaux (`tableau`)

| id | élément | sources | vysi |
|---|---|---|---|
| `tableau` | Tableau | PDF-TAG:Table, OOXML-W:tbl, HTML:table, PADDLEX:table, PERFECT:tables[] | table |
| `ligne_tableau` | Ligne de tableau | PDF-TAG:TR, OOXML-W:tr | table_row, row |
| `cellule` | Cellule | PDF-TAG:TD, OOXML-W:tc, PERFECT:tables[].cells | table_cell, cell, numeric_cell |
| `cellule_entete` | Cellule d'en-tête | PDF-TAG:TH, HTML:th | header_cell |
| `groupe_lignes` | Groupe de lignes (en-tête, corps, pied) | PDF-TAG:THead/TBody/TFoot, HTML:thead/tbody/tfoot | — |
| `titre_tableau` | Titre de tableau | VYSI:RC table_title | caption |

### Images matricielles (`image`)

| id | élément | sources | vysi |
|---|---|---|---|
| `image` | Image matricielle | PDF:Image XObject / inline image, OOXML-D:pic, PADDLEX:image, PERFECT:images[] | image, image_region, image_frame |
| `photo` | Photographie | VYSI:AD06 candidate_class photo | photo |
| `logo` | Logo | VYSI:AD06 candidate_class logo, PERFECT:document_profile.has_logo | logo |
| `icone` | Icône / pictogramme | HTML:img (icon) | — |
| `page_numerisee` | Page numérisée (image pleine page) | VYSI:raster frame | raster_canvas |
| `signature` | Signature manuscrite | VYSI:AD06 candidate_class signature, PERFECT:document_profile.has_signature | signature |
| `sceau_tampon` | Sceau / tampon | PADDLEX:seal, PDF:Stamp annotation, PERFECT:document_profile.has_stamp | seal, stamp |
| `qr_code` | QR code | VYSI:AD06 candidate_class qr_code | qr_code, qrcode |
| `code_barres` | Code-barres | VYSI:AD06 candidate_class barcode | barcode |
| `ecriture_manuscrite` | Écriture manuscrite | PERFECT:document_profile.has_handwriting, VYSI:AD05 handwriting_recognition | handwriting_recognition |

### Graphismes vectoriels et formes (`vectoriel`)

| id | élément | sources | vysi |
|---|---|---|---|
| `dessin_vectoriel` | Dessin / illustration vectorielle | PDF:path objects, OOXML-D:custGeom, PERFECT:drawings[] shape | drawing, geometry, draw_vector |
| `forme` | Forme géométrique (rectangle, ellipse, flèche…) | OOXML-D:prstGeom, ODF:draw:custom-shape | shape_region, sp |
| `trait_connecteur` | Trait / connecteur | OOXML-D:cxnSp, PDF:path line | cxnSp |
| `degrade` | Dégradé (shading) | PDF:sh / Shading, OOXML-D:gradFill | — |
| `motif` | Motif (pattern) | PDF:Pattern, OOXML-D:pattFill | — |

### Graphiques de données, diagrammes, schémas (`donnees_visuelles`)

| id | élément | sources | vysi |
|---|---|---|---|
| `graphique` | Graphique de données (courbes, barres, secteurs…) | OOXML-D:c:chart, PADDLEX:chart, PERFECT:document_profile.has_charts | chart |
| `diagramme` | Diagramme / SmartArt / organigramme | OOXML-D:dgm, VYSI:AD06 diagram | diagram |
| `figure` | Figure (ensemble illustration + légende) | PDF-TAG:Figure, HTML:figure | figure |
| `carte` | Carte géographique | HTML:img (map) | — |

### Formules (`formule`)

| id | élément | sources | vysi |
|---|---|---|---|
| `formule_bloc` | Formule en bloc | PDF-TAG:Formula, OOXML-M:oMathPara, PADDLEX:formula, PERFECT:role formula / special_region formula | formula, formula_or_equation, equation |
| `formule_en_ligne` | Formule en ligne | OOXML-M:oMath, HTML:math | inline_formula, formula_fragment |
| `numero_formule` | Numéro d'équation | PADDLEX:formula_number | — |

### Expressions spéciales (vysi special_expression_type) (`expression_speciale`)

| id | élément | sources | vysi |
|---|---|---|---|
| `expression_mathematique` | Expression mathématique | VYSI:mathematical_formula | mathematical_formula |
| `formule_chimique` | Formule chimique / équation de réaction | VYSI:chemical_formula, reaction_equation | chemical_formula, reaction_equation |
| `expression_physique` | Expression physique / grandeur avec unité | VYSI:physical_expression, unit_expression | physical_expression, unit_expression, technical_quantity |
| `matrice` | Matrice | VYSI:matrix, OOXML-M:m | matrix |
| `identifiant_technique` | Identifiant technique | VYSI:technical_identifier | technical_identifier, identifier |
| `acronyme_abreviation` | Acronyme / abréviation | VYSI:acronym, abbreviation, HTML:abbr | acronym, abbreviation |
| `url_email` | URL / adresse e-mail | VYSI:url, email | url, email |
| `identifiant_bibliographique` | Identifiant bibliographique (DOI, ISBN) | VYSI:bibliographic_identifier | bibliographic_identifier, doi |
| `date_valeur` | Date, pourcentage, valeur scientifique | VYSI:ADQ006 protected spans | date, percentage, scientific_value |

### Annotations et révisions (`annotation`)

| id | élément | sources | vysi |
|---|---|---|---|
| `commentaire` | Commentaire | PDF:Text annotation, OOXML-W:comment, PERFECT:annotations[] | comment |
| `annotation_balisage` | Surlignage, soulignement, barré, ondulé | PDF:Highlight/Underline/StrikeOut/Squiggly | highlight, underline, strikeout |
| `annotation_texte_libre` | Annotation texte libre | PDF:FreeText | — |
| `annotation_dessin` | Annotation dessinée (encre, ligne, formes) | PDF:Ink/Line/Square/Circle/Polygon/PolyLine | — |
| `annotation_tampon` | Tampon (annotation) | PDF:Stamp | — |
| `piece_jointe` | Pièce jointe | PDF:FileAttachment | fileattachment |
| `caviardage` | Caviardage (redaction) | PDF:Redact | — |
| `revision` | Révision suivie (insertion, suppression, déplacement, format) | OOXML-W:ins/del/moveFrom/moveTo/rPrChange | insert, delete, move_from, move_to, format_change |
| `controle_contenu` | Contrôle de contenu | OOXML-W:sdt | content_control |

### Navigation (liens, signets, plan, renvois) (`navigation`)

| id | élément | sources | vysi |
|---|---|---|---|
| `lien` | Lien hypertexte (externe ou interne) | PDF:Link annotation, OOXML-W:hyperlink, HTML:a | link |
| `signet` | Signet / ancre | OOXML-W:bookmarkStart, PDF:named destination | bookmark |
| `plan_document` | Plan du document (outline) | PDF:Outlines | — |
| `renvoi` | Renvoi interne (voir page, voir figure) | OOXML-W:REF/PAGEREF field | references |

### Champs de formulaire (`formulaire`)

| id | élément | sources | vysi |
|---|---|---|---|
| `champ_formulaire` | Champ de formulaire | PDF:AcroForm Widget, PDF-TAG:Form, OOXML-W:ffData | form_field, widget |
| `champ_texte` | Champ texte | PDF:Tx | — |
| `case_a_cocher` | Case à cocher | PDF:Btn checkbox, OOXML-W:checkBox | — |
| `bouton_radio` | Bouton radio | PDF:Btn radio | — |
| `liste_choix` | Liste / liste déroulante | PDF:Ch, OOXML-W:ddList | — |
| `bouton` | Bouton poussoir | PDF:Btn pushbutton | — |
| `champ_signature` | Champ de signature | PDF:Sig | — |

### Médias et objets incorporés (`media`)

| id | élément | sources | vysi |
|---|---|---|---|
| `objet_incorpore` | Objet incorporé (OLE, document) | OOXML-W:object/oleObj | embedded_document, activex_control |
| `audio_video` | Audio / vidéo | PDF:RichMedia/Sound/Movie, OOXML-P:video | media |
| `modele_3d` | Modèle 3D | PDF:3D annotation | — |

### Décorations (`decoration`)

| id | élément | sources | vysi |
|---|---|---|---|
| `separateur` | Séparateur / filet | PDF:path line, OOXML-W:pBdr, HTML:hr, PERFECT:drawing role rule_line / vertical_rule | separator, table_line |
| `fond_bloc` | Fond coloré / bandeau | OOXML-W:shd, CSS:background-color, PERFECT:drawing role background_rect | decoration |
| `ornement` | Ornement décoratif | PDF:Artifact | decorative |
| `espace_blanc` | Zone d'espace blanc significative | VYSI:AD06 whitespace_region | whitespace_region |

### Non identifié (`inconnu`)

| id | élément | sources | vysi |
|---|---|---|---|
| `inconnu` | Élément non identifié | VYSI:unknown | unknown |

## 2. Attributs des éléments

### identite

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `id` | Identifiant | chaîne | toutes | VYSI:unit_id | unit_id |
| `type` | Type d'élément (référentiel) | id d'élément | toutes | VYSI:kind, object_type | kind, object_type |
| `source_ids` | Identifiants sources natifs | liste | toutes | VYSI:source_native_ids | source_native_ids |
| `origine` | Origine de l'observation | native | ocr | detecteur | calcule | synthetique | toutes | VYSI:AD05 source_kind, origin, PERFECT:source native_pdf | ocr | pdf_image_block | pdf_vector | source_kind, origin |
| `statut_epistemique` | Statut épistémique | observed | derived | inferred | hypothesis | ambiguous | abstained | rejected | toutes | VYSI:epistemic_status | epistemic_status |
| `confiance` | Confiance | 0..1 + méthode | toutes | VYSI:confidence, PERFECT:confidence | confidence |
| `disponibilite` | Disponibilité de chaque valeur | native | calculated | inferred | unavailable | toutes | VYSI:FT02 availability | availability |
| `xref` | Référence d'objet PDF (xref) | entier | image, vectoriel, page | PERFECT:xref, PDF:indirect object | — |

### position

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `page_index` | Index de page | entier, base 0 | toutes | VYSI:physical_page_index | page_index, physical_page_index |
| `bbox` | Boîte englobante | [x, y, largeur, hauteur] pt, origine haut-gauche | toutes | PDF:BBox, CSS:box, VYSI:bbox, PERFECT:bbox [x0,y0,x1,y1] pt, origin top_left | bbox |
| `quad` | Quadrilatère (texte tourné) | 4 points pt | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale, image, vectoriel | PDF:QuadPoints, VYSI:FT02 quad | quad |
| `polygone` | Contour polygonal | liste de points pt | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | VYSI:AD geometry polygon | polygon |
| `ligne_de_base` | Ligne de base | y pt (+ origine x,y) | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:text matrix, VYSI:baseline, origin, PERFECT:origin, baseline | baseline, origin |
| `rotation` | Rotation | degrés | toutes | PDF:Rotate / text matrix, OOXML-D:xfrm rot, CSS:transform, PERFECT:rotation | rotation, text_rotation |
| `retournement` | Retournement horizontal / vertical | booléens | image, vectoriel, region | OOXML-D:xfrm flipH/flipV, CSS:scale(-1) | — |
| `matrice_transformation` | Matrice de transformation | a b c d e f | toutes | PDF:CTM / Tm, CSS:matrix(), PERFECT:transform | text_matrix, transform_to_parent |
| `ordre_empilement` | Ordre d'empilement (z) | entier | toutes | PDF:ordre du flux de contenu, OOXML-D:relativeHeight, CSS:z-index, PERFECT:render_order_index, z_index | z_order, z_index, render_order |
| `couche` | Couche / contenu optionnel | nom de calque | toutes | PDF:Optional Content (OCG), VYSI:layer | layer |
| `ordre_lecture` | Ordre de lecture | index page / document | toutes | PDF-TAG:ordre structurel, VYSI:AD09, PERFECT:reading_order_index | reading_order_index, page_order_index, document_order_index |
| `colonne_index` | Index de colonne | entier | toutes | VYSI:AD09 column_index, PERFECT:layout.column_index | column_index, column_id |
| `couloir` | Couloir de lecture | header | body | footnote | footer | marginalia | container | toutes | VYSI:AD09 lane | lane |
| `ancrage` | Ancrage | en_ligne | flottant | image, vectoriel, region, donnees_visuelles, tableau | OOXML-D:wp:inline / wp:anchor, CSS:float, position | — |
| `position_relative` | Position relative à (page, marge, colonne, paragraphe, caractère) | référence + décalage pt | image, vectoriel, region, donnees_visuelles, tableau | OOXML-D:positionH/positionV relativeFrom, CSS:position | — |
| `habillage` | Habillage du texte | carre | serre | traversant | haut_bas | derriere | devant | aucun | image, vectoriel, region, donnees_visuelles, tableau | OOXML-D:wrapSquare/wrapTight/wrapThrough/wrapTopAndBottom, CSS:shape-outside | — |
| `distance_texte` | Distance au texte (haut, bas, gauche, droite) | pt | image, vectoriel, region, donnees_visuelles, tableau | OOXML-D:distT/distB/distL/distR, CSS:margin | — |
| `visibilite` | Visibilité / rognage | fully_visible | partially_clipped | not_visible | toutes | VYSI:geometry visibility | visibility, clipped |
| `chemin_decoupe` | Chemin de découpe appliqué | référence | toutes | PDF:W/W*, VYSI:clip_ref | clip_ref |
| `index_paragraphe` | Index de paragraphe | entier | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PERFECT:layout.paragraph_index | — |

### caractere

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `police_famille` | Famille de police | nom | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:rFonts, CSS:font-family, VYSI:font_family, PERFECT:style.font_family | font_family, font_name |
| `police_postscript` | Nom PostScript de la police | nom | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:BaseFont, VYSI:font_postscript_name, PERFECT:style.font_postscript_name | font_postscript_name |
| `police_ressource` | Ressource de police (fichier, incorporée) | référence | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:FontFile, VYSI:font_resource_id, PERFECT:style.embedded_font_path | font_resource_id |
| `classe_police` | Classe de police | serif | sans | mono | symbol | unknown | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:FontDescriptor Flags, VYSI:font_family_class, PERFECT:flags is_serif/is_monospace/is_symbolic | font_family_class, font_flags |
| `taille` | Corps / taille | pt | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:sz (demi-points), CSS:font-size, VYSI:font_size, PERFECT:style.size_pt | font_size, font_size_pt, size_half_points |
| `graisse` | Graisse | 100..900 / gras | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:b, CSS:font-weight, VYSI:font_weight, PERFECT:style.bold | font_weight, bold |
| `style_police` | Style (normal, italique, oblique) | énumération | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:i, CSS:font-style, VYSI:font_style, PERFECT:style.italic | font_style, italic |
| `chasse` | Chasse (étroit, large) | énumération / % | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | CSS:font-stretch, VYSI:font_stretch | font_stretch, font_width |
| `axes_variation` | Axes de police variable | axe=valeur | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | CSS:font-variation-settings, VYSI:font_variation_axes | font_variation_axes |
| `couleur_texte` | Couleur du texte | sRGB / CMJN / gris | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:color, PDF:fill color, VYSI:text_color, PERFECT:style.color_rgb, fill_color | text_color, color, color_srgb |
| `couleur_contour_texte` | Couleur de contour du texte | couleur | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:stroke color, VYSI:stroke_color, PERFECT:style.stroke_color | stroke_color |
| `opacite_texte` | Opacité | 0..1 | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:ca/CA, VYSI:opacity, PERFECT:style.opacity | opacity |
| `soulignement` | Soulignement (type, couleur) | énumération | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:u, CSS:text-decoration, VYSI:underline, PERFECT:style.underline | underline |
| `barre` | Barré simple / double | énumération | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:strike/dstrike, VYSI:strikethrough, PERFECT:style.strikeout | strikethrough |
| `petites_capitales` | Petites capitales | booléen | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:smallCaps, VYSI:small_caps, PERFECT:style.small_caps | small_caps |
| `capitales` | Tout en capitales | booléen | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:caps, VYSI:all_caps | all_caps |
| `exposant_indice` | Exposant / indice | énumération | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:vertAlign, VYSI:superscript, subscript, PERFECT:style.superscript | superscript, subscript, vertical_align |
| `espacement_lettres` | Espacement des lettres | pt | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:spacing, PDF:Tc, VYSI:letter_spacing, PERFECT:style.letter_spacing | letter_spacing |
| `espacement_mots` | Espacement des mots | pt | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:Tw, CSS:word-spacing, VYSI:word_spacing, PERFECT:style.word_spacing | word_spacing |
| `decalage_vertical` | Décalage vertical (rise) | pt | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:Ts, OOXML-W:position, VYSI:text_rise | text_rise |
| `echelle_horizontale` | Échelle horizontale | % | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:Tz, OOXML-W:w, PERFECT:style.horizontal_scale | — |
| `crenage` | Crénage | booléen / seuil pt | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:kern, CSS:font-kerning | — |
| `ligatures` | Ligatures et fonctions OpenType | liste | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | CSS:font-feature-settings, OOXML-W:w14:ligatures | — |
| `mode_rendu` | Mode de rendu (plein, contour, invisible…) | 0..7 | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PDF:Tr, PERFECT:style.text_rendering_mode | — |
| `surlignage_couleur` | Surlignage / trame de caractère | couleur | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:highlight/shd | — |
| `effets_texte` | Effets (ombre, relief, gravure, contour, lueur) | liste | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:shadow/emboss/imprint/outline, OOXML-D:effectLst | — |
| `cache` | Texte masqué | booléen | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:vanish | — |
| `marque_emphase` | Marque d'emphase (CJK) | énumération | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:em, CSS:text-emphasis | — |
| `mode_ecriture` | Mode d'écriture | horizontal | vertical | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | CSS:writing-mode, VYSI:writing_mode, PERFECT:style.writing_mode, line.wmode | writing_mode |
| `langue` | Langue | BCP 47 | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:lang, PDF:Lang, VYSI:language, PERFECT:language | language, dominant_language_tag |
| `ecriture` | Système d'écriture | ISO 15924 | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | VYSI:script, PERFECT:script | script, scripts |
| `direction` | Direction | ltr | rtl | ttb | btt | mixed | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:rtl/bidi, CSS:direction, VYSI:direction, PERFECT:direction, line.dir | direction |
| `style_nomme` | Style nommé appliqué | référence | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | OOXML-W:rStyle/pStyle, VYSI:style_refs | style_refs, style |
| `profil_casse` | Profil de casse (type, casse à préserver, acronymes, lettres, mots, ratio de majuscules) | all_caps | lower | title_case | sentence_case | mixed | numeric | symbolic | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PERFECT:case_profile | — |
| `cle_police_normalisee` | Clé de police normalisée | chaîne | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PERFECT:font_key_normalized | — |
| `drapeaux_police` | Drapeaux bruts de police (serif, chasse fixe, gras, italique, symbolique, exposant) | entier + booléens | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PERFECT:flags, PDF:FontDescriptor Flags | font_flags |
| `categorie_unicode` | Catégorie Unicode, espace, symbole mathématique | catégorie + booléens | granularite | PERFECT:chars unicode_category, is_whitespace, is_math_symbol | — |
| `comptages_texte` | Nombre de caractères, mots, lignes, blocs | entiers | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PERFECT:char_count, word_count, line_count, block_count | — |
| `resume_style` | Résumé des styles du bloc | style dominant + liste | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PERFECT:style_summary | — |

### paragraphe

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `alignement` | Alignement horizontal | gauche | centre | droite | justifie | distribue | texte, liste, tableau, region | OOXML-W:jc, CSS:text-align, VYSI:alignment, PERFECT:layout.alignment (left|center|right|floating) | alignment, align |
| `alignement_vertical` | Alignement vertical | haut | centre | bas | justifie | texte, tableau, region | OOXML-W:vAlign/textAlignment, VYSI:vertical_alignment | vertical_alignment |
| `retrait_gauche` | Retrait gauche | pt | texte, liste | OOXML-W:ind left, CSS:padding-left, VYSI:left_indent, PERFECT:layout.indent_left | left_indent |
| `retrait_droit` | Retrait droit | pt | texte, liste | OOXML-W:ind right, VYSI:right_indent, PERFECT:layout.indent_right | right_indent |
| `retrait_premiere_ligne` | Retrait de première ligne | pt | texte, liste | OOXML-W:ind firstLine, CSS:text-indent, VYSI:first_line_indent | first_line_indent |
| `retrait_suspendu` | Retrait suspendu | pt | texte, liste | OOXML-W:ind hanging, VYSI:hanging_indent | hanging_indent |
| `espace_avant` | Espace avant | pt | texte, liste, tableau | OOXML-W:spacing before, VYSI:space_before, PERFECT:layout.space_before | space_before |
| `espace_apres` | Espace après | pt | texte, liste, tableau | OOXML-W:spacing after, VYSI:space_after, PERFECT:layout.space_after | space_after |
| `interligne` | Interligne + mode | pt ou multiple ; auto | exact | au_moins | multiple | texte, liste, tableau | OOXML-W:spacing line/lineRule, CSS:line-height, VYSI:line_height, line_height_mode, PERFECT:line_height | line_height, line_height_mode |
| `taquets` | Taquets de tabulation (position, type, points de conduite) | liste pt | texte, liste | OOXML-W:tabs, VYSI:tab_stops | tab_stops, tabs |
| `cesure` | Césure | booléen | texte, liste | OOXML-W:suppressAutoHyphens, CSS:hyphens, VYSI:hyphenation | hyphenation |
| `lier_au_suivant` | Paragraphe solidaire du suivant | booléen | texte, liste | OOXML-W:keepNext, VYSI:keep_with_next, PERFECT:layout.keep_with_next | keep_with_next |
| `lignes_solidaires` | Lignes solidaires | booléen | texte, liste | OOXML-W:keepLines, VYSI:keep_lines_together | keep_lines_together |
| `veuves_orphelines` | Contrôle des veuves et orphelines | booléen | texte, liste | OOXML-W:widowControl, VYSI:widow_orphan_control | widow_orphan_control |
| `saut_page_avant` | Saut de page avant | booléen | texte | OOXML-W:pageBreakBefore | page_break_before |
| `espacement_contextuel` | Espacement contextuel (supprimé entre styles identiques) | booléen | texte, liste | OOXML-W:contextualSpacing | — |
| `bordure_paragraphe` | Bordures de paragraphe | côtés + style + épaisseur pt + couleur | texte, liste | OOXML-W:pBdr | — |
| `trame_paragraphe` | Trame / fond de paragraphe | couleur / motif | texte, liste | OOXML-W:shd | — |
| `grille_lignes` | Alignement sur la grille | booléen | texte | OOXML-W:snapToGrid, OOXML-W:docGrid | — |
| `parametres_lettrine` | Lettrine (lignes occupées, distance) | entier + pt | texte | OOXML-W:framePr dropCap/lines/hSpace | — |
| `niveau_plan` | Niveau de plan | entier | texte | OOXML-W:outlineLvl, PDF-TAG:H1-H6, PERFECT:semantic.heading_level | level |

### liste

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `type_liste` | Type de liste | puces | numerotee | liste | OOXML-W:numFmt, HTML:ul/ol, PERFECT:semantic.list_type | — |
| `format_numerotation` | Format de numérotation | decimal | lettre | romain | puce… | liste | OOXML-W:numFmt, CSS:list-style-type | — |
| `texte_marqueur` | Texte / gabarit du marqueur | chaîne | liste | OOXML-W:lvlText, PERFECT:semantic.list_marker | — |
| `police_marqueur` | Police et style du marqueur | référence | liste | OOXML-W:lvl rPr | — |
| `valeur_depart` | Valeur de départ | entier | liste | OOXML-W:start, HTML:ol start | — |
| `niveau_liste` | Niveau d'imbrication | entier | liste | OOXML-W:ilvl, VYSI:list_level | list_level |
| `suffixe_marqueur` | Séparation marqueur / texte | tabulation | espace | rien | liste | OOXML-W:suff | — |
| `image_puce` | Puce image | référence | liste | OOXML-W:lvlPicBulletId, CSS:list-style-image | — |

### tableau

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `nb_lignes_colonnes` | Nombre de lignes et de colonnes | entiers | tableau | OOXML-W:tblGrid, HTML:table, PERFECT:tables rows, columns, header_rows | grid_columns |
| `largeurs_colonnes` | Largeurs de colonnes | pt | tableau | OOXML-W:gridCol | cell_width |
| `hauteur_ligne` | Hauteur de ligne + règle | pt ; exact | au_moins | auto | tableau | OOXML-W:trHeight | row_height |
| `fusion_horizontale` | Fusion horizontale | nombre de colonnes | tableau | OOXML-W:gridSpan, PDF-TAG:ColSpan, HTML:colspan | cell_grid_span |
| `fusion_verticale` | Fusion verticale | nombre de lignes | tableau | OOXML-W:vMerge, PDF-TAG:RowSpan, HTML:rowspan | — |
| `portee_entete` | Portée d'en-tête | ligne | colonne | les deux | tableau | PDF-TAG:Scope, HTML:scope | — |
| `marges_cellule` | Marges internes de cellule | pt (4 côtés) | tableau | OOXML-W:tcMar, CSS:padding | — |
| `orientation_texte_cellule` | Orientation du texte de cellule | énumération | tableau | OOXML-W:textDirection | — |
| `ligne_entete_repetee` | Ligne d'en-tête répétée | booléen | tableau | OOXML-W:tblHeader | — |
| `ligne_insecable` | Ligne non sécable | booléen | tableau | OOXML-W:cantSplit | — |
| `alignement_tableau` | Alignement du tableau | énumération | tableau | OOXML-W:tblJc | table_alignment |
| `largeur_tableau` | Largeur du tableau | pt / % | tableau | OOXML-W:tblW | table_width |
| `disposition_tableau` | Disposition fixe / automatique | énumération | tableau | OOXML-W:tblLayout, CSS:table-layout | table_layout |
| `espacement_cellules` | Espacement entre cellules | pt | tableau | OOXML-W:tblCellSpacing, CSS:border-spacing | — |
| `style_tableau` | Style de tableau et bandes | référence + options | tableau | OOXML-W:tblStyle/tblLook | — |
| `index_cellule` | Index ligne / colonne de la cellule | entiers | tableau | VYSI:row_index, cell_index | row_index, cell_index, cell_ref |

### aspect

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `couleur_fond` | Couleur de fond | couleur | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | CSS:background-color, OOXML-D:solidFill, PDF:fill, PERFECT:fill_color | — |
| `motif_fond` | Motif / trame de fond | référence | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | OOXML-D:pattFill, PDF:Pattern | — |
| `degrade_fond` | Dégradé de fond | arrêts de couleur + angle | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | OOXML-D:gradFill, PDF:Shading, CSS:linear-gradient | — |
| `image_fond` | Image de fond | référence | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | OOXML-D:blipFill, CSS:background-image | — |
| `opacite` | Opacité de l'élément | 0..1 | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | PDF:ca/CA, SMask, CSS:opacity, OOXML-D:alpha, PERFECT:opacity | opacity |
| `bordure` | Bordure par côté (style, épaisseur, couleur, espacement) | pt + couleur | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | CSS:border, OOXML-W:tcBorders/pBdr, OOXML-D:ln, PERFECT:tables style border_color/width | visual_border_ref |
| `rayon_coins` | Rayon des coins | pt | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | CSS:border-radius, OOXML-D:roundRect | — |
| `ombre` | Ombre portée | décalage pt + flou + couleur | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | CSS:box-shadow, OOXML-D:outerShdw | — |
| `effets_3d` | Effets 3D, reflet, lueur | liste | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | OOXML-D:scene3d/sp3d/reflection/glow | — |
| `trait` | Trait (couleur, épaisseur, tirets, extrémités, jointures) | couleur + pt + motif | vectoriel, decoration, annotation | PDF:w/d/J/j, OOXML-D:ln prstDash/cap/join, CSS:stroke, PERFECT:stroke_color, stroke_width, line_cap, line_join, dashes | — |
| `regle_remplissage` | Règle de remplissage | nonzero | evenodd | vectoriel | PDF:f/f*, CSS:fill-rule, PERFECT:even_odd | — |
| `mode_fusion` | Mode de fusion | Normal | Multiply | Screen… | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | PDF:BM, CSS:mix-blend-mode | — |
| `espace_couleur` | Espace colorimétrique | DeviceRGB | DeviceCMYK | DeviceGray | ICC | Indexed | Separation | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | PDF:ColorSpace, PERFECT:colorspace | icc_profile_ref |

### image

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `dimensions_pixels` | Dimensions en pixels | px | image | PDF:Width/Height, VYSI:width_px, height_px, PERFECT:width_px, height_px | width_px, height_px |
| `resolution` | Résolution effective | dpi | image | VYSI:dpi, PERFECT:xres, yres | dpi |
| `profondeur_bits` | Profondeur de couleur | bits par composante | image | PDF:BitsPerComponent | — |
| `compression` | Format / compression | JPEG | JPX | Flate | JBIG2 | CCITT | PNG… | image | PDF:Filter, PERFECT:ext | — |
| `masque` | Masque (doux, pochoir, couleur) | référence | image | PDF:SMask/Mask/ImageMask, PERFECT:mask | — |
| `recadrage` | Recadrage (haut, bas, gauche, droite) | % | image | OOXML-D:srcRect, CSS:object-position | — |
| `ajustements_image` | Luminosité, contraste, recoloration | valeurs | image | OOXML-D:lum/duotone | — |
| `texte_alternatif` | Texte alternatif | chaîne | image, vectoriel, donnees_visuelles, formule | PDF-TAG:Alt, OOXML-D:docPr descr, HTML:alt | — |
| `orientation_exif` | Orientation EXIF | entier | image | VYSI:orientation | orientation |
| `interpolation` | Interpolation | booléen | image | PDF:Interpolate | — |
| `contient_texte` | Contient du texte lisible | booléen | image, donnees_visuelles | VYSI:AD05 ocr | contains_text |
| `alpha_image` | Canal alpha | booléen | image | PERFECT:images alpha | — |

### forme

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `geometrie_predefinie` | Géométrie prédéfinie | nom (rect, ellipse, flèche…) | vectoriel | OOXML-D:prstGeom | sp |
| `chemin` | Chemin (opérateurs de tracé) | liste | vectoriel, decoration | PDF:m/l/c/re/h, OOXML-D:custGeom, PERFECT:drawing items cmd/coords | — |
| `pointes_fleche` | Pointes de flèche (début, fin) | énumération | vectoriel | OOXML-D:headEnd/tailEnd, PDF:LE | — |
| `connexions` | Formes reliées (connecteur) | références | vectoriel | OOXML-D:stCxn/endCxn | — |
| `texte_interne` | Texte interne de la forme | référence | vectoriel | OOXML-D:txBody | — |
| `role_dessin` | Rôle d'un dessin | background_rect | rule_line | vertical_rule | shape | vectoriel, decoration | PERFECT:_classify_drawing | — |
| `type_dessin` | Type de tracé (remplissage, contour, les deux), chemin fermé | f | s | fs ; booléen | vectoriel, decoration | PERFECT:drawing type, close_path | — |

### donnees_visuelles

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `type_graphique` | Type de graphique | barres | courbes | secteurs | nuage… | donnees_visuelles | OOXML-D:c:barChart/lineChart/pieChart… | — |
| `series_donnees` | Séries et valeurs | tableau de données | donnees_visuelles | OOXML-D:c:ser | — |
| `axes` | Axes, titres, graduations | liste | donnees_visuelles | OOXML-D:c:catAx/valAx | axis_label_for |
| `legende_graphique` | Légende du graphique | référence | donnees_visuelles | OOXML-D:c:legend | legend_for |

### navigation

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `cible_lien` | Cible (URI, page, destination) | chaîne | navigation, annotation | PDF:A/Dest, OOXML-W:r:id/anchor | — |

### annotation

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `type_annotation` | Sous-type d'annotation | énumération PDF | annotation, navigation, formulaire | PDF:Subtype, PERFECT:annotation type | — |
| `contenu_annotation` | Contenu, auteur, date | chaînes | annotation | PDF:Contents/T/M, OOXML-W:author/date, PERFECT:content, title, subject | — |
| `drapeaux_annotation` | Drapeaux (masqué, imprimable, verrouillé) | bits | annotation, formulaire, navigation | PDF:F, PERFECT:flags | — |

### formulaire

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `nom_champ` | Nom du champ | chaîne | formulaire | PDF:T | — |
| `valeur_champ` | Valeur et valeur par défaut | selon type | formulaire | PDF:V/DV | — |
| `options_champ` | Options (choix, longueur max, requis, lecture seule) | liste | formulaire | PDF:Opt/MaxLen/Ff | — |

### page

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `taille_page` | Taille de page | largeur, hauteur pt | page | PDF:MediaBox, OOXML-W:pgSz, PERFECT:geometry.width/height | width_pt, height_pt |
| `orientation_page` | Orientation | portrait | paysage | page | OOXML-W:pgSz orient, PERFECT:geometry.orientation (portrait|landscape|square) | — |
| `rotation_page` | Rotation de page | 0 | 90 | 180 | 270 | page | PDF:Rotate, PERFECT:geometry.rotation | rotation |
| `boites_page` | Boîtes de page | MediaBox, CropBox, BleedBox, TrimBox, ArtBox | page | PDF:page boundaries, PERFECT:mediabox, cropbox, bleedbox, trimbox, artbox | box_refs |
| `marges_page` | Marges (haut, bas, gauche, droite, reliure) | pt | page | OOXML-W:pgMar, CSS:@page margin, PERFECT:margins left/right/top/bottom/inner/outer/binding | — |
| `distance_en_tete_pied` | Distance en-tête / pied de page | pt | page | OOXML-W:pgMar header/footer, PERFECT:margins header/footer | — |
| `colonnes_section` | Colonnes de section (nombre, espacement, séparateur) | entier + pt + booléen | page, region | OOXML-W:cols, CSS:column-gap/column-rule, PERFECT:columns count | detected_column_count |
| `numerotation_pages` | Numérotation des pages (format, départ) | énumération + entier | page | OOXML-W:pgNumType, PDF:PageLabels, PERFECT:page_number_logical, page_label | physical_number |
| `en_tetes_differents` | En-tête première page / pair-impair différents | booléens | page | OOXML-W:titlePg, evenAndOddHeaders, PERFECT:margins even_odd_variation, first_page_variation | — |
| `alignement_vertical_page` | Alignement vertical de la page | énumération | page | OOXML-W:vAlign | — |
| `grille_document` | Grille du document (CJK) | type + pas pt | page | OOXML-W:docGrid | — |
| `numero_physique_logique` | Numéro physique, numéro logique, libellé de page | entier / chaîne | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `format_probable` | Format probable | A4 | A5 | Letter | Legal | custom | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `zones_page` | Zones imprimable, visible, de contenu | bbox pt | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `rapport_aspect` | Rapport largeur / hauteur | nombre | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `dpi_page` | DPI cible et natif | dpi | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `marges_estimees` | Marges visibles et probables | pt | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `alignement_contenu_page` | Alignement du contenu dans la page | énumération | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `grille_page` | Grilles verticale, horizontale, de ligne de base ; pas de ligne dominant ; paragraphes alignés sur la grille | pt / booléen | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `arriere_plan_detail` | Arrière-plan : couleur, image, texture, papier numérisé, bruit, ombre, dégradé, filigrane, motif, bordure, fond vectoriel, fond raster, transparence, calques | valeurs | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `image_page_rendue` | Image rendue de la page (pour l'IA) | référence + dpi | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `colonnes_detail` | Colonnes : largeurs, gouttières, bornes, sens de lecture, symétrie, barre latérale, sauts, blocs à cheval | pt / liste | page | PERFECT:page.geometry/background/columns/grid/text | — |
| `source_texte_page` | Source du texte retenue | native_pdf | ocr | aucune | page | PERFECT:page.geometry/background/columns/grid/text | — |

### semantique

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `role_semantique` | Rôle sémantique | vocabulaire semantic_role FT01 | toutes | VYSI:semantic_role | semantic_role, role |
| `type_noeud_structure` | Type de nœud de structure | vocabulaire structure_node_kind FT01 | toutes | VYSI:structure_node_kind | node_kind |
| `type_cadre` | Type de cadre | vocabulaire frame_type FT01 | page, region, texte, liste, tableau, image, vectoriel, donnees_visuelles, formule, annotation, formulaire, media, decoration | VYSI:frame_type | frame_type |
| `nature_contenu` | Nature du contenu | vocabulaire content_nature FT01 | toutes | VYSI:content_nature, AD11 content_classes | content_classes |
| `domaine` | Domaine | vocabulaire domain FT01 | toutes | VYSI:domain | domain_labels |
| `eligibilite_traduction` | Éligibilité à la traduction | eligible | partial | ineligible | review | none | toutes | VYSI:translation_eligibility, PERFECT:translatable, non_translatable_reason | translation_eligibility, translatability |
| `politique_protection` | Politique de protection | translate | preserve_exact | preserve_structure | … | toutes | VYSI:protection_policy, handling_policy | handling_policy, unit_policy, protected |
| `segments_langue` | Segments de langue | liste [début, fin, langue, écriture, direction] | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | VYSI:AD11 language_segments, PERFECT:text.languages | language_segments |

### relations

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `parent` | Élément parent | référence | toutes | VYSI:parent_id, parent_unit_id | parent_id, parent_unit_id, parent_frame_id |
| `enfants` | Éléments enfants | références | toutes | VYSI:child_unit_ids | child_unit_ids, child_frame_ids |
| `suivant_precedent` | Suivant / précédent (lecture) | références | toutes | VYSI:AD09 next, cross_page_next | next, cross_page_next |
| `continuation` | Continuation (débordement, suite sur autre page) | référence | toutes | VYSI:continues, continuation_of | continues, continuation_of |
| `relations_semantiques` | Relations sémantiques | caption_of | note_for | label_for | references | legend_for | header_of | … | toutes | VYSI:AD10 semantic_relation, PERFECT:relationships caption_for_image, caption_for_table, text_context_for_special_region | caption_of, note_for, label_for, illustrates, callout_for, unit_for |
| `appartenance` | Appartenance (légende de, tableau, formule) | références | texte, en_ligne, granularite, liste, tableau, formule, expression_speciale | PERFECT:semantic caption_for, table_membership, formula_membership | — |

### document_source

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `source_chemin` | Chemin et nom du fichier source | chaînes | page | PERFECT:source | — |
| `source_extension_mime` | Extension, type MIME, format détecté | chaînes | page | PERFECT:source | — |
| `source_taille` | Taille du fichier | octets | page | PERFECT:source | — |
| `source_empreinte` | Empreinte du fichier | SHA-256 | page | PERFECT:source | — |
| `source_dates_fichier` | Dates de création / modification du fichier | ISO 8601 | page | PERFECT:source | — |

### document_pdf

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `pdf_nombre_pages` | Nombre de pages | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_version` | Version PDF | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_chiffrement` | Chiffré / mot de passe requis | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_permissions` | Permissions | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_flux_xref` | Flux de références croisées | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_calques` | Présence de calques | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_formulaire` | Présence d'un formulaire | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_annotations` | Présence d'annotations | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_pieces_jointes` | Présence de pièces jointes | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_structure_balisee` | Structure balisée (Tagged PDF) | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_accessibilite` | Accessibilité | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_ocr_preexistant` | OCR déjà présent | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_texte_invisible` | Texte invisible | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_texte_vectorise` | Texte vectorisé (converti en tracés) | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_pages_numerisees` | Pages numérisées | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_polices_incorporees` | Polices incorporées | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_polices_substituees` | Polices substituées | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_images_haute_resolution` | Images haute résolution | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_transparence` | Transparence | booléen / valeur | page | PERFECT:pdf | — |
| `pdf_vecteurs_complexes` | Vecteurs complexes | booléen / valeur | page | PERFECT:pdf | — |

### document_metadonnees

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `meta_titre` | Titre | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_auteur` | Auteur | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_sujet` | Sujet | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_mots_cles` | Mots-clés | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_langue_declaree` | Langue déclarée | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_langues_detectees` | Langues détectées | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_dates` | Dates de création / modification | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_producteur_createur` | Producteur, créateur, application source et version | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_identifiant` | Identifiant unique | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_droits` | Copyright | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_classification_statut` | Classification, statut | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_modele` | Modèle (template) | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_revisions` | Nombre de révisions, historique | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |
| `meta_commentaires_internes` | Commentaires internes | chaîne / date / liste | page | PERFECT:metadata, PDF:Info/XMP | — |

### document_ressources

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `ressources_polices` | Polices (xref, type, nom, clé normalisée, nom de ressource, encodage, incorporée, chemin, sous-ensemble, substitution) | liste | page | PERFECT:resources.fonts, _extract_page_fonts, PDF:Font | font |
| `ressources_autres` | Images, espaces couleur, XObjects, motifs | listes | page | PERFECT:resources, PDF:Resources | image, theme |
| `styles_globaux` | Styles globaux du document | liste | page | PERFECT:global_styles, OOXML-W:styles | style_definition |

### document_profil

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `profil_type_probable` | Type probable du document | valeur / booléens / score | page | PERFECT:document_profile | — |
| `profil_dominantes` | Orientation, style et nombre de colonnes dominants | valeur / booléens / score | page | PERFECT:document_profile | — |
| `profil_presences` | Présence de tableaux, figures, graphiques, formules, code, notes, références, pagination, en-têtes, pieds, filigrane, logo, tampon, signature, écriture manuscrite | valeur / booléens / score | page | PERFECT:document_profile | — |
| `profil_complexite` | Complexité visuelle et linguistique | valeur / booléens / score | page | PERFECT:document_profile | — |
| `profil_qualite` | Qualité du document et de l'OCR | valeur / booléens / score | page | PERFECT:document_profile | — |
| `profil_reconstructibilite` | Score de reconstructibilité | valeur / booléens / score | page | PERFECT:document_profile | — |

### reconstruction

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `contraintes_reconstruction` | Conserver bbox / taille / casse / couleur / styles ; autoriser recomposition, expansion horizontale / verticale, chevauchement ; rendu obligatoire | booléens | toutes | PERFECT:reconstruction_constraints | page_locked, font_size_locked, line_spacing_locked |
| `contraintes_page` | Taille de page identique, tout le texte rendu, obstacles fixes, repositionnement en cascade, formules et images figées | booléens + liste | page | PERFECT:page reconstruction_constraints | — |
| `preserver_visuel` | Doit préserver le visuel | booléen | image, vectoriel, region, formule | PERFECT:must_preserve_visual | — |

### qualite

| id | attribut | valeurs / unité | s'applique à | sources | vysi |
|---|---|---|---|---|---|
| `qualite_extraction` | Score de présence des champs, avertissements, score de reconstructibilité, OCR utilisé, texte natif disponible, blocs sans style | scores + liste | toutes | PERFECT:quality_report | — |

## 3. Propriétés des bboxes

### identite

| id | propriété | valeurs / unité | sources | vysi |
|---|---|---|---|---|
| `type_boite` | Type de la boîte | élément | ligne | mot | glyphe | zone | colonne | groupe | page | VYSI:AD07 hierarchy levels | level, unit_kind |
| `type_element` | Type de l'élément contenu (référentiel) | id d'élément | VYSI:semantic_role | semantic_role |
| `etiquette_detecteur` | Étiquette brute du détecteur et son score | étiquette + 0..1 | PADDLEX:label, VYSI:candidate_class | candidate_class |
| `origine_boite` | Origine de la boîte | native | detecteur | calculee | VYSI:geometry source/method | source, method |
| `source_detection` | Détecteur à l'origine de la boîte | chaîne | PERFECT:detection_source | — |

### geometrie

| id | propriété | valeurs / unité | sources | vysi |
|---|---|---|---|---|
| `coordonnees` | x, y, largeur, hauteur | pt | VYSI:bbox, PERFECT:bbox | bbox |
| `systeme_coordonnees` | Système de coordonnées (origine, axes, unité) | top_left | bottom_left ; pt | px | emu | VYSI:coordinate_space | coordinate_space_ref, origin, unit |
| `rotation_boite` | Rotation de la boîte | degrés | OOXML-D:xfrm rot | rotation |
| `forme_boite` | Forme exacte (quad, polygone) | points | VYSI:quad, polygon | quad, polygon |
| `approximation` | Géométrie approximative | booléen | VYSI:approximate | approximate |
| `bbox_pixels` | Boîte en pixels de l'image rendue | px | PERFECT:bbox_px | — |

### agencement_interne

| id | propriété | valeurs / unité | sources | vysi |
|---|---|---|---|---|
| `nb_lignes` | Nombre de lignes | entier | VYSI:line_bboxes, PERFECT:line_count | line_bboxes |
| `nb_colonnes_internes` | Colonnes internes | entier + gouttières pt | CSS:column-count | — |
| `sens_flux` | Sens du flux (écriture, empilement des lignes) | ltr | rtl | ttb | CSS:writing-mode, direction | direction, writing_mode |
| `alignement_lignes` | Alignement observé des lignes | gauche | centre | droite | justifie | CSS:text-align | align, source_align |
| `alignement_vertical_contenu` | Alignement vertical du contenu | haut | centre | bas | CSS:align-content, OOXML-D:bodyPr anchor | vertical_align |
| `interligne_mesure` | Interligne mesuré | pt + ratio | VYSI:line_height_ratio | line_height_ratio |
| `espacement_blocs_internes` | Espacement entre blocs internes | pt | CSS:margin | — |
| `marges_internes` | Marges internes (padding) | pt (4 côtés) | CSS:padding, OOXML-D:bodyPr lIns/tIns/rIns/bIns, VYSI:padding | padding |
| `retraits_observes` | Retraits observés (gauche, première ligne) | pt | OOXML-W:ind | — |
| `taquets_observes` | Alignements internes en colonnes (tabulations) | positions pt | OOXML-W:tabs | — |
| `grille_interne` | Grille interne (cellules) | lignes × colonnes | OOXML-W:tblGrid | — |
| `marqueurs_internes` | Puces / numéros internes | liste | OOXML-W:numPr | — |
| `densite_encre` | Densité / taux de remplissage | 0..1 | VYSI:AD06 visual primitives | — |
| `debordement` | Débordement du contenu | aucun | coupe | deborde | CSS:overflow, VYSI:overflow_policy | overflow_policy |
| `sous_regions_a_preserver` | Sous-régions à conserver telles quelles (visuel) | liste [bbox, politique, source, indice texte] | PERFECT:internal_discrimination.preserve_visual | — |
| `sous_regions_traduisibles` | Sous-régions de texte traduisible | liste bbox | PERFECT:internal_discrimination.translate_text | — |
| `jetons_proteges` | Jetons protégés | liste | PERFECT:internal_discrimination.protect_token | — |
| `fond_a_ignorer` | Fond à ignorer | liste bbox | PERFECT:internal_discrimination.ignore_background | — |

### style_interne

| id | propriété | valeurs / unité | sources | vysi |
|---|---|---|---|---|
| `segments_style` | Segments de style successifs (runs) | liste [début, fin, style] | OOXML-W:r, VYSI:style_runs | style_runs, style_run_refs |
| `style_dominant` | Style dominant | police, taille, couleur, graisse | VYSI:dominant_font_name/size, PERFECT:style_summary | dominant_font_name, dominant_font_size |
| `signature_style` | Signature de style | empreinte | VYSI:style_signature | style_signature |
| `homogeneite_style` | Homogénéité (nombre de styles distincts) | entier | VYSI:style_runs | — |
| `couleurs_presentes` | Couleurs présentes | liste | PDF:fill/stroke colors | — |

### disposition

| id | propriété | valeurs / unité | sources | vysi |
|---|---|---|---|---|
| `ordre_lecture_boite` | Ordre de lecture | index | VYSI:AD09, PERFECT:reading_order | reading_order_index |
| `ordre_empilement_boite` | Ordre d'empilement | entier | CSS:z-index, VYSI:z_order, PERFECT:render_order z_index | z_order |
| `conteneur` | Conteneur parent et enfants | références | VYSI:FT03 parent_frame_id | parent_frame_id, child_frame_ids |
| `voisins` | Voisins (gauche, droite, dessus, dessous) et distances | références + pt | VYSI:AD09 edges | — |
| `alignements_voisins` | Bords alignés avec d'autres boîtes | références | VYSI:AD06 alignment_axis | alignment_axis |
| `chevauchements` | Chevauchements | références + aire | VYSI:collision_status | collision_status |
| `couloir_boite` | Couloir / zone de page | header | body | footnote | footer | marginalia | VYSI:lane | lane, participation |
| `ancrage_boite` | Ancrage et habillage | en_ligne | flottant ; habillage | OOXML-D:wp:anchor | — |
| `contraintes` | Contraintes (contenance, débordement, redimensionnement, déplacement) | politiques FT03 | VYSI:FT03 constraints | containment_policy, overflow_policy, resize_policy, movement_policy |
| `budget_mise_en_page` | Budget de mise en page (caractères max, boîte de rendu) | entiers + boîte | VYSI:layout_budget | layout_budget |
| `politique_rendu` | Politique de rendu | preserve_source_region | reflow | … | PERFECT:render_policy | reconstruction_policy |

### presentation

| id | propriété | valeurs / unité | sources | vysi |
|---|---|---|---|---|
| `fond_boite` | Fond (couleur, motif, dégradé, image) | couleur / référence | CSS:background | — |
| `bordure_boite` | Bordure | côtés + style + pt + couleur | CSS:border | visual_border_ref |
| `ombre_boite` | Ombre | valeurs | CSS:box-shadow | — |
| `coins_boite` | Coins arrondis | pt | CSS:border-radius | — |
| `opacite_boite` | Opacité | 0..1 | CSS:opacity | opacity |
| `visibilite_boite` | Visibilité, rognage, calque | énumération | VYSI:visibility, clip_ref, layer | visibility, clip_ref, layer |
| `rendu_obligatoire` | Doit être rendue | booléen | PERFECT:must_render | — |

### contenu

| id | propriété | valeurs / unité | sources | vysi |
|---|---|---|---|---|
| `nature_contenu_boite` | Nature du contenu | texte_natif | texte_image | image | vectoriel | mixte | vide | VYSI:content_nature | — |
| `texte_boite` | Texte et nombre de caractères | chaîne + entier | VYSI:text | text |
| `langue_boite` | Langue(s) | BCP 47 | VYSI:language | dominant_language_tag |
| `traduisible_boite` | Traduisible | éligibilité FT01 | VYSI:translation_eligibility | translation_eligibility |
| `politique_traduction` | Politique de traduction | preserve_visual_region | translate | … | PERFECT:translation_policy | translation_policy |
| `exclure_flux_traduction` | Exclue du flux de traduction | booléen | PERFECT:must_exclude_from_translation_flow | — |
