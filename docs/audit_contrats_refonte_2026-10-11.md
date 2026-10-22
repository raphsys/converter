# Audit des contrats de refonte, 2026-10-11

## Perimetre et verdict

Reference exclusive : [plan_refonte_modules_universels_reconstruction.md](plan_refonte_modules_universels_reconstruction.md), sections 1-4, 8, phases 0-3 et invariants associes. Le code du worktree est l'autorite observee, pas la declaration de completion du suivi.

Audit borne de `scene.py`, `ir.py`, `analysis/{options,decisions,provenance,geometry,semantic}.py`, `geometry.py` et des raccordements extraction -> scene -> plan -> validation avant ecriture. Lecture ponctuelle de `render_plan.py`, `reflow.py`, `native_contract.py`, `package.py`, CLI et extracteurs pour etablir les consommateurs. Pas d'audit detaille des backends de phase 4, pas de baseline non visuelle complete, pas de modification de `docs/suivi_refonte_modules_universels.md`.

AGENTS recherche avant inspection : aucun `AGENTS.md` dans le depot, ses parents jusqu'a `/`, ni dans ses sous-repertoires ; `.agents` et `.codex` locaux sont vides. Worktree deja sale preserve. Seule ecriture de ce worker : ce rapport. Sondes Python executees en memoire avec `.converter/bin/python -B`, sans fichier PDF/DOCX, sans pytest/cache et sans reseau.

**Verdict : les contrats existent en partie, mais les phases 0-3 ne sont pas etablies comme completes. Chaque element source actif ou ecarte n'a pas une identite source conservee et une decision de rendu ou de non-representabilite avant ecriture.** Les manques listes restent des exigences du plan ; aucune requalification en amelioration facultative ou en travail futur optionnel.

## Blocages prioritaires pour le prochain backend

1. **P1 / B1 - Le controle avant ecriture peut accepter une couverture source vide.** `RenderPlan.validate()` ne parcourt que les entrees presentes, sans comparer aux sources (`pdfexact/render/render_plan.py:62`). `valider_contrat_word_native()` fait la meme chose (`pdfexact/render/native_contract.py:118`). Pour un document avec texte, `RenderPlan({}, AnalysisOptions()).validate() == []` et le contrat est `conforme=True`. `build_render_plan()` et le plan final parcourent les actifs/prepares, sans les `discarded_elements` ni le registre de `document.scene` (`render_plan.py:204`, `:292`). Une scene avec un actif et un ecarte conserve leurs `render_decision=None`, alors que son plan valide. `package.py:198` continue jusqu'a l'ecriture ZIP ; meme les erreurs du contrat deviennent des diagnostics apres construction XML (`:201`). **Prerequis concret :** reconciliation de chaque ID source avec une sortie planifiee, une transformation tracee vers cette sortie, ou une non-representabilite motivee ; faire echouer la validation avant l'ouverture ZIP pour les sources non traitees. La verification de sortie reste distincte et releve de phase 5.

2. **P1 / B2 - Des sources disparaissent avant la scene, donc un backend complet ne peut pas les recuperer.** `_dedoublonner_textes_positionnes()` retire le perdant de `page.elements` sans l'ajouter aux ecartes (`pdfexact/extract/document.py:1504`), sur les deux chemins appeles a `:2145` et `:2241`. Le perdant a un `reason_code`, mais cet historique n'atteint jamais la scene. `_filtrer_textes_intersectant_zones()` reconstruit TextBox/Line, supprime des spans et perd ID, orientation, baseline, z-order (`:694`, `:727`). Son appel natif a `:301` ne journalise pas les originaux ; l'appel OCR a `:2214` garde l'ancien conteneur, mais pas une decision par span retire ni une relation explicite ancien/nouveau. `regrouper_listes()` retire le marqueur sans transferer ses `source_ids` (`pdfexact/analysis/semantic.py:502`, `:557`). Le plan final de deux sources `marker`, `body` contient seulement `body`, sources `('body',)`, et valide. **Prerequis concret :** IDs attribues avant filtrage, conservation des observations, liens de remplacement/fusion et decision motivee de chaque source ; un historique sur un objet devenu inaccessible ne suffit pas.

3. **P1 / B3 - Les adaptateurs alterent le contrat que le backend est cense respecter.** `scene_from_legacy_document()` fabrique des IDs/index de sortie (`pdfexact/scene.py:228`), classe tout TextBox/FlowParagraph en PDF natif (`:222`), ne lit pas les spans/points des lignes pour la geometrie et le style (`:240`, `:262`), ne transmet ni clipping/compositing ni chemins. `z_index=0` devient l'index courant (`:270`) et `alpha=0` devient `1.0` (`:276`). La sonde d'une forme transparente, premiere peinture mais troisieme objet, donne `opacity=1.0`, `z_order=2`, `path=()`. `_record_for_legacy()` recree encore les records, sans utiliser `document.scene`, et perd les historiques/preuves/clipping/alpha (`pdfexact/render/render_plan.py:174`), avec le meme probleme de zero (`:189`). **Prerequis concret :** une identite commune scene/plan et un transfert explicite de tous les attributs requis, y compris les valeurs nulles ; le plan ne doit pas recalculer un contrat different de la source.

4. **P1 / B4 - Les frontieres et options semantiques ne survivent pas a toute la preparation.** Avec confiance de continuite `0.8` et seuil explicite `0.9`, `preserver_frontieres_ambigues()` produit deux groupes, puis `prepare_page_elements()` les refusionne par colonne/frame (`pdfexact/render/reflow.py:217`). `preserve_line_boundaries='always'` laisse `regrouper_paragraphes()` fusionner et `decider_mode_universel()` choisir `native-flow`. `_option()` prefere toujours le champ dataclass aux valeurs de `extra` (`pdfexact/analysis/semantic.py:286`) : les overrides `2.4/0.18` de `document.py:1375` sont inoperants. **Prerequis concret :** transporter une frontiere/confidence explicite et la respecter dans chaque passe et decision, et une seule resolution effective des options. Les fonctions de regroupement presentes ne prouvent pas cet invariant.

## Matrice phases 0-3

Statuts : **present** = implementation trouvee ; **partiel** = comportement incomplet ou consommateurs limites ; **absent** = API/champ non trouve dans le perimetre ; **non etabli** = aucune preuve suffisante de completion. Les chemins ci-dessous sont relatifs a la racine du depot.

| Exigence exacte du plan | Presence et preuve | Consommation / conclusion |
| --- | --- | --- |
| Phase 0.1, aucune suppression immediate de fonction metier (`plan:260`) | Fonctions historiques encore presentes, notamment `document.py:1450`, `native_contract.py:697`, `docx_writer.py:2140`. | Pas de certification historique de toutes les suppressions ; ce controle de code actuel ne remplace pas la comparaison de baseline. Non etabli. |
| Phase 0.2, contrats et adaptateurs (`plan:261`) | Scene/adaptateur `scene.py:199`, options, decision, provenance et geometrie presents. | Branche d'observation raccordee a `document.py:2493`, mais deuxieme adaptation vers plan et pertes B3. IR/API incomplets, voir inventaire. Partiel. |
| Phase 0.3, snapshots des PDF deja valides (`plan:262`) | `ElementRecord.snapshot()`/`SceneDocument.snapshot()` (`scene.py:105`, `:161`), tests synthetiques `tests/analysis/test_universal_contracts.py:177`, `:208`. | Snapshot omet decisions, historique, preuves, doublons, quads, baselines, clips, chemin, langue/script et confiance detaillee. Aucun golden de scene d'un PDF deja valide etabli par ces tests. Partiel, corpus non certifie ici. |
| Phase 0.4, mesurer decisions actuelles sans changer rendu (`plan:263`) | Scene d'observation ajoutee apres acquisition (`document.py:2488`), diagnostic du nouveau plan. | Scene sans decisions historiques ; `plan.divergences` contient les erreurs de validation interne (`render_plan.py:74`), pas la comparaison ancien/nouveau. Mesure comparative non etablie. |
| Phase 1.1, modules geometry/provenance (`plan:267`) | Deux fichiers presents. | Geometrie bbox effectivement consommee ; provenance surtout journalisation locale. API manquante `registre_elements`, operations geometrie manquantes. Partiel. |
| Phase 1.2, helpers locaux -> wrappers (`plan:268`) | `document.py:96`, `layout/planner.py:189`, `layout/understanding.py:500`, `extract/layout_map.py:810` deleguent aux helpers communs. | Avancee reelle pour bboxes ; orientation/courbure restent dans `extract/orientation.py:42`, `:51`, avec seuils differents de `analysis/geometry.py:151`. Centralisation complete non etablie. |
| Phase 1.3, registre sur chaque page (`plan:269`) | `SceneDocument.registry` seulement (`scene.py:149`), alimente par `add_page()` apres filtres (`:152`). | Ni `Page.element_registry` ni `PageScene` avec registre de page ; pas d'inventaire brut avant filtrage. Construction `SceneDocument([page])` laisse le registre vide. Partiel. |
| Phase 1.4, interdire suppressions sans reason_code (`plan:270`) | `_journaliser_elements_rejetes()`/`_appliquer_filtre_page()` (`document.py:127`, `:137`) gardent certains objets et raisons. | B2 ; tables rejetees a `document.py:1733`, `:1741` jamais enregistrees ; formes hors-page/converties en raster a `:1761`, `:1767` sans enregistrement des composants. `expliquer_filtrage()` accepte meme une raison vide (`provenance.py:163`). Invariant non satisfait. |
| Phase 2.1, creer semantic (`plan:274`) | Toutes les 12 fonctions du plan section 8 existent ; alias accentue fourni (`semantic.py:707`). | Module utilise par extraction, reflow et adaptateurs historiques ; sans imports XML/Word. Present, comportement partiel. |
| Phase 2.2, deplacer regroupements des trois modules (`plan:275`) | Appels delegues, p.ex. `document.py:1383`, `native_contract.py:434`, `reflow.py:198`. | Restent `_groupe_bloc_detecte`, regroupements historiques dans `native_contract.py:461`, `:518`, et fabrique directe de FlowParagraph dans extraction `document.py:313`. Migration partielle ; audit detaille backend laisse au worker phase 4. |
| Phase 2.3, remplacer heuristiques de casse par modele script-aware (`plan:276`) | `_infer_script()` traite Latin/CJK/arabe/etc. (`semantic.py:148`), sonde Latin/arabe refuse bien la fusion. | `est_texte_de_corps()` repose sur regex latine (`:250`), cross-frame exige `islower()` (`:409`), phrase utilise `isupper()` (`:436`), gate capitales historique encore a `native_contract.py:407`. Pas de remplacement complet. |
| Phase 2.4, garder lignes si confiance insuffisante (`plan:277`) | `preserver_frontieres_ambigues()` (`semantic.py:636`), premiere passe de reflow l'appelle. | Frontiere effacee par passes suivantes ; option always ignoree (B4). Invariant non satisfait. |
| Phase 3.1, decisions (`plan:281`) | RenderDecision et cinq fonctions publiques de section 2.3 presents (`decisions.py:28`, `:85`, `:151`, `:155`, `:170`, `:183`). | Tous les champs listes existent. Validateurs trop permissifs et provenance/contexte source non reconciles (B1/B3). Partiel. |
| Phase 3.2, tous les backends consomment RenderDecision (`plan:282`) | Chemin `native_rewriter=True` construit un plan (`package.py:193`). | Chemin public par defaut `False` appelle `construire_document_xml_compat(document, relations)` sans plan (`package.py:206`), facade a `docx_writer.py:2210`. Exigence non satisfaite a cette frontiere ; cartographie fine reservee au worker phase 4. |
| Phase 3.3, desactiver decisions concurrentes progressivement (`plan:283`) | Plan central appele par nouveau chemin ; preparation extraite dans `reflow.py`. | Chemin compat actif, adaptateurs distincts pour scene et plan. Ne pas conclure a une source unique de decisions. Partiel. |
| Phase 3.4, diagnostic expliquant chaque element (`plan:284`) | Nouveau renderer expose `diagnostics.decisions` (`word_native_rewriter.py:151`, `:1290`) et raisons des decisions planifiees (`:1273`). | Seulement elements du plan, pas sources ecartees/perdues ; scene snapshot sans raisons ; rapport CLI expose principalement compteurs/listes de pertes (`cli.py:236`). Explication universelle de toutes sources non etablie. |

