# Checkpoint gele : contrats et consumer Phase 4

Date : 2026-10-11. Worker : Hubble. Destinataires : parent et Arendt.

Ce document consolide le checkpoint consumer/B1/B4 et le raccord crops. Il ne
remplace ni le plan complet, ni `docs/suivi_refonte_modules_universels.md`, dont
Arendt conserve la propriete. Ce dernier fichier n'est pas modifie ici.

## Etat et gel

- Derniere verification postpatch : **76 passed en 182.06 s, exit 0**.
- Fin et relevement des empreintes de verification : **2026-10-11 11:15:51 UTC**.
- Empreintes relues sans changement le **2026-10-11 11:22:17 UTC**.
- Aucun processus de test de ce worker encore vivant ; session 62301 terminee.
- Aucun echec restant dans les trois fichiers du dernier lot. Aucun avertissement
  affiche dans ce lot. Aucun correctif necessaire apres son execution.
- Production et tests geles. Cette publication documentaire ne lance aucun test,
  diagnostic, mapping XML ou nouvelle fonctionnalite.
- Le parent a libere Arendt pour l'unique fullsuite globale, puis cinq diagnostics
  reels. Leurs resultats ne sont pas encore etablis par ce checkpoint.
- **Pas de succes global, pas de Phase 4 terminee.** Les annonces anterieures sur
  les phases 0-3 restent soumises aux gates d'integration du plan complet.

References : `docs/plan_refonte_modules_universels_reconstruction.md` et
`docs/audit_contrats_refonte_2026-10-11.md`.

## Perimetre et responsabilites

Fichiers de production touches au cours des tranches de ce worker :

- `pdfexact/render/render_plan.py`
- `pdfexact/render/word_native_rewriter.py`
- `pdfexact/render/drawing.py` : raccord des overrides z planifies ; la totalite
  de son diff preexistant n'est pas attribuee a ce worker.
- `pdfexact/render/bbox_debug.py`
- `pdfexact/render/reflow.py`
- `pdfexact/analysis/semantic.py`
- `pdfexact/analysis/provenance.py`
- `pdfexact/analysis/decisions.py`
- `pdfexact/analysis/text_geometry.py` : raccord au resolver partage de Pascal.
- Nouveaux modules : `pdfexact/render/text_backend.py`, `text_runs.py`,
  `orientation_backend.py`, `geometry_adapter.py`.

Tests ajoutes : `tests/render/test_planned_materialization.py`,
`tests/analysis/test_plan_source_coverage.py`, `test_text_geometry.py`,
`test_plan_media_crop.py`. Tests ajustes :
`tests/render/test_word_native_rewriter.py` (IDs canoniques),
`tests/analysis/test_universal_contracts.py` et `test_paragraph_segmentation.py`.

La derniere tranche crop consumer ne modifie que `render_plan.py`,
`test_plan_media_crop.py` et `test_plan_source_coverage.py`.

Pascal possede la scene/IR, l'acquisition, les options/geometries partagees et le
producteur de preuve crops. Lovelace possede `package.py`/`native_contract.py` et
l'enforcement avant ZIP. Aucun edit de ces fichiers, de `docx_writer.py`, du CLI
ou de `scripts/reconstruct_bbox_native.py` n'est attribue a ce worker. Aucun
metier ni writer historique n'a ete supprime. Les modifications preexistantes
du worktree sont conservees.

## API et contrats stabilises dans le lot

### Plan et materialisation

`RenderPlan.validate(document=None) -> list[str]` est une validation pure.
`instructions_for_page(page_index)` exige un schedule present ; une absence
leve `missing-materialization-schedule`. Les cles utilisent le vrai `page.index`.

Les structures compilees sont `AnchorSpec`, `RenderInstruction`,
`Materialization(fragments)`, `PlannedElement` et
`SourceCoverage(target_ids, relationship, reason)`. `RenderPlan` conserve
`source_inventory`, `source_coverage`, `instructions_by_page`, les elements
prepares et `media_snapshot`.

