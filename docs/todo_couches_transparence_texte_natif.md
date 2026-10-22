# Couches, transparence et texte natif

## Perimetre et contrat

- Source : `/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/e03fb6c45305fb13_000588.pdf`, page 1 (648 x 776 pt).
- Temoin initial : `results/e03fb6c45305fb13_000588_bbox_native_orchestrated.docx`.
- Travail polices : `pdfexact/fontlib.py`, `pdfexact/extract/fonts.py`, tests nouveaux et ce suivi. Aucun changement de placement du texte.
- Gibbs : extraction et rendu des images, vecteurs, transparence et ordre de peinture. Aucun correctif de ces modules dans le travail polices.
- Extensions explicitement approuvees apres diagnostic : `_angle_direction` dans `extract/text.py`, puis propagation de `Document.polices` dans le squelette `write_bbox_only_docx`. Aucun changement du format de page, des boites source ou des polices choisies ; `drawing.py` ne necessite pas de correction de signe.
- Acceptation : trois petites photos visibles, aucun cache blanc accidentel, texte courant toujours natif et editable, comparaison du vrai export LibreOffice avec le PDF source. Aucun quota de paragraphes ni affirmation d'identite pixel.

## Diagnostic initial, avant correction

- [x] Inspecter les parties XML et les medias du DOCX initial : 175 `w:r`, 147 `w:t`, 21 `wp:anchor`, cinq `pic:pic` et cinq JPEG. Une ancre n'est pas une preuve de rasterisation.
- [x] Confirmer cinq paragraphes natifs longs pour le corps de l'article (793, 781, 809, 566 et 470 caracteres), plus du texte dans `w:txbxContent/w:p/w:r/w:t`. Le compte brut des paragraphes imbriques inclut des alternatives OOXML et ne constitue pas un compte semantique.
- [x] Identifier les polices declarees dans les runs : 92 declarations `cmr10`, 20 `Nimbus Sans`. Aucune partie `word/fontTable.xml` dans ce temoin. L'absence de cette partie ne prouve pas un fallback pour une police installee.
- [x] Inspecter les six polices PDF : Helvetica, Helvetica-Bold et quatre noms opaques `TT...`, toutes avec des octets CFF embarques. Les quatre CFF opaques ne donnent ni famille lisible ni graisse ; leurs noms ne permettent pas une identification exacte.
- [x] Reproduire le choix suspect : les familles inconnues sont classees implicitement sans empattement ; `cmr10` est ainsi choisi comme substitut dynamique avec confiance 0,86. Ce n'est pas une comparaison des metriques avec la police source.
- [x] Signaler a Gibbs le point d'integration : `write_bbox_only_docx` cree le document initial sans `polices`, alors que le writer sait construire une table et embarquer les fichiers resolus. Le remplissage ulterieur n'ajoute pas cette table.
- [x] Distinguer l'ordre de peinture, confirme par Gibbs, du contenu : le grand blanc source est peint sous le vert mais place au-dessus dans le DOCX ; les trois petites photos sont presentes, mais sous l'image principale et/ou leurs fonds blancs.
- [x] Identifier le diagnostic incorrect `embedded_in_pdf=false` du catalogue : le collecteur ne conservait pas les octets source, meme lorsque le PDF les embarquait.

## Corrections generales et tests

- [x] Ajouter et executer les tests rouges isoles : une famille inconnue n'est pas une sans reconnue ; un candidat opaque ne doit pas evincer une sans connue ; la substitution d'une source opaque reste explicitement incertaine. Premier passage : 7 echecs, 3 temoins verts.
- [x] Conserver les correspondances exactes, alias et styles explicites ; ne pas inventer la famille ou la graisse des noms opaques. Le score de choix reste distinct de la confiance exposee, plafonnee a 0,60 pour une source non classifiable.
- [x] Conserver l'information d'embarquement source independamment du fichier substitut utilise pour les metriques Word ; tester aussi une police non embarquee et une lecture impossible (un seul diagnostic par police, meme sur plusieurs pages).
- [x] Verifier le style compose : le premier controle reel selectionnait `URW Gothic Book Oblique` comme regulier, car seuls les styles contenant `italic` etaient reconnus. Tests rouges supplementaires : 2 echecs, 1 temoin vert. Les styles contenant `oblique` sont maintenant reconnus sans changer les placements.
- [x] Executer les tests cibles existants et nouveaux, puis `git diff --check` : premier passage vert 169 passes, 1 ignore ; passage final polices 173 passes, 1 ignore, incluant les 14 nouveaux cas de `tests/test_fontlib_native_fallback.py`.
- [x] Verifier le PDF reel : source, substituts effectivement choisis, modes/confiances et metriques des fichiers resolus. Helvetica et Helvetica-Bold : Nimbus Sans regular/bold, alias 0,92. Les quatre noms opaques : Trebuchet MS Regular (`trebuc.ttf`), dynamique 0,60. La famille et la graisse originales opaques ne sont pas affirmees.
- [x] Enregistrer le diagnostic initial source/XML/polices et les hashes : `results/verification_couches_texte_natif/diagnostic_polices_initial.json`. Six CFF source de 5848, 5341, 6378, 7753, 5894 et 4099 octets ; tous reellement embarques. Les metriques Word restent celles du fichier resolu, distinct des octets CFF source.
- [x] Rendre les references source a 144 dpi : `source_page1.png`, `source_photos.png`, `source_article.png` dans ce meme dossier. La source montre bien trois petites photos, un titre visuellement gras et sans empattement, et des intertitres gras italiques ; leur style exact ne peut pas etre deduit des quatre seuls noms opaques.