## Inventaire des contrats canoniques

| Contrat du plan | Existant | Manque ou defaut de consommation |
| --- | --- | --- |
| Section 2.1, enums | SourceKind/ElementKind complets ; VerificationState complet et etendu. | `RenderMode` vit dans `analysis/decisions.py:12`, pas dans `scene.py` comme demande ; `from pdfexact.scene import RenderMode` echoue. Exposer le contrat demande sans dupliquer l'enum. |
| ElementRecord, ID/page/kind/role/provenance | Champs declares (`scene.py:45`). | `source_ids=()` autorise par constructeur ; fabrique exigeant provenance a `:309` non utilisee par les adaptateurs. IDs attribues apres transformations, sources OCR classees natives, aucun source_pdf_id. B2/B3. |
| ElementRecord, bbox/quad/polygon/path/baseline/orientation | Champs bbox/quad/polygon/path/baseline/angle/orientation presents. | Pas de champ distinct de points d'orientation ; ceux des lignes ne remontent pas. Polygon/path/clip_ids ne sont jamais renseignes par l'adaptateur. `_legacy_text()` ignore cellules de table (`scene.py:192`). |
| ElementRecord, peinture/clipping/opacite/compositing | z_order/opacity/clip_ids presents. | Compositing absent ; clip_bbox/paint_group ne remontent pas ; zeros alteres B3 ; ordre stable sur IDs/index de sortie ne prouve pas ordre de peinture source. |
| ElementRecord, texte/spans/langue/script/style/metriques | text/language/script/style declares. | Spans et metriques de police absents du contrat type ; `raw` n'est pas un transfert canonique. Style du TextBox vide via adaptateur, langue/script explicites ignores, confiance de detection nommee seulement `confidence`. |
| ElementRecord, confiances/doublons/decision/historique/verification | Champs presents, `confidence`, extraction/role/geometry/semantic_confidence. | Confiances d'extraction/geometrie forcees a 1, decision absente dans scene. Candidats de doublons non calcules sur chemin d'extraction. Warning d'ecarte n'est ni decision ni non-representabilite. |
| Section 2.1, huit fonctions publiques | `creer_element_record`, `ajouter_preuve`, `enregistrer_decision`, `marquer_conserve`, `marquer_non_representable`, `valider_invariants_scene`, `ordonner_elements_par_peinture`, `reperer_recouvrements` presentes. | Seul `enregistrer_decision` est appele par le constructeur de plan ; controle d'invariants/recouvrements/ordre canonique non branche en production. `marquer_conserve` accepte un simple mode en guise de decision ; `marquer_non_representable` ne met pas a jour le registre. |
| Scene neutre, aucune logique XML/LibreOffice/seuil AI | Aucun XML/choix lecteur dans `scene.py`. | Propriete structurelle presente. Cela ne compense pas les lacunes de couverture. |
| Chaine obligatoire ElementRecord -> SemanticRecord -> RenderDecision (`plan:77`) | Features, listes de groupes et attributs semantiques existent. | Type/contrat public `SemanticRecord` absent ; les groupes de `semantic.py` ne portent pas une issue canonique avec preuves/confiance/frontieres transmissibles. Cette lacune reste une exigence de la chaine, meme si le plan ne detaille pas ses champs. |
| Section 2.2, AnalysisOptions | Tous noms explicites presents ; alias `allow_raster_fallback` applique (`options.py:68`). | Aucun objet options unique transmis depuis extraction/CLI. Dans analyse/decision, seule politique raster-orientation et quelques seuils sont effectivement consommes ; use_native/ocr/layout/langue/script/detection/reading_order/line_boundaries/priorites/target_reader ne pilotent pas ces chemins. Extra d'un champ connu ignore. `LOCAL_RASTER` accepte meme avec fallback interdit (sonde R10). |
| Section 2.3, RenderDecision/champs/helpers | Tous les dix champs listes et cinq fonctions presents. | `verifier_decision()` accepte raison vide, pas de fallback, expected_* absents et `requires_verification=False`. `decision_is_lossless()` ne regarde que deux modes, pas preuves/contraintes/pertes ; helper jamais consomme en production. Le booleen `safe_reflow` explicitement exige par le plan a la section 14 n'existe pas dans RenderDecision. |
| Section 2.4, geometrie commune | Aire/intersection/recouvrement/union/clipping/centre/IoU bbox, overlap par axe, angle et quad_bbox (`analysis/geometry.py`). Repere EMU et PageGeometry presents (`geometry.py:68`, `:135`). | Projections x/y dediees, IoU quadrilatere et distance baseline absents ; quad_bbox ne remplace pas IoU quad. Courbure/chemin non centralises ; seuil horizontal 8 deg ici contre 7 deg dans `extract/orientation.py:89`, et vertical 8 contre 10 deg. Seuils non dans options/profil. |
| Section 2.5, provenance publique | Six fonctions sur sept presentes : creer_source_id, lier_source_ocr_native, calculer_candidats_doublon, marquer_doublon_sans_supprimer, expliquer_filtrage, expliquer_fallback. | **`registre_elements(scene)` absent.** Creation source ID, liaison OCR/native, candidats/marquage doublons, fallback non utilises par extraction ; journalisation de filtrage seule branchee. `ElementRegistry` existe mais n'a pas de raccordement aux evenements de rendu/non-representabilite. |

`SceneDocument([page])` ne passe pas par `add_page()` et laisse le registre vide ; `validate_scene()` retourne alors `[]`. Inversement, apres adaptation, `marquer_non_representable(record, raison)` change l'enum mais `registry.missing_terminal_states()` continue de signaler ce record. Les etats d'objet et les evenements de registre ne sont pas une machine d'etats commune (`scene.py:335`, `:398`, `provenance.py:44`). Le registre accepte aussi `warning` comme etat terminal sans exiger decision ni cause (`provenance.py:45`).

## Matrice IR exigee par la section 4

| Type / API | Elements deja presents | Champs/obligations manquants |
| --- | --- | --- |
| FontAsset (`ir.py:22`) | Donnees/chemin/embedding ; `metriques`, mode/alias/confiance_resolution. | Couverture Unicode, equivalence **validee**, source de substitution explicite, `font_confidence`, `metrics_confidence`. Une confiance de resolution n'est pas une confiance de metriques. |
| FontRef (`:45`) | Reference/style historique. | Script, langue, role typographique, identifiant canonique distinct du nom source. |
| MediaItem (`:86`) | Seulement media_ref/donnees/extension. | Dimensions natives, mode couleur, alpha, hash, provenance, DPI, distinction media source/composite fallback. |
| Span (`:95`) | Typographie, source_id, quad, baseline_points, z_index. | source_kind, language, script, confidence, glyph_ids, to_unicode_status ; champs existants d'origine non renseignes par l'acquisition native/OCR usuelle (`extract/text.py:218`, `extract/ocr.py:94`). Alias z_index/baseline_points existent mais leur transport reste incomplet. |
| Line (`:121`) | Baseline_points/quad/orientation/source_id. | Direction de lecture, script, score de segmentation, boundary_before/boundary_after avec confiance. La frontiere en `presentation` d'un paragraphe (`analysis/text_segmentation.py:333`) ne satisfait pas ce contrat Line. |
| TextBox (`:144`) | Geometrie, semantic_role et champs layout_frame, source_ids. | group_id explicite, preuves de regroupement ; layout_frame_id ne distingue pas groupe semantique et cadre geometrique. |
| FlowParagraph (`:169`) | Conteneur renderer, source_ids et lignes. | paragraph_confidence, source_line_ids, render_decision_id ; creation directe par extracteur `document.py:313` sans decision semantique sure ; classe seule prise comme confirmation (`render_plan.py:89`). |
| ImageEl (`:213`) | z_index, placement_id/xref, quad/transform, alpha_preserved, clip_bbox, paint_group_id. | Opacite numerique et confiance ; provenance commune/parent complet non transferes dans scene/plan. alpha_preserved n'est pas l'opacite. |
| ShapeEl (`:228`) | Chemins, alpha, z_index. | Clipping, groupe parent, source et confiance. Chemins/alpha perdus dans adaptation (B3). |
| RasterEl (`:240`) | z_index, purpose optionnel, placements/xrefs, paint_group/sequences. | Clipping/opacite/confiance ; cause fallback et elements remplaces obligatoires absents : construction sans purpose/sources admise, ni validation ni relation aux observations remplacees. |
| TableBorder/Cell/Row/TableEl (`:254`) | Bordures, contenu, spans ; fusions col_span/v_merge explicites. | Confiances cellule/ligne/table, preuves de grille, source des textes ; distinction table visuelle/semantique non encodee dans TableEl, decision NATIVE_TABLE inconditionnelle (`decisions.py:100`). |
| LinkZone (`:293`) | bbox/uri/page_cible. | Provenance, texte associe, ordre de peinture. |
| Page/Document (`:305`, `:323`) | Conteneurs, discarded_elements et repere Page ; Document.scene optionnel. | scene_id, source_pdf_id, options_snapshot, diagnostics, element_registry ; validation IR avant rendu absente. SceneDocument.registry ne fournit pas les champs publics de ces conteneurs. |
| Six fonctions publiques (`plan:388`) | Aucune des six exposee. | **iter_elements, element_text, element_source_ids, element_geometry, clone_element_with_metadata, validate_document_ir** toutes absentes. Les helpers prives du renderer ne satisfont pas ces API publiques. |

Nuance d'acquisition : l'outil bbox `extract/native_document.py:111` attribue des IDs aux blocs/lignes/spans, apres sa propre deduplication/absorption de lettrine (`:78`, `:108`). Ce chemin ne prouve pas l'identification de toutes observations brutes du convertisseur `extract/document.py`, et n'attache pas de scene. La segmentation attribue aussi des IDs de paragraphes apres regroupement (`analysis/text_segmentation.py:442`) et des sources locales `line:{ordinal}` (`:64`) ; cela ne remplace pas un ID d'observation lie au PDF avant filtrage.

## Reproductions en memoire

Les sorties ci-dessous ont ete observees sur le worktree audite. Le provider de comprehension texte est absent dans l'environnement de sondage ; le repli deterministe a emis un avertissement, sans appel reseau. Les sondes testent les fonctions publiques et les filtres precis, pas une conversion visuelle du corpus.