Les builders disponibles sont `build_render_plan`, `build_document_render_plan`,
`build_page_render_plan(..., polices=None, source_inventory=None, document=None)`
et `build_scene_render_plan(..., media=None)`. La compilation copie les entrees
et options ; un document fourni modifie apres compilation est rejete par le
contrat, sans reconstruction silencieuse. La validation sans document utilise
notamment le snapshot des medias ; avec document, les medias courants sont verifies.

Le plan stocke avant emission : fragments source paint, ordre total stable,
composition de paragraphe avec les metriques de `document.polices`, geometrie,
orientation normalisee, kind, container et anchor. `TextInstructions` conserve
composition, geometry, orientation, flow/frame/native runs, slices et vertical
lines. Le consumer garde les decisions flow/photo/DML etablies, sans rerouter
tous les objets vers un meme mode.

Les egalites paint suivent l'ordinal d'acquisition puis la subsequence de fragment,
pas le tri geometrique ou un hash d'ID. Les barriers paint, alpha 0, z 0, angles,
polices natives, page selectionnee 3 et `LinkZone` ont des tests dedies. Les
primitives XML et la propriete des sections/font parts restent preservees.

### Factory canonique commune

`_record_for_legacy` delegue a
`scene.element_record_from_legacy(element, page_index, *, document=None)`.
Il n'introduit pas un second contrat d'identite ou un adaptateur lossy.

API amont de Pascal consommee/coordonnees :

```text
ensure_source_identity(element, page_index, *, source_kind=None,
                       source_pdf_id="", source_token=None)
capture_source_observations(page, elements, *, source_kind=None)
record_source_transformation(page, sources, outputs, reason_code, **details)
scene_from_legacy_document(document)
analysis.geometry.resolve_text_orientation(element) -> dict
```

Le resolver partage conserve parent, angle dirige, orientation et conflits
observes des lignes. `text_geometry` s'y raccorde sans cycle d'import et sans
reduction modulo 180 qui effacerait une orientation dirigee.

### B1 : couverture et validation

Le contrat verifie l'inventaire actif, ecarte et ses observations enfants, les
decisions, raisons, instructions et relations source/cible. Un plan vide pour
un document non vide echoue. La duplication exige une equivalence source et un
gagnant conserves ; une transformation doit verifier ce qu'elle preserve.
Un warning vide, une union de bbox ou un blanket `legacy-filtered` ne constituent
pas une couverture terminale. L'etat non representable exige raison et preuve.

L'enforcement pre-ZIP et le respect du plan fourni relevent du raccord Lovelace,
pas d'une modification locale de package. Son checkpoint rapporte par le parent
est 183 passed, 1 skipped ; ce nombre n'est ni reproduit ni recompte ici.

### B4 : frontieres, options, marqueurs et purete

`preserve_line_boundaries='always'` et la confiance minimale survivent aux passes,
y compris frames/colonnes. L'override explicite dans `extra` suit une politique
coherente. La branche orientation precede la politique `always` : vertical et
oblique restent natifs editables, avec leurs angles. Zero n'est pas remplace par
une confiance par defaut ; `None` reste inconnu et traite conservativement.

Les decisions portent raisons non vides, bbox/angle/z attendus, verification et
`safe_reflow` explicites. Un fallback local interdit reste interdit ; une vraie
image source n'est pas un fallback. `fallback_mode=None` reste legitime si aucun
fallback n'est requis.

Le regroupement des listes copie le corps, conserve les IDs source du marqueur
et du corps ainsi que le marqueur materialisable. `prepare_document_elements`
fait un deepcopy des pages : les annotations des passes ne mutent plus l'appelant,
ses styles ou ses coordonnees. Le mode explicitement in-place conserve son contrat.