### Sens dirige du texte et table des polices

- [x] Prouver source -> IR -> OOXML -> vrai export LO, avec crops et traces : APRIL et AMBER ont `line.dir=(0,+1)` dans la source mais `(0,-1)` dans le premier LO ; Peggy a `(0,-1)` dans les deux et ne doit pas etre inverse. Preuve initiale conservee dans `diagnostic_directions_rotations.json`.
- [x] Identifier la perte dans `_angle_direction` : inversion Y avant la rotation canonique de page, puis repli modulo 180 qui supprime le sens. Garder la direction complete : rotation du vecteur source d'abord, conversion Y ensuite, sans repli modulo 180. Le renderer convertissait deja correctement le signe recu.
- [x] Ajouter 35 tests generiques : droite/gauche/haut/bas, +/-30 et +/-135, quatre rotations de page, conversion Word, styles et boites source inchanges. Passage rouge : 18 echecs et 17 temoins verts ; passage cible vert : 109 passes. Le cas texte natif montant + page 90 donne bien l'horizontale 0, pas 180.
- [x] Regenerer et exporter LO apres correction des angles : les trois directions LO sont maintenant strictement celles de la source ; APRIL/AMBER corriges, Peggy preserve. `final_directed_rotations.json`, crops source/LO et page complete a 144 dpi. Suite a ce stade : 785 passes, 1 ignore, 6 warnings, 100,87 s, avant correction du squelette polices.
- [x] Corriger le point d'integration du squelette approuve ensuite : transmettre une copie de `Document.polices` au writer existant. Celui-ci utilise les fichiers locaux resolus via `asset.chemin`, jamais les octets CFF source `asset.donnees`.
- [x] Ajouter sept tests de packaging : table et relations presentes, sfnt resolu recupere byte-identique apres desobfuscation, bits de droits OS/2 inchanges (0, 4, 8, sans sous-ensemble), aliases de famille/style dedupliques, CFF non resolu non embarque comme sfnt, parties conservees apres ajout du texte natif. Rouge : 6 echecs et 1 temoin vert ; cible : 147 passes, 1 ignore.
- [x] Refaire generations, LO, preuve d'edition et suite finale avec la table des polices effectivement presente dans le livrable : deux familles, trois fichiers (`Nimbus Sans` regular/bold, `Trebuchet MS` regular), relations valides, octets desobfusques exactement ceux des fichiers resolus. Droits OS/2 conserves : Nimbus 4 (Preview/Print), Trebuchet 8 (Editable). Rapport : `final_embedded_fonts.json`. Aucune affirmation d'identite de la police CFF source.

### Commandes et resultat intermediaire global

Tests cibles :

```sh
.converter/bin/python -m pytest -q tests/test_fontlib_native_fallback.py tests/test_fontlib.py tests/render/test_fonts_embed.py tests/render/test_package.py tests/extract/test_elements.py --tb=short
git diff --check
```

Suite non visuelle sur l'etat intermediaire des couches :

```sh
.converter/bin/python -m pytest -q --ignore=tests/capture_ecran --ignore=tests/visual --tb=short
```

Resultat : **686 passes, 1 ignore, 2 echecs**, 7 warnings, 72,73 s. Les deux echecs sont `tests/render/test_source_paint_layers.py::test_native_contract_copies_line_and_span_paint_provenance` et `::test_compat_writer_preserves_genuine_late_page_sized_white_cover`, dans le perimetre couches en cours de Gibbs. Transmis au parent ; aucun test ecarte, aucun changement de ces modules. Ce resultat n'est pas une validation globale finale.

## Regeneration et validation reelle