| Sonde | Entree / appel | Sortie observee |
| --- | --- | --- |
| R1 | Deux TextBox identiques, source_id native/ocr ; `_dedoublonner_textes_positionnes(page)`. | actifs=1, ecartes=0 ; perdant history contient filtered/duplicate-positioned-text ; scene IDs=['native']. |
| R2 | Page actif visible + ecarte discarded motive ; scene puis build_render_plan. | Scene deux records sans render_decision ; plan seulement visible ; plan.validate=[] ; valider_invariants_scene=[] ; registre manque les deux etats. Plan vide : contrat conforme=True. |
| R3 | TextBox vertical, source box-id, Line line-id angle=90/z=0 ; spans keep/drop ; zone sur drop. | Seulement keep ; nouveau TextBox/Line source_id=None, orientation=horizontal, line.z_index=None ; aucun historique sur original ou span retire. |
| R4 | Adapter les memes objets sans source_id dans ordre [A,B] puis [B,A]. Forme alpha=0/z=0 en index 2. | A passe p1-e1/legacy:0:0 -> p1-e2/legacy:0:1 ; forme devient opacity=1.0, z_order=2, path=(). |
| R5 | preserve_line_boundaries='always' sur deux lignes continues confirmees ; seuil gap=2.4 via extra compare au champ explicite. | Groupes [2], decision native-flow ; gap explicite groupes [2] contre wrapper extraction extra [1,1]. |
| R6 | SceneDocument([page]) sans register ; RenderDecision native-flow sans raison/fallback/expected et requires_verification=False. | Registre {}, validate_scene=[], invariants=[] ; verifier_decision=[]. |
| R7 | Phrase terminee + continuation minuscule, seuil confiance=.9, confiance calculee=.8. | Groupes initiaux [2], groupes preserves [1,1], preparation finale ['Premiere phrase. puis la suite']. |
| R8 | Objet source_kind='ocr', language='ar', script='arabic', quad/baseline renseignes sur Line. | Record scene pdf-native/auto/auto, quad=(), baseline=(), style={} ; record plan source_kind=pdf-native. |
| R9 | Marqueur '*' ID marker et corps ID body ; build_document_render_plan. | Scene IDs marker/body ; plan [('body', ('body',), 'native-list')], plan.validate=[]. |
| R10 | RasterEl purpose='local-fallback', allow_raster_fallback=False. | Decision local-raster, raison explicit-composite, fallback=None. Aucune interdiction/non-representabilite. |
| R11 | hasattr sur les API absentes. | Six helpers IR=False, provenance.registre_elements=False, scene.RenderMode=False. |

Commande autonome pour reproduire les blocages principaux, sans ecriture :

```bash
.converter/bin/python -B - <<'PY'
from pdfexact.geometry import BBox, pt_vers_emu as u
from pdfexact.ir import Document, Page, FontRef, Span, Line, TextBox, ShapeEl
from pdfexact.scene import scene_from_legacy_document, valider_invariants_scene
from pdfexact.analysis.options import AnalysisOptions
from pdfexact.analysis.provenance import expliquer_filtrage
from pdfexact.analysis.semantic import regrouper_paragraphes, preserver_frontieres_ambigues
from pdfexact.extract.document import _dedoublonner_textes_positionnes, _filtrer_textes_intersectant_zones
from pdfexact.render.render_plan import RenderPlan, build_render_plan, build_document_render_plan
from pdfexact.render.native_contract import valider_contrat_word_native
from pdfexact.render.reflow import prepare_page_elements
font = FontRef('Arial', 'Arial', False, False)
def box(text, ident, y=10):
    bbox = BBox(u(10), u(y), u(170), u(y+12))
    line = Line(bbox, [Span(text, font, 12, '000000', bbox=bbox)], u(12), u(160))
    return TextBox(bbox, [line], source_id=ident, semantic_role='body')
a, b = box('same text', 'native'), box('same text', 'ocr')
p = Page(0, u(300), u(200), [a, b])
_dedoublonner_textes_positionnes(p)
print('R1', len(p.elements), len(p.discarded_elements), getattr(b, 'decision_history', None))
a, b = box('visible', 'visible'), box('discarded', 'discarded', 30)
expliquer_filtrage(b, 'covered-by-zone')
doc = Document([Page(0, u(300), u(200), [a], discarded_elements=[b])])
doc.scene = scene_from_legacy_document(doc)
plan = build_render_plan(doc)
print('R2', [(e.element_id, e.render_decision) for e in doc.scene.all_elements()],
      [i.element.element_id for i in plan.for_page(0)], plan.validate(),
      valider_invariants_scene(doc.scene),
      valider_contrat_word_native(doc, RenderPlan({}, AnalysisOptions())).conforme)
s1 = Span('keep', font, 12, '000000', bbox=BBox(10, 10, 40, 20), source_id='span-a')
s2 = Span('drop', font, 12, '000000', bbox=BBox(50, 10, 90, 20), source_id='span-b')
line = Line(BBox(10, 10, 90, 20), [s1, s2], 10, 80, source_id='line-id',
            orientation='vertical', angle_deg=90, z_index=0)
original = TextBox(line.bbox, [line], source_id='box-id', orientation='vertical')
filtered = _filtrer_textes_intersectant_zones([original], [BBox(50, 0, 100, 30)])
print('R3', [(e.source_id, e.orientation, e.lignes[0].source_id,
              e.lignes[0].orientation, [s.texte for s in e.lignes[0].spans]) for e in filtered])
shape = ShapeEl(BBox(0, 0, 100, 100), [[('line', ((100, 100),))]], 'FFFFFF', None, 0,
                alpha=0, z_index=0)
scene = scene_from_legacy_document(Document([Page(0, u(300), u(200), [a, b, shape])]))
r = list(scene.all_elements())[-1]
print('R4', r.opacity, r.z_order, r.path)
a, b = box('Premiere phrase.', 'a'), box('puis la suite', 'b', 24)
opts = AnalysisOptions(semantic_group_min_confidence=.9)
groups = regrouper_paragraphes([a, b], opts)
print('R7', [len(g) for g in preserver_frontieres_ambigues(groups, opts)],
      [getattr(e, 'texte', None) for e in prepare_page_elements([a, b], opts)])
marker, body = box('*', 'marker'), box('Body text', 'body')
marker.bbox = BBox(u(1), u(10), u(5), u(22))
marker.lignes[0].bbox = marker.bbox
plan = build_document_render_plan(Document([Page(0, u(300), u(200), [marker, body])]))
print('R9', [(i.element.element_id, i.element.source_ids, i.decision.mode.value)
             for i in plan.for_page(0)], plan.validate())
PY
```

## Portee des tests et suite concrete

Lecture ciblee de `tests/analysis/test_universal_contracts.py` : le test de registre enregistre manuellement l'element (`:68`), celui des ecartes ne demande qu'un warning (`:239`), celui de plan couvre un seul actif synthetique (`:134`), celui d'extraction verifie seulement un nombre d'elements et un index (`:208`). Ils ne prouvent pas la couverture de toutes sources, ni les decisions des ecartes, ni l'identite commune scene/plan, ni l'interdiction d'ecriture d'un plan incomplet. Le test de listes attend meme la disparition du marqueur sans verifier sa provenance (`:113`). Les tests de segmentation sont utiles pour leurs cas precis ; ils ne certifient pas les autres contrats.

Sondes R1-R11 terminees, processus Python code retour 0 ; ce retour signifie execution des reproductions, pas conformite du logiciel. Pas de suite pytest relancee pour eviter la duplication du worker evidence/baseline et respecter l'unique ecriture autorisee. Aucune conclusion de completion globale, de fidelite visuelle, de compatibilite lecteur ou d'absence de regression.

Ordre d'action suggere au parent : B1/B2 (inventaire source et couverture bloquante), B3 (adaptation sans perte et IDs communs), B4 (frontieres/options conservees), puis fermeture explicite des champs et API encore absents dans les matrices. Le backend phase 4 pourra alors recevoir un plan dont chaque source a une issue explicable. Le present rapport ne valide pas la phase 4.

## Empreintes de l'etat audite

HEAD : `03a5b4839773cb1e27ae2255e66307fe59d13a89`. Fichiers locaux modifies/non suivis inclus dans l'audit ; HEAD seul ne decrit pas cet etat. Empreintes SHA-256 prises avant redaction :

```text
ca6bb1957624836912b6a98a33d3f11b542b69c5165fbfaf3b809b06b3fbed93  docs/plan_refonte_modules_universels_reconstruction.md
784011a531a640cbe5b2afd1f6e1dbedfc8ffe93ede549abdcdff7c583879b26  pdfexact/scene.py
94b3727d13a83f811403a42ec8310fdd9d8f090234a8a7df366c99c60525fcf4  pdfexact/ir.py
65e0318647327eba0d9abe531491fb7b32425aa00c3c637d246af601672301e1  pdfexact/analysis/options.py
31eb02b0a02dbcfb868e7a1e05d03e0633da8206c7c6d237fee413220770bd56  pdfexact/analysis/decisions.py
44109aea0a36d23523d977c22607872884141cc8eee9dd3e06ad8a04edbce2c5  pdfexact/analysis/provenance.py
2ebf1f4cbe43a11057a14cf26b3382532d36e062c4c7f42b96242ded9ce34e16  pdfexact/analysis/geometry.py
d2c9d0d01e7750d1129ee08ff552ff21b32f88d166fe2548d7b3ca05e3f12db1  pdfexact/geometry.py
785a5b080ca835a5f48c617b540960a7ce80e38ab262bfcbd46b3df5fff48d8b  pdfexact/analysis/semantic.py
538478b652160581b9801a459c27b1100a3b18523d5321d809e5ccafd97d38f9  pdfexact/extract/document.py
77010b0ef0411ba38096942baa9c68ae9f5f54c3b855ca82746413c42ea19d0e  pdfexact/render/render_plan.py
dc27439b04d38588d5225894fed4b5589f0a1d5a11516d7e45cd2d3a74b27de7  pdfexact/render/reflow.py
```

Controle final : ajouts concurrents preserves dans `analysis/provenance.py` (`source_paint_index`, ligne 8) et `analysis/semantic.py` (`text_paint_fragments`, ligne 19). Le premier conserve correctement la sequence zero, mais n'est pas consomme par les deux adaptateurs identifies en B3 ; leurs expressions `or index` restent presentes. Le regroupement/liste/options et le registre audites restent identiques. Les references numeriques ci-dessus correspondent a l'etat initial empreinte ; pour les anciennes fonctions de provenance ajouter 14 lignes, pour celles de semantic ajouter 61 lignes (sauf imports). Exemples actuels : `_option:347`, `_replace_list_metadata:563`, `preserver_frontieres_ambigues:697`, `ElementRegistry.missing_terminal_states:58`, `expliquer_filtrage:177`.

Commande autonome du rapport rejouee apres ces ajouts : R1, R2, R3, R4, R7 et R9 reproduisent exactement les sorties annoncees, code retour 0. Les dix autres fichiers empreintes sont restes identiques lors de cette verification. Empreintes finales des deux fichiers ayant change :

```text
9049c2a846ab569156ba60896fce1a847b42fe96f9166daca80a4fdbf6da2747  pdfexact/analysis/provenance.py
0d8c3b4f7162b4f0f648a8a8ffd7ac172bd6c57f8e02ed5b36c6c02345f27cec  pdfexact/analysis/semantic.py
```