Les deux assertions historiques ont ete remplacees par des assertions fortes :
inventaire complet actif + observations raw lignes/spans ; raisons et historique
de filtrage conserves pour les ecartes. Un ecarte reste detecte/non terminal tant
qu'aucune relation verifiee ne justifie sa couverture, sans fabriquer un warning.

## Raccord de preuve collective crops

Schema reconnu : **`media-crop-partition-v1`**, evidence
`media-crop-partition`, details `proof`, methode **`source-media-pixel-crop`**.
Helper producteur de Pascal :

```python
verify_media_crop_partition(source, outputs, media, proof,
                            *, require_verified=True) -> list[str]
```

`_media_crop_partition_errors` exige une source IMAGE/RASTER_COMPOSITE avec son
snapshot raw, une preuve parent correspondante et non ambigue par sortie, et une
preuve coherente pour toutes les sorties schedulees. Il appelle ce helper avec
la source raw, toutes ces sorties et les vrais medias. Les schemas malformes et
les preuves absentes echouent fermement.

La preuve contient source et sorties avec IDs, media refs, hashes payload/RGBA,
dimensions, modes, bornes pixel et geometries. Les booleens verified et reasons
ne suffisent jamais. Le helper recalcule les hashes et pixels, verifie partition
complete sans trou/chevauchement, IDs et lineage, geometries/transforms,
alpha/opacity/clip/z et metadonnees de composition, puis recompose le RGBA sans
alpha blending et compare a la source effective.

Le plan marque cette relation `transformed / source-media-crop-partition`, pas
un faux remplacement raster. Les crops d'une vraie image restent possibles
avec fallback raster local interdit. Les geometries non prouvables ne recoivent
pas de flag artificiel : conservation source et raison explicite cote producteur.

Preuve reelle incluse au dernier lot :
`test_real_native_extraction_to_plan_collectively_proves_twenty_four_tiles`,
dans `tests/extract/test_collective_media_crop_contract.py`, passe sans deselection.
Elle exerce extraction native, securisation, parent raw et **une image vers
24 tuiles**, puis producteur et `plan.validate(document)` sans erreur.

Les tests adversaires couvrent absence, bool seul, gap, overlap, alpha, clip, z,
transform, payload, payload rehashe et source payload. Ils couvrent aussi medias
courants contre snapshot, purete de validation, et les quatre builders.

### Limite raster distincte et impact attendu

Une trace **`source-page-region-render` n'est pas une verification pixel de la
sortie**. `_raster_replacement_traceable` peut etablir la relation structurelle,
mais le plan conserve `unverified-raster-replacement` pour un remplacement source
non mesure, meme si un flag pretend le contraire. Une relation absente ajoute
son erreur de tracabilite. Une partition bitmap valide ne prouve pas retroactivement
le remplacement vectoriel ou textuel ayant produit ce bitmap.

L'extraction native reelle une image/24 tuiles est prouvee par le test ci-dessus.
Les futurs diagnostics utilisant une capture de region de page non mesuree
peuvent legitimement remonter cette limite ; ne pas relacher le gate ni declarer
le document globalement couvert sur la seule base d'une capture ou d'une bbox.
Les cinq conversions reelles d'Arendt restent necessaires pour quantifier cet impact.

## Executions et regressions

Ces comptes concernent des lots et des etats differents : **ne pas les additionner**.
La baseline historique Arendt 792 passed, 1 skipped appartient a un autre etat
et n'est pas reproduite ici.

1. RED initial : le fichier `tests/render/test_planned_materialization.py`
   echouait sur six repros : late planning, paint barriers, z 0/alpha 0,
   page selectionnee 3, LinkZone et instructions absentes. Le fichier a ensuite
   ete etendu ; ce compte n'est pas celui de sa taille finale.
2. Lot elargi avant fixup : **301 passed, 5 failed, 6 warnings en 78.79 s**.
   Un echec etait la collision d'ID line:0 entre pages, corrigee par Pascal.
   Les quatre autres etaient deux variantes de mutation wrapper et les deux
   assertions historiques d'inventaire/etat detecte. Tous sont resolus dans
   le lot vert elargi suivant. Aucune regression de ce lot ne reste masquee.