- [x] Executer un temoin intermediaire independant des corrections de couches : copie XML structuree du DOCX initial dans `/tmp/converter-native-editability-initial`, remplacement de `invasive species` par `EDITABLE WITNESS` dans un run natif, vrai export LibreOffice termine avec code 0. Une page PDF ; phrase extraite en page 1, rectangle environ (330,05 ; 531,00 ; 418,73 ; 540,00) pt. Cinq medias avec SHA-256 strictement identiques, original byte-identique. Rapport : `results/verification_couches_texte_natif/editability_initial.json`.
- [x] Inspecter la capture de ce temoin : le grand cache blanc du livrable initial masque encore la zone modifiee. Cette preuve etablit l'edition native et sa restitution dans le texte PDF, pas la visibilite finale. Aucun changement des couches sur la copie ; repetition sur le livrable final toujours requise.
- [x] Regenerer toute la pipeline CPU sous le suffixe distinct `_couches_corrigees` ; conserver le temoin initial. Sorties : `results/e03fb6c45305fb13_000588_bboxes_couches_corrigees.pdf` et `results/e03fb6c45305fb13_000588_native_couches_corrigees.docx`. Layout obligatoire PaddleX PP-DocLayout_plus-L CPU, 16 zones, 44 objets : 24 textes, 7 images/raster locaux, 13 formes.
- [x] Conserver l'integration intermediaire avant regeneration : `results/verification_couches_texte_natif/intermediate_20261010T182840Z`. Premier lancement sandbox SIGSEGV natif, sans cause attribuee avec certitude ; meme commande hors sandbox terminee code 0. Journaux conserves.
- [x] Exporter le DOCX corrige avec LibreOffice dans un profil distinct et rendre les previews a 144 dpi : `docx_page1.png`, `docx_photos.png`, `docx_article.png`, `docx_header.png`, `docx_right_edge.png`, dans `results/verification_couches_texte_natif` ; references source correspondantes disponibles.
- [x] Comparer page complete et crops source/export : trois petites photos visibles, article natif visible, aucun cache blanc accidentel. Le fond blanc de FINDINGS et les traits gris a droite sont authentiques dans la source et restent preserves ; suspicion initiale du parent corrigee apres comparaison de la vraie source, sans patch indu.
- [x] Recompter le XML actuel : 53 `w:p`, 251 `w:r`, 200 `w:t`, 44 `wp:anchor`, 7 `pic:pic`, comptes bruts incluant alternatives. Les cinq paragraphes longs (781, 793, 566, 809, 470 caracteres dans l'ordre de peinture actuel) sont dans `w:txbxContent/w:p/w:r/w:t`, sans `pic:pic` descendant ; tous ont un conteneur `a:noFill`, sans `a:solidFill`. Leurs textes sont exactement ceux du temoin initial, ordre de peinture mis a part.
- [x] Prouver l'editabilite sur `/tmp/converter-native-editability-final` : phrase `EDITABLE WITNESS` modifiee par XML structure, visible dans le vrai export LO et extraite en page 1 ; sept medias SHA-256 identiques, livrable byte-identique avant/apres. Rapport et emplacement du crop dans `validation_couches_texte_natif.json`.
- [x] Regenerer et exporter LO les trois temoins sous suffixe distinct : Tideman 54 paragraphes 11/18/25, 96 lignes, 142 runs ; Katrina 4/6/6 ; NASA 4/6/6 au lieu de 3/6/6, les deux lignes de titre maintenant separees. Aucun quota impose. Geometries de pages, contrats des spans source (texte, police source, style, corps, couleur, bbox) et caracteres natifs par page inchanges ; fichiers historiques byte-identiques. LO : Tideman trois pages 612 x 792 pt, Katrina une page 612 x 792 pt, NASA une page paysage 792 x 612 pt.
- [x] Executer la suite complete apres le premier checkpoint stable couches : 726 passes, 1 ignore, 6 warnings, 75,21 s ; `git diff --check` propre. Ce bilan precede le dernier correctif de composition de groupe ci-dessous, et n'est donc pas encore le bilan de cloture.
- [x] Recevoir le checkpoint stable du correctif groupe non textuel a opacite globale appliquee apres composition ; pas simplement appliquer l'alpha a chaque enfant. Derniere revue independante annoncee : 90 passes ; aucun fichier couche encore en modification.
- [x] Repeter les quatre generations CPU et les vrais exports LO sur le dernier code stable, incluant les angles et la table des polices : **792 passes, 1 ignore, 6 warnings, 99,78 s** ; `git diff --check` propre. Les 63 fichiers de production empreintes sont inchanges entre debut et fin ; originaux et sources byte-identiques. Rapport final : `results/verification_couches_texte_natif/validation_couches_texte_natif.json`. Passages anterieurs archives, dont le passage 785/1 avant ajout de la table.
- [x] Revalider le livrable final : cinq longs paragraphes d'article toujours dans `w:txbxContent/w:p/w:r/w:t`, conteneurs transparents, aucun `pic:pic` descendant ; tous les caracteres natifs non blancs preserves. XML brut : 53 paragraphes, 251 runs, 200 noeuds texte, 44 ancres, 7 images, alternatives comprises. Les trois directions verticales LO concordent avec la source, sans changer de format de page.
- [x] Repeter la preuve d'edition finale dans `/tmp/converter-native-editability-fonttable-final` : phrase modifiee visible et extraite dans LO, sept medias et toutes les parties de polices byte-identiques, livrable non modifie. Aucun remplacement raster du corps de texte.
- [x] Revalider les trois temoins finaux : Tideman 54 paragraphes (11/18/25), 96 lignes, 142 runs ; Katrina 4/6/6 ; NASA 4/6/6, avec historique 3/6/6 conserve et sans quota. Contrats texte/style/positions des 142/6/6 spans source et proprietaires de pages natifs inchanges. LO : trois pages portrait, une page portrait, une page paysage respectivement ; Budget quatre records autonomes et Partners cinq lignes lisibles, sans chevauchement incoherent visible.
- [x] Actualiser les previews source/LO a 144 dpi, la preuve de directions et les hashes/mtimes des artefacts. Toutes les sessions de cette tache sont terminees ; aucune nouvelle modification de production apres le snapshot final.

## Couches et revue generale

- [x] Verifier sur le cas reel l'ordre de peinture source : grand fond blanc sous le vert, trois photos au-dessus de l'image principale et de leurs sous-couches, texte natif transparent au bon niveau. Aucune suppression arbitraire de blancs authentiques.
- [x] Consigner les trois premiers P1 corriges par Gibbs et ses tests/repros independants : origines de glyphes dupliquees sans ecrasement de style/sequence, opacite de Form transportee, clips vectoriels respectes. Premier checkpoint commun annonce : 465 tests cibles passes, 1 ignore, dont 57 nouveaux.
- [x] Clore la revue de composition : pour un Form contenant plusieurs enfants qui se chevauchent, une opacite de 50 % s'applique au groupe compose, et non individuellement aux enfants. Checkpoint Gibbs : 487 passes cibles, 1 ignore ; 22/22 tests de groupes. Trois repros de chevauchement donnent RGBA (0, 0, 255, 126). Les changements de hashes observes lors du passage precedent restent archives.
- [x] Consigner le perimetre : occurrences de groupes/clips distinctes, groupes isoles graphiques `Normal` composes en un seul raster local avant alpha global, enfants vectoriels deja composes non repeints, groupes differents non fusionnes. Texte natif conserve ; groupes texte/shading/imagemask/non isoles/non `Normal` non certifies et signales par `RuntimeWarning`.

## Limites a conserver

- Les familles exactes des CFF opaques ne sont pas identifiees. Une substitution dynamique n'est ni une reconnaissance exacte ni une equivalence metrique prouvee.
- `recognized=true` dans le catalogue signifie qu'un fichier de police exploitable a ete resolu, pas que la famille source opaque a ete identifiee ; lire avec `resolution_mode` et `resolution_confidence`.
- La table et les trois fichiers de polices sont verifies dans le livrable final, avec relations et octets resolus preserves. Les droits propres aux fichiers restent inchanges ; une declaration `w:rFonts` ou un fichier embarque ne prouve pas a elle seule l'identite avec la police CFF source ni le comportement de toutes les versions de Word.
- Avant le dernier correctif du squelette, le DOCX n'avait pas de `fontTable.xml` ni de polices embarquees, bien que LO resolvait TrebuchetMS et NimbusSans-Regular/Bold. Cette absence connue est corrigee, pas acceptee comme limitation permanente. Cela ne recupere pas les familles CFF opaques. Le gras du titre et les gras/italiques d'intertitres source ne sont pas restitues exactement ; reflow et espaces varient.
- Sur la cible, les 72 textes de lignes et styles de caracteres source sont conserves, mais le decoupage passe de 109 a 162 runs et 55 boites de ligne estimees changent avec les metriques du substitut. Ne pas affirmer une geometrie de ligne byte-identique. Section DOCX 648 x 776 pt ; PDF LO environ 649,162 x 776,013 pt.
- Les modes de melange non `Normal` et la composition de groupes contenant du texte natif ont des contraintes non certifiees exhaustivement. Ces preuves sur quatre PDF et les tests synthetiques ne constituent pas une certification de tous les PDF.
- Aucun endpoint de comprehension semantique ni modele semantique CPU local n'est configure ; repli geometrique annonce, distinct du layout IA CPU effectivement execute.
- Les avertissements de timestamps fontTools ne sont pas un diagnostic de cette divergence et ne justifient pas de modification hors perimetre.
- La fidelite pixel, les metriques et le comportement de Word restent distincts de l'editabilite native et de la validation visuelle LibreOffice.