## Checkpoint d'integration du 2026-10-11 : B2/B3, production gelee

Cette section est un ajout au rapport initial, preserve integralement ci-dessus. Les constats, references de lignes, empreintes et restrictions read-only precedents decrivent l'etat initial de l'audit, pas le code apres implementation. Le parent a ensuite autorise une tranche amont B2/B3, helpers IR et metadonnees. Il a confirme son gel apres le checkpoint **168 tests passes, dont 31 nouveaux cas amont**. Cette mise a jour ne modifie que le present rapport ; aucun nouveau code, test, lancement de suite ou changement de backend n'est effectue pendant le gel.

### Commandes et resultats observes

Commande du dernier controle propre aux nouveaux contrats, executee avant le gel :

```bash
.converter/bin/pytest tests/analysis/test_upstream_source_contracts.py -q --disable-warnings
```

Resultat exact : `31 passed in 0.44s`, code retour `0`.

Commande du dernier lot cible extraction/geometrie/integration, executee avant le gel :

```bash
.converter/bin/pytest tests/analysis/test_upstream_source_contracts.py tests/extract/test_elements.py tests/extract/test_document_layout_filters.py tests/extract/test_document_reading_frames.py tests/extract/test_source_paint_provenance.py tests/extract/test_directed_text_angles.py tests/extract/test_orientation.py tests/test_rasterize_cleanup.py tests/analysis/test_paragraph_segmentation.py::test_paragraph_ids_are_page_scoped_even_when_pdf_line_ids_repeat -q --disable-warnings
```

Resultat exact : `168 passed in 2.35s`, code retour `0`. La session deja lancee a ete pollee jusqu'a sa terminaison normale apres la demande de checkpoint immediat ; elle n'a ete ni tuee ni redemarree. Aucun processus necessaire a ce lot ne reste actif. Les 31 cas amont sont inclus dans les 168, pas additionnes a ceux-ci.

Ce lot n'est ni une fullsuite, ni une baseline non visuelle complete, ni une validation visuelle du corpus, ni une certification globale des phases 0-3. La baseline Arendt `792 passed, 1 skipped` a ete communiquee par le parent pour un autre etat ; elle n'a pas ete reproduite par ce worker. Aucun succes de publication DOCX ou de compatibilite lecteur n'est deduit de ces tests.

### Fichiers de la tranche

Production modifiee exclusivement dans le perimetre autorise :

- `pdfexact/scene.py` : identite d'acquisition, inventaire/snapshots, fabrique canonique, registres, etats et ordre de peinture.
- `pdfexact/ir.py` : champs appendus avec valeurs par defaut compatibles, et six helpers publics.
- `pdfexact/extract/document.py` : capture avant filtres, clones metadata, conservation des perdants/rejets, relations raster et preservation des coordonnees source.
- `pdfexact/extract/text.py` : identite et metadonnees natives, glyphes/quads/baselines/peinture, comparaison de doublons avec equivalent-paint.
- `pdfexact/extract/native_document.py` : identite avant dedup/lettrine, observations et transformations retenues, scene canonique finale.
- `pdfexact/extract/ocr.py` : observations avant filtres OCR, identites/metadonnees, liens de transformation et preuves producteur raster.
- `pdfexact/analysis/geometry.py` : projections, IoU quad, distance baseline, courbure/chemin et resolver d'orientation partage.

Nouveau fichier de tests : `tests/analysis/test_upstream_source_contracts.py`. Rapport : `docs/audit_contrats_refonte_2026-10-11.md`. `analysis/options.py` n'a pas ete modifie par ce worker. Aucune edition de `semantic.py`, `provenance.py`, `decisions.py`, `reflow.py`, `render_plan.py`, drawing, rewriter, backends, package ou native_contract ; leurs changements concurrents sont preserves. Les tests existants n'ont pas ete modifies par ce worker.

### APIs stabilisees et consommees

```python
ensure_source_identity(element, page_index, *, source_kind=None, source_pdf_id="", source_token=None)
capture_source_observations(page, elements, *, source_kind=None)
record_source_transformation(page, sources, outputs, reason_code, **details)
element_record_from_legacy(element, page_index, *, document=None)
scene_from_legacy_document(document)
resolve_text_orientation(element) -> dict[str, object]
```

Les cinq premieres fonctions sont dans `scene.py`, le resolver dans `analysis/geometry.py`. `element_record_from_legacy` est l'unique fabrique scene/plan communiquee a Hubble et Lovelace ; le consommateur de plan de Hubble l'utilise. La construction de scene initialise les identites par `capture_source_observations` avant adaptation. La validation prewrite ne doit pas attribuer des IDs pour reparer une couverture incomplete.

Contrat du resolver, stabilise et communique a Hubble pendant le gel :

```python
{
    "angle_deg": angle,
    "orientation": orientation,
    "parent": {"angle_deg": parent_angle, "orientation": parent_orientation},
    "conflicts": tuple({
        "parent": {"angle_deg": parent_angle, "orientation": parent_orientation},
        "line": {"angle_deg": line_angle, "orientation": line_orientation},
        "line_source_id": line_source_id,
    } for each_conflict in observed_conflicts),
}
```

Le parent non default conserve sa geometrie ; la ligne unique n'est un fallback que lorsque le parent est default. Une observation enfant contradictoire reste dans les snapshots et dans `geometry_conflicts`, avec preuve `geometry-conflict` et confiance `None`. La fabrique le consomme deja. Le raccordement de `orientation_of` et `geometry_contract_for` au meme resolver reste dans le perimetre de Hubble et n'est pas declare termine ici.

`Page.source_inventory` contient les copies d'acquisition, y compris lignes/spans/cellules/lignes de table et observations sans bbox. `Page.source_transformations` contient les evenements separes. Les IDs acquis restent les memes entre scene et plan ; les sorties filtrees/decoupees ont des IDs derives et des relations `replaces`, `original_source_ids`, `removed_source_ids` ou `source_component_ids`. Les alias locaux historiques `Line.source_id='line:{ordinal}'` sont normalises a l'acquisition sous l'identite du parent, avec `legacy_local_source_id` conserve ; les IDs deja acquis ne sont pas remplaces par des indices de sortie.

Departage de peinture : `record.attributes['source_acquisition_index']`, apres `z_order`, sans bbox/hash. Les egalites non renseignees gardent l'ordre d'insertion stable. L'ordre de lecture reste distinct. `RenderMode` est expose paresseusement par `scene` depuis l'enum possedee par `decisions`, sans duplication.

Helpers IR exposes : `iter_elements`, `element_text`, `element_source_ids`, `element_geometry`, `clone_element_with_metadata`, `validate_document_ir`. Texte/source IDs/clonage sont consommes par les raccordements de cette tranche ; l'exposition et les controles structurels de `validate_document_ir` ne prouvent pas son utilisation globale avant ecriture. Les hooks `bind_state`/`registre_elements` ont ete demandes a Hubble, qui les a ajoutes dans son propre perimetre ; aucun changement de provenance par ce worker.

### Contrats B2/B3 etablis par les tests cibles

- Identification avant les filtres raccordes ; originaux et descendants accessibles dans l'inventaire, sans promotion automatique en warning/non-representable.
- Doublon retire seulement sur equivalent-paint verifie : texte, police/style, geometrie, couleur, alpha/opacite, z-order, clipping et famille source compatibles. Perdant retenu avec `duplicate_of` et `duplicate_verified`. Les variantes de peinture natives et les fragments ambigus restent actifs ; OCR/natif n'est pas une equivalence de peinture.
- Clonage des lignes/TextBox filtrees sans perte des metadonnees declarees ou dynamiques ; IDs des spans retires exclus de la lignee conservee et exposes dans `removed_source_ids`. Les spans retires restent `DETECTED`, sans decision fabriquee.
- Fabrique commune transportant spans/runs, styles/polices/metriques disponibles, geometrie parent/enfants distincte, chemins, clipping, groupes/compositing, langues/scripts effectivement observes, preuves/historiques et snapshots source. Zero de sequence et zero d'alpha/opacite ne deviennent pas des valeurs par defaut.
- Conservation du parent 90/180 degres face a un enfant default ; observations geometriques contradictoires explicites. SourceKind herite uniquement des descendants connus coherents ; familles connues melangees restent `INFERRED` avec conflit, jamais PDF-native invente. Les confiances inconnues restent `None` ; la decision est conservatrice, sans confiance source fabriquee a 1.
- Initialisation du registre par constructeurs, synchronisation apres ajout et changement d'etat ; observation de span sans bbox enregistree avec `bbox=None`, sans geometrie inventee.
- Tables rejetees, vecteurs hors page et composants raster conserves. L'evidence hors page contient les bboxes source/page et une intersection effectivement nulle ; elle n'est pas une non-representabilite generique.
- Capture native des quads/baselines/glyph IDs, Unicode decode et peinture. `decoded-unicode` constate le decodage disponible, pas la validation d'un CMap ToUnicode.
- Suppression des appels destructifs a `_quantifier_page` dans l'assemblage de `extraire` : les coordonnees acquises restent identiques dans actifs/inventaire/scene et passent le cas B1 precis. Le helper legacy subsiste mais n'est plus appele par cet assemblage. Toute quantification cible reste une transformation de sortie a expliciter, pas une mutation source autorisee implicitement.

### Restes requis : priorites d'integration et matrice IR

Ces obligations restent celles du plan, pas des options futures. La tranche n'etablit pas une couverture terminale de toutes les sources de tous les chemins.