3. Resolver : **3 failed, 3 passed** en RED ; recheck quatre anciens echecs
   + six cas resolver : **10 passed, 2 warnings en 8.68 s**. Les imports dans
   les deux ordres ont aussi ete verifies en interpreteurs neufs.
4. Lot elargi apres fixup : **319 passed, 6 warnings en 80.47 s, exit 0**.
   Les avertissements comprennent les replis attendus de partitions IA invalides
   et la deprecation pkg_resources. Ce lot **precede** le patch consumer crops.
5. RED crops : **23 failed en 92.84 s**, puis patch consumer et gel demande.
6. Verification postpatch bornee : **76 passed en 182.06 s, exit 0**, sans
   avertissement affiche ni correction apres run. Ce dernier lot est la preuve
   courante du raccord crops, pas une nouvelle fullsuite.

Commandes des lots de reference, sans relance lors de cette publication :

```sh
# RED initial
.converter/bin/python -B -m pytest -q -p no:cacheprovider tests/render/test_planned_materialization.py

# Lot elargi : 301/5 avant fixup, puis 319 GREEN apres fixup
.converter/bin/python -B -m pytest -q -p no:cacheprovider tests/analysis tests/render/test_b1_package_source_gate.py tests/render/test_planned_materialization.py tests/render/test_word_native_rewriter.py tests/render/test_source_paint_layers.py tests/render/test_native_paragraph_pages.py tests/render/test_bbox_font_propagation.py tests/extract/test_directed_text_angles.py

# RED crop consumer
.converter/bin/python -B -m pytest -q -p no:cacheprovider tests/analysis/test_plan_media_crop.py tests/analysis/test_plan_source_coverage.py::test_raster_capture_trace_does_not_prove_output_pixel_verification

# Dernier lot postpatch, y compris real_native_extraction_to_plan
.converter/bin/python -B -m pytest -q -p no:cacheprovider tests/analysis/test_plan_media_crop.py tests/extract/test_collective_media_crop_contract.py tests/analysis/test_plan_source_coverage.py
```

`git diff --check` etait propre au checkpoint. Il ne remplace pas les tests des
fichiers nouveaux/non suivis. Aucun processus vivant n'a ete redemarre.

## Gates ouverts, non optionnels

- **Mapping source vers XML absent** : `RewriteResult` expose XML, diagnostics et
  numbering, pas de mapping public. Le gate Phase 4 impose pour chaque fragment
  et objet emis les IDs plan/source, page, mode et vrai locator XML, enregistres
  pendant la materialisation. Aucun rematching heuristique texte/bbox admissible.
  Cette fonctionnalite n'est pas commencee dans ce cycle gele.
- **Provided-plan consumers != tous les entrypoints par defaut** : les consumers
  rewriter/bbox testes valident et consomment les instructions fournies sans
  appels semantic/grouping/planning tardifs. Les wrappers sans plan et les
  appels independants peuvent encore construire plusieurs plans.
- `_shape_should_overlay`, `_flow_runs` avec defaut `None`, helpers metier et
  writers legacy restent des points de migration, pas une isolation globale
  terminee. La purete de tous les backends n'est pas declaree.
- Les routes package/facade/docx_writer/CLI et les trois stages bbox du script
  doivent partager l'unique plan precalcule. Ce script est hors scope worker ;
  un raccord d'un autre owner n'est pas une preuve end-to-end de notre lot.
- `build_scene_render_plan` accepte les medias mais pas encore un contexte
  document.polices equivalent au builder document : limite d'integration fonts.
- Les remplacements raster non mesures restent unverified comme indique plus
  haut. Le support des crops prouves ne ferme pas ce gate distinct.
- Isolation complete texte/images/tables/formes/fonts, gates de compatibilite
  Word/LibreOffice/WPS, checks visuels reels et tous autres gates du plan restent
  a prouver. Aucun scope global n'est reduit par ce checkpoint.

Le parent coordonne le gel et les prochains scopes apres le rapport Arendt.
Ce worker reste disponible pour des echecs reproduits, sans edit spontane.

## Registre SHA-256 du snapshot

Relu le 2026-10-11 a 11:22:17 UTC. Les trois derniers fichiers sont des dependances
producteur Pascal, pas des edits consumer. Les empreintes identifient le contenu
du worktree sale, pas un commit ni une certification globale.

```text
7314a240d348a1ce4362198f1af2b8d12097008a36a77438bd8c59c3a4eb655a  pdfexact/render/render_plan.py
212e4560a0503d17a600ade17c405838b6f3cbbdf561c28d5c752fe94d9c2de3  pdfexact/render/word_native_rewriter.py
bbad7f825dd13d6e86892905b71ad9c8a01068bb7fe1a6edfbae7ca3ab7d88ec  pdfexact/render/drawing.py
6eb6ecc23ab64e843cb9d0bb31976df867eaebb60e68712836a3aa525fc2b377  pdfexact/render/bbox_debug.py
813c672c431d41a3bbc7f1dceaaf2a57a21cc9e054012006097cd7f16bc87738  pdfexact/render/reflow.py
61208134f1d708d7d666a2175a9ea28cf919ba0d3a71d9df54763e70c6ca1c5e  pdfexact/render/text_backend.py
9bd17476b4fcd2c26eaf1d72da657cdf950cffd32e56d6f2a65055922975e54d  pdfexact/render/text_runs.py
98817740d5d609f514345e2eb1a0038281e1231d64da8845f27b0efce6df3934  pdfexact/render/orientation_backend.py
e17c7f8062301547eed0cc0e66ec5a58e1876f9a81aea11e57fb4a600365fc68  pdfexact/render/geometry_adapter.py
c0a08f8c81fbf9cac5e91a4aa2df3a2d7eaffa9bd0fa02281430dc7c9d57a2e3  pdfexact/analysis/semantic.py
972d14f75a0a5cb49827442bf99fb4b93e065f1b948fd857464d6ed03afa070d  pdfexact/analysis/provenance.py
01b8d25d5a32e98341fd8e48228ad53944ce7080b264b62d167fd7bfdb263a86  pdfexact/analysis/decisions.py
d7059a322eac1a02ac8a2b874a5205d280067f1f8d4a6fce4f8fc7c1c6f92399  pdfexact/analysis/text_geometry.py
b69b8b5581cc4c6d23da7e55e5167e0ccf63c16de3b3dd289debb972db5bb4c4  tests/render/test_planned_materialization.py
343947314b46f1544604b11a7564226346fad5502a826077da0a41e8a2bf42a2  tests/analysis/test_plan_source_coverage.py
56d8755460222d7ecea6b7e4490acb53cdb4229bf2e8890392650b44f3aa1f35  tests/analysis/test_plan_media_crop.py
f8cbf39db46479c467373dbacbc51e909bc5bdc90e97417434e88c8e12714b34  tests/analysis/test_text_geometry.py
d5676daa64f327d4cfca602177f8f2f3dcbbfb636fdbbb623ce7bb7f7b778a1a  tests/analysis/test_paragraph_segmentation.py
93adf25ef49b47e7e15a5dc77e49079ddf03a0f6394d7a6da41ebdaf8cfeb24b  tests/analysis/test_universal_contracts.py
3a594775480887f13f51b876f92368b56542f344661f08232b6d089be51c5693  pdfexact/fallback/rasterize.py
1cb3144fb12299b6b19a75c0c5c5ca39064d0ee1654df5974abf7b886d596846  pdfexact/extract/document.py
8d1511d6f0f8a45b7d9d299cdfc3089abdf0fd9c636ac15ead6a02619ecace99  tests/extract/test_collective_media_crop_contract.py
```