1. **Gate crop encore ouvert.** `_securiser_elements_visuels_page` conserve toutes les metadonnees, le parent brut et les fragments a IDs derives. Son journal contient `capture_method='source-media-pixel-crop'`, source/output IDs, media_ref et bboxes. La couverture collective des fragments n'est pas acceptee par le validateur de plan actuel : Hubble rapporte un cas reel `1 ImageEl -> 24 fragments + 1 ecarte`, rejete `unverified-source-transform`. Ne pas remplacer ce gate par une alias source ID, une non-representabilite generique ou une fausse equivalence pixel.
2. **Resolver et regressions de Hubble.** Raccorder `orientation_of`/`geometry_contract_for` au resolver stabilise. Hubble rapporte encore quatre echecs hors du lot 168 : deux cas `mixed_page_preserves_locked_nodes` avec mutation reflow et deux anciennes attentes de `test_universal_contracts` (compte actifs seuls et warning d'ecarte). Ils ne sont pas relances ni corriges par ce worker pendant le gel. Le precedent echec de collision `line:0` est corrige et son test existant est inclus dans le lot 168.
3. **Decisions des observations restantes.** Rejets ambigus, spans retires et transformations non prouvees restent retenus et exigent une decision centrale ou une non-representabilite motivee avec preuve. L'inventaire n'est pas une preuve de couverture ; un journal n'est pas une decision terminale. Les filtres internes non raccordes dans les modules hors perimetre, notamment images/tables, ne sont pas certifies par cette tranche.
4. **Preuve raster producteur et verification visuelle distinctes.** `_lier_composants_raster(..., dpi=...)` et le raccordement OCR portent cause, IDs remplaces et `Evidence(kind='raster-replacement', source=producer, confidence=None, details=...)`. Les details incluent reason/source_ids/output_id/dpi/capture_method ; `pixel_equivalence_verified=False`. La relation de capture locale peut etre controlee avec la politique fallback et la bbox ; elle ne prouve pas l'equivalence des pixels rendus. Le chemin raster-page integral et les autres producteurs sans inventaire complet restent a verifier.

| Exigence initiale | Etat au gel de cette tranche | Alimentation/consommation encore requise ou non etablie |
| --- | --- | --- |
| FontAsset | Champs Unicode/equivalence/substitution/font_confidence/metrics_confidence declares ; metriques disponibles transportees par la fabrique. | Couverture Unicode mesuree, equivalence validee, source de substitution et confiances effectivement produites/consommees ; `None` n'est pas une mesure validee. |
| FontRef | Script/langue/role typographique/canonical_id declares ; reference/style conserves dans les runs. | Alimentation et utilisation systematiques de typographic_role/canonical_id ; langue/script seulement quand observes, pas une detection globale certifiee. |
| MediaItem | Dimensions/mode/alpha/hash/source_ids/DPI/media_kind declares avec defaults ; media_kind inconnu reste `unknown`. | Producteurs devant remplir dimensions/mode/alpha/hash/DPI/provenance et distinguer source/composite ; conservation des binaires media originaux au travers des nettoyages non etablie. |
| Span | Source kind/IDs, quad, baseline/baseline_points, z_order/z_index, langue/script/confiance/glyph_ids/to_unicode_status declares ; transport et acquisition native cibles testes. | Exhaustivite de tous extracteurs, resolution des glyphes non decodes, validation CMap et decisions des observations retirees/non representables. |
| Line | Source/quad/baseline/langue/script, direction/segmentation/frontieres et confiances declares ; clone complet et snapshots testes. | Alimentation/consommation globale de reading_direction, segmentation_score, boundary_before/after et leurs confiances ; frontieres semantiques sous controle de Hubble. |
| TextBox | group_id/grouping_evidence/source/confidences et metadonnees visuelles declares, transportes si presents. | Production et consommation systematiques des preuves de groupe ; un layout_frame ne suffit pas a etablir un groupe semantique. |
| FlowParagraph | paragraph_confidence/source_line_ids/render_decision_id declares ; adaptateur natif conserve IDs/lignes et ne fabrique plus une confirmation semantique par la classe. | Creation uniquement apres decision semantique sure ; creation directe legacy encore presente, alimentation de paragraph_confidence/render_decision_id et validation centrale a clore. |
| ImageEl/ShapeEl | Source/confiance, clipping, opacite/groupe/compositing et geometrie transportes si observes. | Exhaustivite des acquisitions hors perimetre et materialisation backend de toutes ces contraintes ; transport n'est pas rendu prouve. |
| RasterEl | Cause/source_component_ids/provenance/metadata declares ; relations des clusters et regions raccordees, fragments conserves. | Gate collectif crop, inventaire complet des autres producteurs/fallbacks et controle de sortie ; aucune equivalence pixel declaree. |
| TableBorder/Cell/Row/TableEl | Confiances/provenance/preuves de grille/text_source_ids et semantic_table declares ; fusions existantes conservees ; tables rejetees retenues. | Alimentation des confiances/preuves/text_source_ids et distinction visuelle/semantique effectivement utilisee avant NATIVE_TABLE. |
| LinkZone | Source/associated_text/z_index/confiance declares et transportes si presents. | Alimentation du texte associe et peinture/source de toutes annotations ; conservation des enrichissements de liens a etablir dans la couverture centrale. |
| Page/Document | scene_id/source_pdf_id/options_snapshot/diagnostics/element_registry declares ; identite PDF/options/inventaire et registry raccordes dans les chemins modifies. | scene_id/diagnostics/options a alimenter uniformement sur tous points d'entree ; validation d'invariants et couverture avant rendu a verifier globalement avec B1. |
| Six helpers IR | Tous exposes et testes ; element_text/element_source_ids/clonage consommes dans cette tranche. | validate_document_ir reste un controle structurel des actifs, pas la reconciliation complete actifs/ecartes/inventaire ; consumption globale avant ecriture et couverture des autres helpers non certifiees. |
| Geometrie commune | Projections x/y, quad_iou, baseline_distance, baseline_curvature, path_is_curved et resolver exposes et testes. | Nouveaux calculs quad/baseline/courbure principalement testes, pas encore branches partout ; seuils d'orientation disperses et options partagees restent a unifier. |
| Scene/registre/options/decisions/semantique | Correctifs amont ci-dessus ; provenance et consommateurs sont possedes par Hubble, B1 prewrite par Lovelace. | SemanticRecord, completude des politiques/options, validation de decisions/etats terminaux et chaque autre obligation des matrices initiales non explicitement fermee ici restent a verifier. Aucune completion Phase 0-3 deduite des seules declarations de champs ou des 168 tests. |

Le parent reprend l'integration/fullsuite et assignera la prochaine tranche amont. Aucun switch global de backend n'est autorise par ce checkpoint. API factory/registry et resolver communiques a Hubble/Lovelace ; Hubble informe du gel et de sa responsabilite sur le raccordement resolver et les quatre echecs signales. Le suivi global reste la propriete d'Arendt et n'est pas modifie par ce worker.

## Checkpoint crop du 2026-10-11, 11:10 UTC : producteur gele

Append documentaire uniquement apres le gel demande par le parent. L'audit initial et le checkpoint B2/B3 precedent sont conserves comme historique. Aucun nouveau test, fullsuite, changement de production ou reprise de session n'est lance pour cet append. Les obligations non explicitement fermees des matrices precedentes restent requises.

### Perimetre livre et coordination

- Production de la tranche crop : `pdfexact/fallback/rasterize.py` (`segmenter_elements_visuels_page`, `_decouper_media`, geometrie partagee producteur/verificateur) et `pdfexact/extract/document.py` (`_securiser_elements_visuels_page`, docstring corrigee vers l'ordre total de peinture source).
- Nouveau fichier de tests : `tests/extract/test_collective_media_crop_contract.py`. Aucun nouvel edit scene/IR n'a ete necessaire pour cette tranche ; factory/registry B2/B3 restent ceux du checkpoint precedent.
- Hubble a reconnu `media-crop-partition-v1` et l'API publique `verify_media_crop_partition(source, outputs, media, proof, *, require_verified=True) -> list[str]`. Il possede exclusivement le consommateur RenderPlan, ses snapshots media et ses tests de validation. Source est l'observation brute acquise ; outputs est l'ensemble des tuiles, pas une tuile consideree seule ; media est le registre de binaires effectivement valide.
- Le parent a ensuite informe Hubble directement du gel. La notification de ce worker, cellule `110`, s'est terminee sur timeout de revue d'autorisation automatique ; aucun retry/restart n'a ete fait. Ce n'etait pas une session de tests. Toutes les sessions pytest de ce worker sont terminees.

### Commandes effectivement executees et comptes distincts

```bash
.converter/bin/pytest tests/extract/test_collective_media_crop_contract.py -k 'not real_native_extraction_to_plan' -q --disable-warnings
```

Resultat final producteur : **37 passed, 1 deselected in 1.74s**, exit 0, session `88909` terminee. Le cas deselectionne est le probe d'integration RenderPlan ci-dessous, pas un skip masque.

```bash
.converter/bin/pytest tests/analysis/test_upstream_source_contracts.py tests/test_rasterize_cleanup.py tests/extract/test_elements.py tests/extract/test_document_layout_filters.py tests/extract/test_document_reading_frames.py -q --disable-warnings
```

Resultat de regression ciblee : **115 passed in 2.23s**, exit 0, session `87058` terminee. Les **31 tests B2/B3** sont inclus dans ces 115. Ce lot recouvre une partie des 168 du checkpoint precedent : ne pas additionner ces comptes, ni les cumuler avec des comptes source/crop communiques par d'autres workers.

```bash
.converter/bin/pytest tests/extract/test_collective_media_crop_contract.py -q --disable-warnings
```

Derniere execution de ce fichier entier avant le raccordement du consommateur Hubble : **35 passed, 3 failed in 6.08s**, session `48096` terminee, exit 1. Deux erreurs d'assertion des nouvelles fixtures ont ensuite ete corrigees dans ce seul nouveau fichier : comparer l'historique de la tuile au snapshot acquis, pas au parent apres journalisation du filtre ; lire `scene.registry.elements`, pas un inexistant `ids()`. Ces deux cas font partie des 37 verts ci-dessus. Le troisieme etait le probe RenderPlan avec `unverified-source-transform`, non relance par ce worker apres le gel. Ces resultats ne constituent donc ni un dernier fichier entier vert, ni trois echecs de production restants. Le statut du consommateur apres ses propres modifications releve du checkpoint Hubble et de l'integration parent.

### Schema de preuve livre

Chaque tuile porte `Evidence(kind='media-crop-partition', source='pdfexact.fallback.rasterize', confidence=None, details=(('proof', proof),))`. Le journal contient cette meme preuve dans l'evenement `reason_code='source-media-segmentation'` ; ne pas prendre aveuglement le dernier evenement, car la journalisation d'un parent ecarte ajoute aussi un evenement sans preuve.

```python
proof = {
    'schema': 'media-crop-partition-v1',
    'capture_method': 'source-media-pixel-crop',
    'source': {
        'source_id': acquired_id, 'media_ref': acquired_media_ref,
        'payload': original_bytes, 'payload_sha256': sha256_payload,
        'rgba_sha256': sha256_decoded_rgba,
        'width': width_px, 'height': height_px, 'mode': decoded_source_mode,
        'geometry': acquired_geometry_snapshot,
    },
    'outputs': [{
        'source_id': tile_id, 'media_ref': tile_media_ref,
        'pixel_bounds': (x0, y0, x1, y1),
        'width': tile_width, 'height': tile_height, 'mode': 'RGBA',
        'payload_sha256': tile_payload_hash, 'rgba_sha256': tile_rgba_hash,
        'geometry': tile_geometry_snapshot,
    }],
    'partition_verified': computed_partition_result,
    'pixel_equivalence_verified': computed_equivalence_result,
    'reasons': [],
}
```

Les bornes pixel sont des entiers, debut inclus et fin exclue. Source et tuiles sont decodees reellement par PIL. Le verificateur controle schema, identites et ensemble complet des sorties, dimensions/modes, SHA-256 des payloads et des RGBA decodes, puis couvre la grille pixel pour detecter trous et overlaps. Il recompose chaque tuile sans masque alpha et compare les octets RGBA entiers a la source ; les RGB sous alpha zero ne sont pas ignores. Les flags sont initialement faux, renseignes seulement apres calcul, et toujours recontroles avec recalcul des faits au consommateur. `require_verified=False` est utilise pour cette premiere verification producteur, pas pour autoriser la validation de plan.

`geometry` est un deepcopy de `bbox`, `quad`, `transform`, `clip_bbox`, `clip_ids`, `alpha`, `opacity`, `z_index`, `alpha_preserved`, `paint_group_id`, `parent_group_id`, `compositing`, `source_kind`, `placement_id`, `source_xref`, `source_placements`, `source_xrefs`, `paint_sequences`. Les bboxes/quads sont canoniques en EMU ; les matrices PDF restent en points et sont composees avec les fractions pixel de la tuile. Le clip bbox est intersecte avec la tuile, sans remplacer un clip vide par l'absence de clip. Producteur et verificateur utilisent le meme calcul `_media_crop_geometry`, pas deux derives geometriques independantes.

Les IDs de tuiles sont derives de l'ID acquis et des bornes pixel source. `_securiser_elements_visuels_page` reutilise directement les clones canoniques du producteur et verifie contre `page.source_inventory[source.source_id]`, au lieu de recloner le parent avec seulement bbox/media_ref. Le parent brut, ses geometries et le payload media original sont conserves. Pour RasterEl, les tuiles gardent les composants amont et ajoutent l'ID du parent bitmap ; une preuve bitmap-vers-tuiles ne prouve pas par transitivite l'equivalence du raster aux vecteurs remplaces.

### Fixtures et evidence reproductible

- Fixture generale : PNG de **17 x 19 pixels**, modes `RGBA`, `RGB`, `L`, `P`, place sur **200 x 300 points**, matrice `(200, 0, 0, 300, 0, 0)`, **24 tuiles**. Les pixels RGBA avant conversion sont `(31*x % 256, 47*y % 256, (x+y) % 256, 13*x*y % 256)`. Le pixel `(3, 0)` vaut `(93, 0, 3, 0)` et est conserve a l'identique sous alpha zero.
- Petits medias : `(1,1)`, `(1,19)`, `(17,1)`, `(2,3)`, `(3,5)`, `(4,6)`. L'aire des bornes partitionnees est exactement l'aire source ; aucune tuile d'un pixel n'est forcee en chevauchement pour atteindre artificiellement 24 fragments.
- Absences adversariales : element tuile retire, payload tuile retire du registre, entree de preuve retiree. Alterations : pixels modifies, hashes de la tuile recalcules apres alteration, dimension redimensionnee, payload source altere. Le rehash d'une tuile modifiee reste rejete par `media-crop-rgba-reconstruction-mismatch`.
- Partition : borne x1 de la premiere tuile reduite ou agrandie d'un pixel ; rejet respectif `media-crop-pixel-hole` / `media-crop-pixel-overlap`.
- Geometrie/peinture : alpha dynamique, opacity et z_index tous **0** ; clip `(20,40,175,280)` points, `paint-A`/`parent-A`, placement/source_xref et compositing imbrique. Muter z, alpha, opacity, parent, clip ou matrice d'une sortie est rejete `media-crop-output-geometry-mismatch`. Muter le compositing du parent ne modifie pas le snapshot de preuve et produit un mismatch source.
- Raster : `raw-vector`, `placement-A`, xref `7`, sequence `(0,)` et cause `actual-vector-fallback` restent transports ; la preuve nomme le parent bitmap, pas le vecteur. Cette preservation est testee ; le verificateur n'etablit pas ici une equivalence pixel vectorielle amont.
- Ambiguites conservees : matrice tournee `(0,200,-300,0,300,0)`, quad contradictoire, matrice largeur `400` sur bbox largeur `200`. Source reste active, sans transformation prouvee ni non-representabilite generique, avec `crop_unverified_reasons` explicite. Un media remplace par un PNG blanc apres capture du snapshot est rejete par identite media acquise, pas promu en equivalence d'inpainting.
- Proofs malformes : `None`, dictionnaire vide, entree non dictionnaire, ID non chaine, bornes `None` ; erreurs retournees sans exception dans ces fixtures.
- Texte natif : ajout d'un TextBox/Line/Span `Native remains native`, meme objet/texte apres segmentation ; IDs actifs et ID du parent sont presents dans le registre canonique.
- Probe reel en memoire : PyMuPDF cree une page **200 x 300 points**, insere le PNG RGB **68 x 114 pixels**, puis `extraire_images -> _securiser_elements_visuels_page -> build_render_plan`. Acquisition **1 ImageEl**, sorties **24 tuiles**, **1 parent conserve** ; `verify_media_crop_partition(...) == []`. Le dernier run de ce worker s'arrete ensuite sur `unverified-source-transform:p0:inferred:ImageEl:24e101cb01486415a8103a79` dans `plan.validate(document)`, avant l'adoption Hubble. Ni le nom de fichier PDF ni une policy ad hoc n'interviennent.

### Gates et obligations restant ouverts au gel

1. **Consommation RenderPlan** : schema/API agrees ; adoption, validation sur medias reels et snapshot interne, adversariaux de plan et nouveau resultat du probe doivent etre etablis par Hubble. Le dernier rouge rapporte ici est historique pre-consommateur, pas un constat execute contre sa livraison ulterieure. Pas de contournement de `validate` ni de global completion deduit des 37 tests producteur.
2. **Crops legitimes non prouves** : rotations/reflets/cisaillements et ambiguite entre payload deja aplati et espace natif restent explicitement non verifies. Le gel ne ferme pas ces obligations ; elles peuvent etre documentees comme telles sans invalider les controles deja prouves sur la partition axis-alignee. Les sorties d'un producteur legacy/personnalise sans preuve restent `missing-producer-crop-proof` ; aucune relation terminale n'est fabriquee pour rendre la couverture verte.
3. **Resampling/inpainting et raster source-page** : le verificateur prouve seulement des crops pixel exacts d'un media acquis. Nettoyages, rerenders et compositions amont exigent leur propre preuve ; `source-page-region-render` et un boolean de capture ne constituent pas une equivalence pixel. Aucun nouveau travail sur ces producteurs hors tranche n'est inclus.
4. **Champs et consommation globale** : les MediaItem des tuiles renseignent dimensions/mode/alpha-channel/hash/source_ids/DPI connu/media_kind, sans completer fictivement les MediaItem source ou tous les autres producteurs. Le transport teste de source_component_ids n'est pas un test adversarial exhaustif de mutation de cette liste. FontAsset/FontRef, Unicode/ToUnicode, confidences, limites semantiques, tables/liens, diagnostics/options, toutes les autres lignes des matrices et la couverture terminale avant ecriture restent dans les obligations initiales tant qu'aucune preuve ciblee ne les ferme.

Aucun fullsuite n'est lance par ce worker. Le parent le coordonne apres le gel Hubble ; ses comptes et ceux d'Arendt/Lovelace ne sont pas recomptes ici. Aucun basculement global de backend, edit de suivi global ou edit de production apres gel.

## Checkpoint integration du 2026-10-11, 11:19 UTC : consommateur crop vert, gel global

Resultat communique par le parent apres la livraison Hubble : **76 tests GREEN en 182 s**, avec le probe producteur reel **1 image -> 24 tuiles**, et validation de plan **`[]`** reconnue. Ce resultat etablit le raccordement producteur-consommateur pour le cas jusque-la rejete `unverified-source-transform` ; le rouge du checkpoint precedent reste l'historique pre-consommateur, pas un echec courant de ce probe.

Ce worker n'a pas relance ce lot. Sa commande exacte et son detail de selection ne sont pas fournis dans ce message de coordination : ne pas en inventer, ni additionner les 76 aux comptes 37/115/168 ou aux autres lots workers qui peuvent se recouvrir. Les preuves d'execution detaillees restent celles de Hubble et de l'integration parent.

Tous les fichiers de production sont geles, sans edition jusqu'a un rapport d'echec et une nouvelle attribution. Arendt est autorise par le parent a lancer la **fullsuite globale et cinq diagnostics reels** ; il s'agit d'un lancement autorise, pas encore d'un resultat valide. Aucun test, diagnostic ou processus de production supplementaire n'est lance ici ; `docs/suivi_refonte_modules_universels.md` reste exclusivement sous sa responsabilite.

**TODO conserves** : chaque exigence du plan ou ligne des matrices sans validation explicite reste a faire. Les crops legitimes non prouves, transformations/espaces de clip ambigus, resampling/inpainting, preuves raster amont, champs encore partiellement alimentes et consommation/coverage globale ne sont pas fermes par ce checkpoint. Ni les 76 tests cibles ni le probe vert ne prouvent la completion globale des phases 0-3 ou du plan, et aucun basculement global de backend n'est autorise par cet append.

## Tranche OCR multilingue CPU, 2026-10-11, checkpoint 12:24 UTC

Nouvelle autorisation bornee, distincte de la refonte generale toujours pausee : acquisition Unicode, routage OCR local, options/API/CLI et tests cibles. Historique et TODO des matrices ci-dessus conserves. Aucun changement de semantic/provenance/decisions/reflow/render_plan/drawing/rewriter/backends, aucun relachement de garde, aucun fullsuite, aucune conversion des cinq anciens diagnostics reels. Worktree preexistant preserve.

### Inventaire reel, avant branchement et apres provisionnement Lovelace

Interpreteur d'execution : `/home/raphael/Mes_Projets/converter/.converter/bin/python`, Python **3.10.20**. Inventaire `importlib.metadata.version` releve dans cet environnement : RapidOCR **3.9.2**, ONNX Runtime **1.23.2**, PaddlePaddle **3.2.0**, PaddleX **3.3.11**, OpenCV **5.0.0.93**, Pillow **12.3.0**. `paddleocr`, `fastocr`, `easyocr`, `pytesseract`, `torch`, `onnx` absents lors de l'inventaire initial ; `paddleocr`/`fastocr` toujours absents au checkpoint. CTranslate2, absent initialement de `.converter`, est desormais **4.8.0**, installe par la tranche provisionnement ; `tokenizers` **0.23.1**, `transformers` encore absent ici. Les librairies/modeles Qwen de `.vysi` ne sont pas une preuve d'execution dans `.converter`.

Tesseract systeme **5.5.0**, Leptonica **1.84.1**. `tesseract --list-langs` : seulement **eng, fra, osd** sous `/usr/share/tesseract-ocr/5/tessdata`. Pas de reconnaissance russe/CJK Tesseract acquise par ce patch. `--ocr-layer` reste la couche Tesseract historique ; le routage multilingue de cette tranche concerne `--text-mode rapidocr`.

Configuration RapidOCR installee : `.converter/lib/python3.10/site-packages/rapidocr/config.yaml:22` racine par defaut nulle donc `rapidocr/models` ; `:26` threads automatiques ; `:33` CUDA desactive ; `:130` detection v6 small ; `:169` reconnaissance v6 small, langue ch ; `:180` dictionnaire externe nul. `rapidocr/utils/model_resolver.py:21` definit les alias et `:32` les langues v6 : chinois simplifie/traditionnel, japonais et langues latines, pas Cyrl/Hang. Changer seulement la langue en russe avec une version v6 n'est pas un branchement valide.

Trois ONNX initialement installes dans `/home/raphael/Mes_Projets/converter/.converter/lib/python3.10/site-packages/rapidocr/models/` : `PP-OCRv6_det_small.onnx` **9 929 594 B**, `PP-OCRv6_rec_small.onnx` **21 234 383 B**, `ch_ppocr_mobile_v2.0_cls_mobile.onnx` **585 532 B**. Ils etaient les seuls modeles utilises par l'ancien `_rapidocr() -> RapidOCR()`.

Alphabet ONNX v6 mesure, pas deduit du nom : **18 708 entrees**, dont **0 cyrillique, 0 hangul**, 15 908 Hani, 87 hiragana, 153 katakana, 613 lettres latines et 64 grecques. Couverture des 66 lettres russes majuscules/minuscules avec Ё/ё : **0/66** ; exemples chinois simplifie/traditionnel et japonais couverts ; exemple coreen **0/5**. Le nouveau routage n'annonce donc pas que le modele v6 sait lire le russe/coreen.

Sous `/home/raphael/Mes_Projets/vysi/ai_models/ppstructurev3/`, 15 bundles Paddle deja presents, dont `PP-OCRv5_server_det/inference.pdiparams` **87 932 887 B**, `PP-OCRv5_server_rec/inference.pdiparams` **84 390 117 B**, `inference.json` et `inference.yml`. Le dictionnaire rec YAML de **18 383 entrees** ne couvre que **11/66** lettres russes et **0/5** de l'exemple coreen : ce n'est pas un substitut v5 Cyrl/Hang qualifie. Autres bundles observes : PP-LCNet doc/textline/table, PP-DocLayout_plus-L, PP-DocBlockLayout, seal_det, SLANet_plus, SLANeXt_wired, RT-DETR-L cellules, UVDoc, PP-FormulaNet_plus-L, PP-Chart2Table. Leur presence n'est pas une preuve OCR.

Registre Vysi `/home/raphael/Mes_Projets/vysi/src/vysi/document_analysis/models/registry.py:27` declare OCRv5 ; `:203` marque la decouverte `INVENTORY_ONLY`. Adaptateur `document_analysis/adapters/ocr/paddleocr.py:244` importe `paddleocr` absent ; sa methode `:270` ignore `languages`. Variante PaddleX `:355`/`:360` charge des repertoires locaux avec device explicite, mais `:429` ignore egalement `languages` et garde son unique rec v5. Ces implementations sont inventoriees, pas branchees ou executees par ce worker. FastOCR declare dans le registre `registry.py:325` ne signifie pas paquet installe. L'aide CLI trompeuse sur FastOCR a ete corrigee dans notre fichier.

### Catalogue partage et modeles effectivement executes

Accord transmis a Lovelace et Hubble avant patch : `/home/raphael/Mes_Projets/vysi/ai_models/ocr/rapidocr/catalog.json`, `schema=pdfexact.ocr-models.v1`, **models est une liste**, ID = stem du fichier, path relatif a `catalog.parent`, `engine=onnxruntime`, task det/cls/rec, version, model_type, lang_type, scripts ISO, languages upstream non necessairement ISO, SHA256 du payload. `dictionary={source:onnx.metadata.character,sha256,count,classes_count}` conserve le hash **UTF8 exact** de la valeur metadata, sans normalisation ni deduplication. Preuve de provisionnement Lovelace : `results/model_provisioning_20261011.json` ; ses 11 zero-tensors CPU ne sont pas des tests de qualite linguistique.

Racine de tous les chemins relatifs du tableau : `/home/raphael/Mes_Projets/vysi/ai_models/ocr/rapidocr/v3.9.2/`. Extension `.onnx` pour chaque ID. **100 857 210 B** au total, aucun ancien modele ecrase. Detection/rec v6 et cls copies verifies depuis RapidOCR ; huit rec v5 provisionnes par Lovelace depuis les URLs officielles epinglees dans `rapidocr/default_models.yaml:78`, `:99` et les entrees voisines.

| ID/fichier | Role/scripts declares | Octets | Entrees alphabet / classes CTC |
| --- | --- | ---: | ---: |
| PP-OCRv6_det_small | detection partagee | 9929594 | sans dictionnaire rec |
| PP-OCRv6_rec_small | Latn/Hani/Hira/Kana | 21234383 | 18708 / 18710 |
| ch_ppocr_mobile_v2.0_cls_mobile | orientation partagee | 585532 | sans dictionnaire rec |
| cyrillic_PP-OCRv5_rec_mobile | Cyrl | 8074092 | 850 / 852 |
| korean_PP-OCRv5_rec_mobile | Hang | 13488748 | 11945 / 11947 |
| arabic_PP-OCRv5_rec_mobile | Arab | 8023828 | 747 / 749 |
| devanagari_PP-OCRv5_rec_mobile | Deva | 7940361 | 568 / 570 |
| th_PP-OCRv5_rec_mobile | Thai | 7915294 | 524 / 526 |
| el_PP-OCRv5_rec_mobile | Grek | 7832350 | 354 / 356 |
| ta_PP-OCRv5_rec_mobile | Taml | 7909926 | 513 / 515 |
| te_PP-OCRv5_rec_mobile | Telu | 7923102 | 540 / 542 |

Les neuf rec ont tous ete essayes sur chaque crop dans les smokes auto verts, avec `CPUExecutionProvider` verifie sur la session reelle ; detection et classification egalement CPU-only. Sessions mises en cache, threads ORT intra=2/inter=1, accelerateurs explicitement desactives. Construction baseline v6 initialement mesuree **1,86 s**. Le loader reverifie hashes/metadata, nombre de classes et alphabet du decodeur Rapid ; le wrapper verifie aussi le dernier axe des logits en inference. Pas de fichier dictionnaire generique de secours ni telechargement implicite : metadata absente => erreur explicite avant le constructeur Rapid qui, autrement, pourrait telecharger un dictionnaire chinois.

### Fichiers et API livres

- `pdfexact/model_paths.py:6` : `resolve_ai_models_root(value=None)` partage la priorite argument, `PDFEXACT_AI_MODELS_ROOT`, `VYSI_AI_MODELS_ROOT`, Vysi local, puis cwd/ai_models.
- `pdfexact/extract/ocr_routing.py:54` : `script_counts`, observations Unicode ISO sans convertir Cyrl en langue russe. `:85` `load_catalog`, `:128` `validate_alphabet`, `:179` `choose_candidate`, `:222` `LocalOcrRouter`, `:366` `get_local_ocr(model_root=None, language="auto")`. Reutilise RapidOCR, son detecteur, perspective-crops, classifieur, TextRecognizer/CTCLabelDecode et boites de mots. Ce n'est pas un nouveau moteur OCR.
- `pdfexact/extract/ocr.py:136` capture alternatives et ambiguite avant snapshot source ; `:171` transporte preuves et scripts vers sorties ; `:313` adapte le runtime ; `:559` preserve les caracteres non latins sans corrections latinisantes ; `:2179` ne rejette plus les titres non latins courts ; `:2376` ajoute **en fin de signature** `language="auto", model_root=None`. Filtrage des zones natives/interdites avant reconnaissance des crops. Resume dans `Page.diagnostics` (Page ne possede pas de champ attributes).
- `pdfexact/extract/text.py:196` : l'heuristique d'espacement ne traite plus les mots/lettres non latins comme texte illisible. Ni remapping de caracteres PDF ni changement des runs natifs.
- `pdfexact/extract/document.py:1764`, `:2202`, `:2278`, `:2339` passent language/root aux trois appels RapidOCR existants ; `:2433` expose `ai_models_root=None, ocr_language="auto"`, sans reordonner les arguments anterieurs. L'ancien supplement Tesseract anglais n'est actif qu'avec demande en/eng explicite, pas sur auto multilingue. Les modes spans/glyphs restent natifs ; aucune OCR ajoutee par simple presence de scripts.
- `pdfexact/analysis/options.py:46` ajoute les defaults `ocr_language="auto", ai_models_root=None`, sans reinterpretation de language/script semantiques. Les champs sont declares ; leur consommation par tous les consommateurs d'AnalysisOptions n'est pas demontree par cette tranche. Le chemin effectivement teste est CLI -> extraire -> extraire_rapidocr -> routeur.
- `pdfexact/cli.py:51` expose ces options publiques et le bool `experimental_local_text_understanding=False` en fin de signature. `--ocr-language` alias de `--ocr-lang`, default auto ; `--ai-models-root` racine commune ; l'ancien `--layout-model-root` est aussi transmis a OCR/comprehension s'il n'y a pas de racine commune, et conserve sa priorite explicite pour le layout. Sans argument root explicite, la factory comprehension recoit None pour respecter son environnement specifique.
- **12:23, autorisation parent supplementaire** : `--experimental-local-text-understanding` seul fournit `experimental_local=True` a la factory Hubble ; default **False**, independamment de la racine commune ou du drapeau historique `--text-understanding-ai`. Signature agreee : `creer_fournisseur_comprehension_texte_ai(*,url=None,timeout=3.0,model_root=None,local_timeout=30.0,experimental_local=False)`. URL/timeout HTTP transmis sans changement ; HTTP garde sa priorite dans la factory Hubble. Son diagnostic experimental-disabled et sa qualite Qwen sont hors implementation OCR ; aucun opt-in LLM deduit du catalogue.
- Tests nouveaux exclusivement : `tests/extract/test_multilingual_ocr_routing.py`, `tests/test_cli_multilingual_ocr.py`. Aucun edit des tests/production Hubble/Lovelace/Arendt.

### Politique auto et limites explicites

Bitmap sans texte PDF : **les neuf reconnaisseurs locaux sont effectivement executes sur les memes regions detectees**, pas simplement ch lorsqu'un hint est vide. Selection **best effort** par crop : texte non vide/representable par l'alphabet, evidence de script non latin observe, puis seuils/marges heuristiques de score brut. Une lecture seulement numerique/latine du rec cyrillique ne suffit pas a le choisir. Scores CTC inter-modeles **non calibres** ; aucun score n'est converti en probabilite universelle de bonne langue. Alternatives contradictoires conservees, `ambiguous=True`, confidence source/sortie inconnue plutot qu'inventee. Catalogue incomplet ou rec invalide => warning explicite et ambiguite, pas annonce de couverture generale. Une langue explicite sans modele local compatible echoue clairement.

Evidence par region : `policy`, `ambiguous`, `calibrated=False`, `reason`, `selected_model`, `attempted_models`, `shared_detection=True`, hash des pixels du crop, `model_failures`, et candidats `{model_id, model_sha256, provider, text, raw_ctc_score, score_calibrated=False, dictionary_source, alphabet_entries, ctc_classes, scripts, alphabet_valid, script_fraction, non_latin_letters}`. `Evidence.confidence=None`. Observation et ligne/span gardent les scripts acquis sans langue devinee ; pour une page mixte chaque crop choisit son rec, pas une langue globale du document. Alternatives OCR sont des hypotheses d'une meme region, pas des peintures natives retirees ou declarees non representables.

### Executions et resultats exacts

1. `.converter/bin/python -m pytest -q tests/extract/test_multilingual_ocr_routing.py tests/test_cli_multilingual_ocr.py --tb=short` : **25 passed, 6 skipped en 7,86 s** initialement, puis **26 passed, 6 skipped en 9,39 s** apres test d'entree acquisition PDF. Lots qui se recouvrent, pas a additionner.
2. `env PDFEXACT_TEST_LOCAL_OCR=1 .converter/bin/python -m pytest -q -s tests/extract/test_multilingual_ocr_routing.py -k real_cpu --tb=short` : premier run **6 failed en 34,57 s**, tous les textes deja exacts mais rec arabe refuse pour doublons. Verification concrete : alphabet arabe officiel **747 labels, 749 classes, 31 labels repetes, zero entree vide**. Correction generique : ne pas dedupliquer/refuser des labels repetes legitimes, verifier hash exact et alignement des indices/classes. Aucun changement de poids ou du catalogue.
3. `env PDFEXACT_TEST_LOCAL_OCR=1 .converter/bin/python -m pytest -q -s tests/extract/test_multilingual_ocr_routing.py tests/test_cli_multilingual_ocr.py --tb=short` : **31 passed en 67,06 s**, six vrais smokes CPU compris, zero warning de modele. Mesures sous charge concurrente (pas benchmark controle) ci-dessous.
4. `.converter/bin/python -m pytest -q tests/extract/test_ocr_hybrid.py tests/extract/test_elements.py tests/test_cli.py tests/test_cli_text_comprehension.py --tb=short` : **118 passed, 3 failed, 2 warnings en 142,37 s**. Deux uncovered-source Word-native restent ouverts. Le troisieme etait la priorite root CLI qui masquait l'environnement comprehension specifique ; corrige par None sans root explicite, puis test concerne revalide dans le lot suivant.
5. `env PDFEXACT_TEST_LOCAL_OCR=1 .converter/bin/python -m pytest -q -s tests/extract/test_multilingual_ocr_routing.py tests/test_cli_multilingual_ocr.py tests/test_cli_text_comprehension.py -k 'not real_cpu_multilingual_synthetic' --tb=short --junitxml=results/multilingual_ocr_final_focused_20261011.xml` : **43 passed, 6 deselected en 14,86 s**. Inclut entree reelle PDF bitmap RU+ZH sans aucun texte PDF : texte exact, **Cyrl=24/Hani=10**, **6,0185 s**, inventaire 11 observations, preuves conservees. Inclut revalidation de `test_cli_missing_endpoint_announces_fallback_and_continues`. Avant ajout du flag experimental demande ensuite ; pas un fullsuite ni une validation Word-native globale.
6. `.converter/bin/python -m pytest -q tests/test_cli_multilingual_ocr.py --tb=short --junitxml=results/multilingual_ocr_cli_optin_20261011.xml` : **6 passed en 0,35 s**, session **23668 terminee**, apres ajout du flag. Tests factory mockee : racine != opt-in, False par defaut, True uniquement avec flag, URL/timeout inchanges. Integration concrete avec nouvelle factory depend de la livraison Hubble ; ne pas confondre les mocks avec une inference Qwen.

| Smoke independant PIL/groundtruth | Police locale | Secondes recognition auto | Rec selectionne | Ambigu |
| --- | --- | ---: | --- | --- |
| Русский язык и русский текст | pdfexact/fonts/DejaVuSans.ttf | 11.7219 | cyrillic v5 | oui |
| 中文汉语简体文字测试 | pdfexact/fonts/NotoSansCJKjp-Regular.ttc | 8.3492 | v6 | non |
| 中文漢語繁體文字測試 | pdfexact/fonts/NotoSansCJKjp-Regular.ttc | 9.2323 | v6 | non |
| 日本語ひらがなカタカナ | pdfexact/fonts/NotoSansJP-Regular.otf | 8.3217 | v6 | oui |
| 한국어 한글 문서 테스트 | pdfexact/fonts/NotoSansKR-Regular.otf | 9.2050 | korean v5 | non |
| Les cinq lignes dans une meme image | ces cinq polices | 10.9692 | Cyrl/v6/v6/v6/Hang par ligne | RU oui |

Les six sorties sont exactes a l'egalite du texte hors espaces ; alphabet/script/provider/candidats egalement asserts. Aucun groundtruth tire de la sortie OCR. Les latences sont des observations de ces petites images sous charge, pas un SLA ni une preuve pour tous les documents. Un test unitaire prouve une detection unique, memes objets crop vus par chaque rec et selection differente par ligne sans hint Unicode d'entree. Le test spans russe construit un vrai PDF avec police embarquee, interdit tout appel OCR et verifie le texte/scripts natifs.

### Sonde bornee du PDF utilisateur, acquisition seule

Fichier retrouve : `/home/raphael/Mes_Projets/vysi/vysi_real_corpus/pdf_native/a92188dd5fa88ea3_000177.pdf`. Pas de conclusion de langue d'apres son nom. Deux commandes `.converter/bin/python -B - <<'PY'` ont releve le texte des `page.get_text('dict')['blocks'][...]['lines'][...]['spans']` pour indices 0,1,2, puis execute exactement :

```python
document = extraire(path, pages=[0, 1, 2], text_mode="spans", ocr_language="auto",
                     layout_provider="none", strict=True)
after = "".join(element_text(item) for item in page.elements)
nonlatin = "".join(c for c in text if c.isalpha() and script_counts(c).get("Latn", 0) == 0)
```

Layout geometrique demande explicitement pour isoler l'acquisition native ; avertissement layout_ai_disabled conserve, pas preuve de layout IA. Aucun writer/plan de rendu/conversion DOCX lance par cette sonde. Premiere acquisition **3,43 s**, seconde comparaison sequence/compteurs/SHA **3,1765 s**, toutes deux terminees.

| Page | Spans PDF bruts | Scripts avant = apres | Actifs / discarded / inventaire | SHA256 sequence non latine avant = apres |
| --- | ---: | --- | --- | --- |
| 1 | 22 | Cyrl 243, Latn 23 | 8 / 0 / 52 | 91e0a9f832c8ae5476ebfba8b161ed0b6c0dd7301598e06fb14b746916be3cab |
| 2 | 59 | Cyrl 1960, Latn 104 | 18 / 0 / 135 | 11e3fca6807415fc5fc392179350b87f0fd18479cfb11351895686aefa2a8f00 |
| 3 | 55 | Cyrl 1442, Latn 29 | 4 / 0 / 111 | 5e5e45fdd50add27ff7bb83f319e9b5add5c291d61d2f7ee7de369d9f9141975 |

Sequence non latine egale (pas seulement nombres de lettres), compteurs caracteres egaux, aucun element OCR. Cette observation confirme le cyrillique reel et sa preservation native sur ces trois pages ; elle ne ferme pas la couverture source avant ecriture ni les autres pages.

### Gates ouverts et gel

1. **Couverture Word-native distincte** : `tests/test_cli.py:105` (`test_word_native_rapidocr_reste_page_exacte`) et `:133` (`test_word_native_ecrit_le_diagnostic_de_contrat`) ont echoue sur `invalid-word-native-contract: uncovered-source` pour observations OCR TextBox/Line/Span. IDs releves : `p0:ocr:TextBox:180a27c01e5e69e45d931f90`, Line `886aecc3d2e6e189abf37875`, Span `283c3308e87ebf227daa1986`, puis TextBox `eb0e6baaf2508c18d81292a5`, Line `e0c8c0bea4f3c3192d69a8ee`, Span `c5d9d2bcaabef3bdb8f09cd0`. Signales a Hubble. Aucun terminal nonrepresentable generique, aucun abandon d'inventaire ni bypass de valider_contrat_word_native pour passer ces tests. Pas de verdict que ces erreurs precedaient notre tranche sans baseline isolee equivalente. Integration parent necessaire.
2. **Auto seulement best effort** : vraies pages mixtes a lignes separees testees, pas preuve universelle ni de transcription d'un meme crop contenant simultanement Cyrl et Hani. Confiances inter-modeles non calibrees ; incertitude conservee. Pas de mesure qualite arabe/Deva/Thai/grec/tamoul/telougou : modele/alphabet/runtime acquis, qualite linguistique non demontree. Scripts hors catalogue restent non couverts, pas fausse promesse d'auto general.
3. **Compréhension Qwen** : Hubble indique qualite insuffisante (9/15 probes), parent impose experimental_local=False. Flags livres, integration factory finale et diagnostics/guards appartiennent a Hubble, pas aux smokes OCR. Une racine IA commune ne doit pas activer Qwen. Aucun resultat Qwen declare vert ici.
4. **Consommation globale** : nouveaux defaults AnalysisOptions declares mais propagation globale non prouvee ; racine commune pas encore propagee au consommateur optionnel `certifier_et_reparer` (appel CLI conserve layout_model_root historique). Les obligations initiales IR/champs/crops/consommateurs restent TODO. Pas de switch backend global.

Production OCR gelee a 12:21 UTC ; seule extension CLI experimental autorisee ensuite par le parent, terminee et testee avant ce checkpoint. Aucune session de ce worker active a 12:24. Pas d'attente de notification masquee, pas de relance ou kill d'un job vivant. Parent coordonne l'integration finale.

Empreintes du gel (SHA256 fichiers complets, incluant les edits preexistants preserves) :

```text
a33193c4bc3ab31dab540fe9d7199a50d52b945f296f202f17d136e85ddc72ba  pdfexact/extract/ocr_routing.py
72ce9fd852c240c4f2ff92f89f5ef11318ee42d1a56693f8c7d5809f01103a25  pdfexact/model_paths.py
ff1c3b9fa25ff9c9fc554398abbe6fe99bb5cd0c2b64a25edda28dd59e007c83  pdfexact/cli.py
d0a6f4dd79cc6738abeaac4348234f5632e0d077f5717b9bfd31ef2bab691b22  pdfexact/analysis/options.py
3557f6d1c0453073efec8b6b66a78f9428e378e7730a9d384ab5127ab01b7ebb  pdfexact/extract/ocr.py
a7b355a917d8b618c407f36a7084c72320b9d0061fceada62b6aea139a15e4fe  pdfexact/extract/text.py
423cc335cc829cf255c48acaf481e81712d8a1190ecd3a4998cc47b52b819446  pdfexact/extract/document.py
e253ddddcf2b9f932bfb982b2f2338ce3333c686739b87cff752d85cdcaea9e7  tests/extract/test_multilingual_ocr_routing.py
46eedbd8b632ce001838f76b163a848daa88aeb04ae58ce30966593a13063a73  tests/test_cli_multilingual_ocr.py
```

### Raccordement final du flag, 2026-10-11, 12:28 UTC

Factory Hubble relue apres publication : signature `experimental_local=False` presente, stub `experimental-disabled` sans chargement de runtime/poids, HTTP toujours prioritaire. Extension CLI minime supplementaire : le mode verbose affiche `provider.diagnostics.status` lorsqu'il est fourni, donc **experimental-disabled**, pas seulement configuree. Aucune modification du routeur OCR ni des autres producteurs depuis le gel de 12:21.

Commande terminee, session **83982**, aucun job restant de ce worker :

```bash
.converter/bin/python -m pytest -q tests/test_cli_multilingual_ocr.py --tb=short --junitxml=results/multilingual_ocr_cli_factory_20261011.xml
```

Resultat **7 passed en 0,40 s**. Le septieme test utilise la **vraie factory** Hubble, une racine locale contenant un model.bin factice, et un initialiseur local remplace par une assertion d'echec : presence de racine/bundle sans flag => zero initialisation LLM, CLI reussie, statut experimental-disabled visible. Il ne mesure ni ne certifie la qualite Qwen. Les tests de flag conservent False par defaut/True explicite et URL/timeout HTTP inchanges. Aucun ancien test Hubble modifie ni lot concurrent relance.

Empreintes actualisees pour les deux seuls fichiers modifies apres les empreintes historiques du checkpoint precedent :

```text
35dc978e94e751c385a27d40e2fef5fd2a4db26f81a5e1ed056dfc8635eef227  pdfexact/cli.py
4092b5e9180196981e337e0d9387e5b4c0a4a2a18c36eedf86c815a798f8cabf  tests/test_cli_multilingual_ocr.py
```

`git diff --check -- pdfexact/cli.py pdfexact/extract/ocr.py pdfexact/extract/text.py pdfexact/extract/document.py docs/audit_contrats_refonte_2026-10-11.md` : exit 0. Production et tests de cette tranche desormais figes. Les deux uncovered-source restent des echecs observes non resolus, a distinguer de la lecture multilingue correcte ; autres gates/TODO des matrices inchanges. Integration globale au parent, aucun fullsuite lance ici.
