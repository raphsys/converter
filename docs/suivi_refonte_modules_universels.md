# Suivi persistant de la refonte des modules universels

## Dernier Checkpoint : FAIL Visuel Page 3

Le parent a réellement comparé source/contrôle page3 et confirme un **FAIL
visuel**, sans qualification : puces native-list sur baseline séparée du
texte, espacement excessif, chevauchement dans les zones milieu/basse.
Observation du parent sur les vues source/contrôle diagnostiques, pas une
revue indépendante ou un rendu production exécuté par ce worker.
Preuve de réception :
`results/reprise_universelle_20261020/visual_page3_native_list_failure_parent.md`.

- [x] Sauvegarder le constat visuel négatif réel page3 ; réussite d'import ContentTypes ou compte376/376 ne valide pas la mise en page.
- [ ] APRÈS gel Ohm courant, ouvrir diagnostic général du producteur native-list sur baseline/espacement/chevauchement ; cause et correction non établies, aucun élargissement du patch Ohm ni exception PDF autorisés par ce constat.
- [ ] Recevoir diagnostic, scope/GO puis preuves de correction et nouveau contrôle visuel ; production CLI/LO final, sourceXML/éditabilité/corpus/benchmark/fullgoal restent ouverts.

Thread docs arrêté à la demande du parent après sauvegarde ; aucun job propre,
test/runtime/LO/NN ou changement production. Reprise documentaire ultérieure,
objectif universel non clôturé.

## Point Courant : LO Isolé Sans Contrôle

**Causalité désormais établie par réduction contrôlée, après les essais
ci-dessous :** `results/lo_import_reduction_20261020_20261020T155513Z/checkpoint.md`
et `continuation_checkpoint.md`. Sur LO25.2.3.2, préfixes lexicaux ns0 dans
`[Content_Types].xml` provoquent le refus ; namespace par défaut racine ET
enfants importe la copie RU complète en3 pages Letter. Arbres XML expansés
identiques, toutes autres parts byte-identiques, aucune donnée source retirée.
Sens inverse sur un contrôle minimal auparavant valide : default→ns0 échoue.
Contrôles racine ns0 seule et enfants ns0 seuls échouent également. Ce n'est
pas une exception à un PDF, ni l'affirmation que ns0 serait illégal en XML.

Quatre probes terminés, deux slots non utilisés, handles27541/19952/67423/
56956 et enfants clos selon checkpoints. La copie diagnostique ouvrable n'est
PAS un correctif production ni le contrôle du DOCX original inchangé. Aucune
routine interne de l'importeur identifiée. Les settings/fontTable/document
restent byte-identiques dans la copie qui s'ouvre : leurs défauts XSD sont
réels mais distincts de la cause d'import isolée, pas déclarés inoffensifs.
Réception bornée : `results/reprise_universelle_20261020/lo_content_types_causality_confirmed.md`.

- [x] Recevoir la preuve causale bidirectionnelle et les deux contrôles de placement des préfixes, sans autre part/donnée modifiée ; quatre probes clos, deux slots non consommés. Aucun LO/test/NN de ce worker.
- [x] Consigner GO Ohm PREMIER correctif général ContentTypes, TDD/sérialisation locale au producteur, sans enregistrement namespace global ; settings/fonts/pPr/fitText restent des défauts séparés et leurs tâches ouvertes.
- [ ] Recevoir RED puis correctif/tests ciblés ContentTypes : racine ET enfants dans namespace par défaut, même arbre expansé/Default/Override/contenus, état global de namespaces et autres parts inchangés ; aucun cas par nom/ID de PDF/DOCX.
- [ ] Recevoir gel/revue/SHA et sémantiques/gardes inchangés, puis GO/succès réel CLI production et LO du nouveau DOCX ; tests ou copie diagnostique ne valent pas cette preuve finale.
- [ ] Recevoir PNG diagnostiques source/contrôle1–3 de l'acteur autorisé, avec verdict explicitement diagnostique ; validation visuelle finale, mapping sourceXML/editabilité/corpus/benchmark19 toujours ouverts.

État HISTORIQUE avant preuve causale : checkpoint relu
`results/lo_env_isolated_20261020_20261020T153514Z/checkpoint.md`.
Deux essais autorisés CLOS : sandbox34133 LO1/helper1, stdout/stderr vides ;
élévation42858 LO0/helper1 avec `Error: source file could not be loaded`,
aucun PDF dans les deux cas. Fin15:37:55, owned_remaining vide selon summary,
pas de timeout ni de nouvel essai. Dconf a disparu avec l'isolation, sans
établir la cause du premier53044 ; cause d'import source encore inconnue,
ni corruption produit ni refus de permission prouvés. L'acteur runtime mène
ce diagnostic séparément. Succès RU CLI0/package/couverture376/376 inchangé,
gel946 préservé ; aucun contrôle/PNG/visuel réussi.

## Correctifs OOXML Producteurs : GO TDD Borné

Rapport indépendant relu, défauts XSD séparés de la cause ContentTypes
établie ensuite ci-dessus :
`results/lo_package_review_20261020_20261020T155114Z/REPORT.md` et `evidence.json`.
Des défauts de CONFORMITÉ sont établis, pas leur causalité sur le refus LO.
Le témoin connu bon s'ouvre dans le même environnement isolé
(`results/lo_load_readonly_diagnosis_20261020_20261020T155010Z/control/known_good.pdf`) ;
cela exclut une indisponibilité générale déduite de ces essais, sans valider
l'import/rendu RU. Le validateur projet parse déjà tous les XML et relations,
mais ne vérifie pas les séquences XSD : son retour `[]` ne contredit donc pas
les défauts ci-dessous et ne signifie pas conformité OOXML globale.

| Producteur | Défaut établi sur l'artefact réel | Contrat à corriger pour toutes sources |
| --- | --- | --- |
| `package.py:107/111` | Flags `CT_Compat` après compatSetting ; `useWord2013TrackBottomHyphenation` émis comme élément non déclaré | Flags avant compatSetting ; option encodée comme compatSetting name/uri/val sans perte de politique |
| `package.py:236` | Faces Arial regular/italic/bold hors séquence `CT_Font` | Ordre regular/bold/italic/bold-italic, payloads/keys/relations/styles inchangés |
| `text_backend.py:81/96/133/135/141` |105/159 pPr invalides : spacing après ind, keepLines après jc | Respecter séquence des propriétés en conservant valeurs, texte, styles, géométrie et paint |
| `text_backend.py:94` | Deux fitText placés sous pPr, porteur interdit | Encodage au porteur valide sans suppression silencieuse de l'effet/valeur fit |

Les deux fitText sont INCLUS dans105/159, pas deux défauts supplémentaires à
ajouter au compteur. Cas général de producteurs OOXML, aucune branche par
nom/ID PDF/DOCX, police observée ou langue. Les counts valident un diagnostic,
pas une correction ni l'import LO. Le rapport ne certifie pas tout le WPS.

- [x] Consigner GO parent Ohm `01a15a02-3da5-7962-8d21-d84d265c4b49`, production SEULEMENT `pdfexact/render/package.py` + `pdfexact/render/text_backend.py` et tests ciblés ; rapport reçu, correction/résultats encore attendus.
- [ ] Recevoir checkpoint RED ciblé indépendant sur XML réellement émis : ordre/encodage compat, combinaisons de faces font, ordre pPr et fitText ; assertions de schéma/structure explicites, géométries/polices/valeurs variées, sans exception de fichier et sans LO/NN.
- [ ] Recevoir correction des deux producteurs gardant les sémantiques : ne pas supprimer flag, face, fitText ou propriété pour faire passer le schéma ; mêmes texte/styles/tailles/sections/relations/medias/font payloads/paint et sourcecoverage, changements limités aux représentations conformes nécessaires.
- [ ] Recevoir tests de non-régression body/metadata/ordre et conformité des parties produites, résultats focus RED→GREEN/commandes/JUnit/exit/handles clos ; lots connectés seulement sur périmètre approuvé, aucune somme avec946 ni nouveau succès runtime déduit.
- [ ] Recevoir gel/SHA avant-après/revue Ohm : deux sources seules, tests ciblés listés, gardes source/IR/Scene/OCR/digests/signatures et perf inchangés, originaux/source/modèles non modifiés ; aucun élargissement de validateur pour masquer un défaut.
- [x] Recevoir séparément le résultat discriminant runtime ContentTypes : quatre probes dont inversion minimale et racine/enfants seuls, cause d'import ns0 isolée ; pas de preuve que les autres défauts XSD expliquaient ce refus.
- [ ] Recevoir un GO runtime post-fix et vraie sortie production/LO/visuel ; aucun résultat final ou mapping sourceXML présumé depuis les tests schéma ou le PDF d'une copie diagnostique.

Worker docs/evidence uniquement : aucun test/NN/LO, édition production ou
réécriture des DOCX originaux. Les tâches s'appliquent à TOUS les producteurs/
sources concernés ; diagnostic sur l'exemple RU n'autorise aucune exception.

SourceRaster1 vérifié par le parent comme record non textuel : placement/
composition image, kind image, xrefs109/111, texte/spans vides. Comptes
rapportés46 TextBox natifs dont22 non vides et3 images. Ce record ne démontre
PAS une violation texte-raster ; pas de qualification de toutes les images,
du rendu/fonts ou de l'éditabilité globale déduite de ce constat borné.

- [x] Consigner l'échec réel LO53044/exit1 sans contrôle et le diagnostic borné stderr dconf readonly, sans l'ériger en cause unique ni en bug produit établi ; CLI0/376 sourcecoverage et gel946 préservés.
- [x] Consigner SourceRaster1 comme image non textuelle vérifiée dans ce scope, pas violation texte-raster ; aucune exception de contrat ou requalification globale.
- [x] Consigner nouveau GO parent à l'acteur runtime : helper LO EXISTANT, environnement isolé HOME/XDG config/cache/runtime/tmp en répertoires700, GSETTINGS_BACKEND=memory/VCLsvp ;120s UNIQUEMENT LO. Si échec de permission sandbox, un seul essai élevé sur le même rendu local propre/isolé via revue outil, pas relance arbitraire ni NN.
- [x] Recevoir clôture des deux essais LO isolés34133/42858 et leur échec sans PDF ; helper correctement en erreur même lorsque LO renvoie0. Douze entrées de sceau vérifiées en lecture seule dans `results/reprise_universelle_20261020/lo_isolated_closed_evidence_receipt.json`, aucune exécution LO/test/NN de ce worker.
- [ ] Recevoir contrôle LO et vues de la vraie sortie PRODUCTION après correctif Ohm/gel/GO ; diagnostic causal ContentTypes désormais acquis, PNG de copie diagnostique non promus validation visuelle finale.

Ce point actualise l'étape LO des sections ci-dessous, pas le succès CLI
ni les faits historiques. Aucun exec LO/test/NN/benchmark, job propre ou
changement source/test par ce worker. Objectif complet toujours ACTIF.

Audit documentaire actuel contre le plan original sections2-3/4-22/23-24 :
`results/reprise_universelle_20261020/readiness_after_lo_isolation_20261020.md`.
Priorités non cochées : import LO/contrôle réel ; mapping per-source XML ;
matrice fonction/appelant/options et B1-B4 ; fonts/fit/profils lecteurs ; audit
et réparation locale ; golden12×7 ; qualité19 sur GO ; gel final/tests et
suppression contrôlée en dernier. Ce sont des preuves manquantes au fullgoal,
pas des bugs tous reproduits aujourd'hui. Les anciennes cases runtime
satisfaites sont réconciliées dans le détail sans clôturer ces gates globales.

## Point Courant : RU Direct Réussi

Succès E2E courant reçu du parent : **OCR2 réel2 GREEN/72.98s**, puis vraie
CLI RU DIRECT **exit0**, validateur package projet `[]` (pas conformité XSD globale), couverture source
**376/376 :63 retained,313 transformed**. Source/code164 chemins et33 modèles
inchangés selon preuves parent. C'est un vrai succès CLI/package/couverture
dans ce scope, ce n'est plus un échec runtime RU ; aucune preuve globale source→XML,
NativeEditability ou qualité modèle n'en est déduite. Réception documentaire :
`results/reprise_universelle_20261020/ru3_cli_success_parent.md`.

**Gate PDF corrigée, sans changement produit :** `annotate_pdf_bboxes`
conserve CORRECTEMENT les17 pages du PDF source et annote les seules pages
sélectionnées1–3. Pages4–17 non touchées vérifiées par l'acteur selon parent.
L'ancienne exigence « PDF bboxes3p » était une hypothèse erronée de la gate,
PAS un bug produit ni un correctif à apporter. Ne pas sous-ensembler/muter
le PDF pour satisfaire cette ancienne hypothèse. Les mentions historiques
« PDF+DOCX valides3p » plus bas sont remplacées par cette clarification :
PDF bboxes17 pages source conservées, DOCX natif sur la sélection1–3.

- [x] Recevoir OCR2 courant2 GREEN/72.98s et vrai RU DIRECT0, package OOXML sans erreur et couverture376/376 (63/313), code/source164 chemins et33 modèles stables ; preuves rapportées par le parent, pas un run/vérification supplémentaire de ce worker.
- [x] Consigner la gate correcte PDF bboxes17 pages/annotations1–3/pages4–17 intactes ; aucune correction code/PDF ni nouvelle extraction/plan demandée. Succès produit réel, pas succès inféré d'un compteur unitaire.
- [ ] Recevoir le contrôle LO sur le MÊME DOCX natif, profil neuf isolé/limite120s LO SEULE, contrôle des3 pages Letter612×792 et six PNG source1–3/contrôle1–3 ; GO parent donné, résultat/views non reçus ici. Contrôle visuel/fonts encore en attente, aucune nouvelle CLI ou réécriture produit.
- [ ] Prouver source→XML/NativeEditability, rendu/fonts/lecteurs et corpus/fullgoal ; nativeEligibility et couverture source ne suffisent pas. Qwen qualité UNQUALIFIED, benchmark19 toujours HOLD après la chaîne réelle/autorisation, aucune clôture globale.

Liens utilisateur PDF/DOCX déjà fournis en commentaire selon parent, aucun
chemin de produit reconstitué ici. Toutes les anciennes époques abort/137/
neuf refus restent vraies et conservées avant ce succès courant. Worker
docs/evidence ONLY : aucun exec NN/LO/test/benchmark ni changement source.

## Point Courant : Gel Producteur 946

Retour parent après longue attente : gel FINAL Hume lu/accepté,
`results/parent_lineage_compile_order_fix_20261020/checkpoint.md`,
**946 GREEN,7 deselected,130.96s, handle51033 clos**. Les882 précédents,
43 ciblés (géométries égales/non monotones incluses) et21 word-native sont
inclus, pas ajoutés aux946 ou à d'autres gels. Préfixes SHA annoncés :
segmentation3068ae / render_plan d4da9d ; complets dans le checkpoint original,
aucune expansion inventée ni vérification supplémentaire de ce worker.

Le parent accepte `TypedParentAncestry` canonique et compilation topologique
selon l'ordre réel sourceRowOrder, PAS un tri géométrique seul ; pile paint
ancrée conservée. Causes réelles précédentes : ancestry du parent acquis
perdue après subdivision des vues de frames et priorité mode/anchors+flow
altérant l'ordre. Gardes/digests/signatures et prédicats/snapshots de six autres
modules inchangés ; patch perf copies de collection six lignes intact.
Acceptation productrice/source-contract bornée, pas preuve NativeXML/lecteur/
corpus/native editability. Ce point remplace les états d'attente avant946
ci-dessous, sans réécrire les époques historiques.

- [x] Consigner acceptation parent du gel producteur946 et ses limites : `results/reprise_universelle_20261020/parent_lineage_order_946_acceptance_parent.md` ; réception parent seulement, aucun exec ni source/test edit de ce worker docs/evidence.
- [x] Consigner GO Averroes E2E conditionnel POST946 :2 vrais OCR verts/closes -> nouvelle RU DIRECT3p/CPU100dpi sans observer/runpy/profiling/replan/deadline globale CLI -> SI0/PDF+DOCX valides3p/clos, helper LO existant/profil isolé/120s LO SEULE -> six PNG source/contrôle.
- [x] Recevoir la partie OCR2/RU réelle POST946 :22729 clos0/2 GREEN72.98s,24520 clos0/DOCX+PDF présents/package valide/376 sources couvertes ; `results/e2e_current_parents_order_20261020_20261020T151652Z/checkpoint.md`. PDF bboxes17 pages source est correct, pas une sortie3p à fabriquer.
- [ ] Compléter la partie contrôle/views de cette chaîne : essais LO clos sans PDF, aucune preuve visuelle/lecteur ; benchmark19 HOLD, Qwen/sourceXML/native editability/audits/corpus/fonts/fullgoal ouverts.

Les neuf refus réels AVANT ce gel restent vrais et archivés ; capture42865
close/exit1, document109MB/plan38MB/failed-sources826KB restent dans
`results/ru3_erroronly_capture_20261020_20261020T133819Z/failure/`, références
SHA d'origine sans duplication147MB. Ancien46279/1200s wrapper non autorisé et
43536/137 avant ordre SIGINT/cause UNKNOWN sont distincts ; aucun signal parent
réalisé ni OOM certifié pour137. Aucun propre job, exec NN/LO/test/benchmark
ou changement production de ce worker. Objectif universel ACTIF, non terminé.

Ce fichier est le journal durable de l’implémentation du plan
`docs/plan_refonte_modules_universels_reconstruction.md`. Il doit être mis à jour
après chaque étape significative, avec les fichiers touchés, les tests exécutés et
les régressions éventuelles.

## État global

- **Statut :** objectif universel complet ACTIF et inchangé. Hume882/perf et OCR2 réel POST-perf2 GREEN/108.27s restent acceptés. Capture error-only réelle42865 close/exit1, exports scellés selon parent ; causes des neuf parents et défaut d'ordre d'émission identifiés sur le vrai Plan+IR. GO Hume production borné aux producteurs ancestry `_ligne_unit` et ordre `_compile_page`, gardes/digests/signatures inchangés, patch perf six lignes conservé. RED ciblés/connectés à recevoir ; aucun nouveau GO runtime NN/LO/benchmark.
- **Objectif :** un pipeline universel, un contrat de scène, une décision de rendu, un backend DOCX principal et un audit par élément.
- **Règle :** aucune suppression de code historique avant migration, comparaison et tests.
- **Dernière mise à jour :** 2026-10-20, capture réelle `results/ru3_erroronly_capture_20261020_20261020T133819Z/failure/`, handle42865 CLOS/exit1/export scellé confirmé par le parent. Document109MB/plan38MB/failed-sources826KB conservés sur place, références SHA de la capture originale à utiliser, aucune duplication147MB ni SHA inventé/vérifié par ce worker. Anciennes époques46279/1200s wrapper et43536/137 cause UNKNOWN restent distinctes.
- **Étape active :** correctif producteur Hume autorisé SEULEMENT dans text_segmentation (ancestry via registre typé) et render_plan `_compile_page` (ordre d'émission). `_ligne_unit` perd l'ID du parent acquis après subdivision en vues de frames ; `_compile_page` concatène anchors puis flow et émet les lignes DML27–30 avant0–26. RED ciblés puis unités connectées/gel/gardes stricts requis avant prochain GO réel, pas acquis maintenant. NN/LO/PNG/corpus/benchmark19 HOLD, aucun PDF/DOCX russe final. Worker docs uniquement, sans exec ni changement production/tests.
- **Relais runtime parent :** GO CLI DIRECTE EXACTE donné à Averroes, sans profiler/runpy/observateur/wrapper personnalisé ni deadline globale. Démarrage/résultat de cette nouvelle époque non déduits ici. Ce worker reste docs ONLY, ne relance aucun runtime/LO/benchmark et ne modifie pas le gel code/tests. Priorité aux vrais PDF/DOCX utilisateur, catalogue et manifeste réellement écrits ; scène/plan absents restent déclarés absents. L'interruption46279 relève du harness ajouté, pas d'un bug production CPU/IA démontré ;607 et les deux vrais OCR restent acceptés.
- **Revue frames indépendante acceptée :** parent a lu/accepté Sagan, `results/review_frames_source_preservation_20261020.md`, aucun P1 concret dans ce scope, worker de revue clos. Réserves explicites sur vues source/index zéro, clip et FlowParagraph non explicitement testés : aucun test ni couverture supplémentaire déduit de la revue. Acceptation bornée, pas qualification globale. Benchmark19 Laplace : préparation21 unit GREEN selon parent, aucun NN ; RUN toujours HOLD, après RU direct puis LO et autorisation, pas ajouté aux607/970. SourceMap reste un design non implémenté, gap du scope natif ouvert.
- **Actualisation runtime/coût de graphe :** sur le RU DIRECT d'Averroes, le parent rapporte un stack py-spy externe réel dans `render_plan.py::_inventory_for_document` vers325 : deepcopy par ERecord, backlinks_registry/`_registries` reliant chaque copie au registre et à tous ses records. Probe Hume sur trois vrais records : neuf records/six registries copiés individuellement contre trois/deux pour la collection ; indépendance des snapshots raw/dyn et entre appels conservée dans le probe rapporté. Racine générale de coût de graphe à traiter, aucune exception de langue/PDF.
- **État réel direct corrigé :** Averroes43536/PID hôte414241 CLOS à13:02:01, exit137 et zéro enfant propre selon retour parent. Sortie AVANT l'ordre SIGINT : aucun signal parent effectivement réalisé, cause du kill UNKNOWN, OOM non prouvé. L'intention de stopper pour coût mesuré et le libellé de coordination `cancelled-for-measured-copy-fix` ne prouvent pas la cause de sortie137. Époque distincte de46279/340249→340250 arrêté par mon wrapper sur durée non autorisée, archives/responsabilité conservées. Le patch Hume six lignes dans `_inventory_for_document`, deux copies de collection, est désormais accepté par le parent sur cinq focus GREEN et882 cas uniques, gardes stricts inchangés, tests copy-count/fraîcheur entre phases ; acceptation source-contract/performance seulement.
- **GO E2E conditionnel courant :** Averroes doit rejouer les deux vrais OCR sur le code APRÈS perf ; les deux GREEN avant perf restent acceptés dans leur époque mais ne remplacent pas ce retest. Seulement si OCR2 vert et clos : RU DIRECT exact trois pages, sans observer/runpy/profiler/replan/deadline globale CLI. Seulement si RU exit0, sorties valides3p et job clos : helper LO existant/profil isolé, limite120s UNIQUEMENT LO, puis PNG des trois pages source et des trois pages contrôle. Aucun de ces résultats/outputs/views encore reçu par ce worker ; pas de PDF/DOCX russe final prétendu. Benchmark19 toujours HOLD après cette chaîne réelle ; ce worker docs n'exécute rien ni ne change production/tests.
- **Retour de cette chaîne, non achevée :** OCR2 courant réel2 GREEN/108.27s reçu du parent, puis refus RU strict9 TextBox parents dans le dossier131636Z :7 unverified-transform et2 uncovered sur `p2` (notation du log, index/page non réinterprété ici). Erreurs Line/Span antérieures disparues du refus courant, sans masquer les parents. Le coût corrigé permet effectivement d'atteindre le garde en environ3min ; pas une requalification rétroactive de l'ancien137 ou du run20min instrumenté. Condition RU0/valid3p non satisfaite, donc aucun LO/rendu/produit réussi. Nouveau P1 général à auditer, pas d'assouplissement du garde ni exception de langue ; audits de tous modules, corpus, fonts et mapping fullgoal restent ouverts.
- **Diagnostic réel reçu ensuite :** capture error-only42865 close/exit1, frontière d'échec Plan+IR scellée dans `results/ru3_erroronly_capture_20261020_20261020T133819Z/failure/`. Hume explique les neuf erreurs : `_ligne_unit` omet l'ID du parent acquis après subdivision des vues de frames. Couverture cible des sept parents :15 lignes blanches incluses,28 visibles exclues ; pour les deux autres racines,33 lignes toutes matérialisées mais ParentID absent. Sept signatures agrégées et historiques concordants, aucun diff de données/champs de style : problème d'ancestry/coverage, pas motif pour relâcher signatures ou garde. Deuxième cause actuelle dans `_compile_page` vers306 : concaténation anchors+flow place les lignes DML27–30 avant0–26, à corriger au producteur d'ordre, pas dans le garde. Pas d'exception document/langue ni diffusion arbitraire d'aliases. Ces faits sont rapportés par le parent/Hume, sans nouveau diagnostic de ce worker.
- **Portée de la réussite :** toutes les exigences du plan, sections 2 à 24, sur les familles du corpus ; les progrès couches/angles/polices d'un PDF ne terminent aucune phase à eux seuls.
- **Backend étroit / mapping global :** correction Averroes acceptée, même objet Plan et legacy préservé. Ancien échec connecté323/1 conservé ; Galileo final1201 contient la migration explicite en trois cas du node conteneur/fragment, sans affaiblir gardes ni normaliser les rôles acquis. Audit visible accepté dans `results/final_audit_multilingual_fix_20261020/`, RED historiques préservés. Aucun succès ne ferme XML/NativeEditability : design Laplace reçu, backlog fullgoal sans production avant premier RU.
- **Gate fonts/métriques/rendu ouverte :** le parent signale l'échelle horizontale héritée `paragraph_planner.py:164-171`, clamp70..100/facteur0.96 sur une ligne. Non introduite par A ; adaptations fonts/fit à tracer et mesurer au vrai audit/backend, aucun patch polices demandé à A/B en 5. Les 570 tests ou un compte `w:t` ne prouvent pas la police/glyphe effectivement rendu.

## Focus Correctif 5

Union UNIT5 explicitement autorisée, une seule exécution :
`results/corrections_conservation_phase5_integration_20261020_102923Z/checkpoint.md`.
Résultat : **970 passed, 7 deselected, 75.03 s, exit 0**, zéro warning rapporté,
zéro skip. Handle **9111 clos**, aucun rerun. `command.sh`, stdout, JUnit,
timing, archives `/tmp`, SHA avant/après et liveness HÔTE sont conservés.
Les 570 gate4, 236 A contexte et 332 B final sont tous inclus, sans addition
des lots ; legacy default migré et extraction-scène A GREEN chacun une fois.
Les 28 contours du focus source secondaire A restent hors sélection explicite,
leur preuve antérieure est archivée, pas ajoutée aux 970. Seuls les sept
`real_cpu` sont désélectionnés. Aucun `test_text_comprehension_ai.py` présent.

Les huit sources 5 et trois sources 4 concordent aux gels, aucun changement
avant/après, y compris Scene/OCR/routage/catalogue et tests sélectionnés.
Le gel B final remplace son ancien 317/1 deselected : route utilitaire et
extraction native gardent désormais le contexte selon code/tests gelés, avec
deux conversions distinctes testées par factories/workers mockés. Ce sont des
preuves bornées de durée de vie des providers, pas une garantie sur toutes les
routes ni une qualification de modèle. Le parent accepte maintenant CODE5
après lecture de ce checkpoint ; qualité/root/modèle restent ouverts en 6.

Archives intermédiaires byte-identiques aux notes et XML `/tmp` lors du contrôle :
`results/reprise_universelle_20261020/phase5_focus_received_101649/manifest.json`.
Notes A/B, 236 et 314 A, 317 B, et ancien default rouge séparé conservés. Les
désélections de ces anciens focus ne sont pas celles de l'union finale UNIT5.

La note B initiale documente deux appels de chacun des vrais entrypoints convertir et
reconstruct_bbox_native avec factory counters/workers mockés : un provider
distinct et une tentative par conversion dans ces tests. Elle exclut la route
utilitaire native_document qui reset None avant writer, corrigée depuis dans
le gel B final et couverte dans l'union UNIT5. Cette preuve remplace une
simple hypothèse issue des trois fichiers lus, sans garantir toutes les routes.

Revue provisoire autorisée sur les seuls executor/factory :
`results/reprise_universelle_20261020/revue5_executor_factory_preliminaire.md`.
Aucun P1 concret identifié dans cette lecture : délai worker, reap et claims
shadow None/unqualified/non-applied, priorité HTTP et racines. La route locale
expérimentale opt-in reste distincte, timeout coopératif et décision advisory
possibles ; ne pas lui attribuer les garanties du shadow. Aucun modèle réel,
benchmark 19 ou qualification de qualité exécuté/déduit ici.

## Préparation Corrective 6

**RU interrompu, non achevé :** handle46279 désormais CLOS, aucun rerun.
Wrapper340249 a envoyé SIGTERM à340250 vers12:05:31 sur son plafond1200s,
ajouté sans autorisation parent : erreur de ce worker, pas un garde mémoire,
OOM ou diagnostic de lenteur production. Fin12:05:33/1202.97s/CLI -15 ; tous
les exports attendus absents, observer finalization non achevée, phase exacte
et overhead inconnus.163 SHA inchangés au contrôle post-abort12:32:40 et
source stable ; modèles size/mtime stables seulement, pas hashes des poids.
Preuves : `results/integration_ru3_reelle_20261020_114418Z/post_abort_evidence.json`.
PID hôte absents et user290402 intact à12:32:06, aucun job propre restant.

**OCR2 après frames GREEN, GO RU historique exécuté une fois :** retest
`results/integration_ocr2_reelle_apres_frames_20261020_20261020T113834Z/`,
2 passed/deux warnings/123.80s/exit0, fin11:41:01, owned_remaining vide et
code/modèles stables selon summary. Neuf archives SHA concordantes dans
`ocr2_after_frames_received_114418/manifest.json` du dossier de reprise.
RU unique démarré11:45:30 puis interrompu comme ci-dessus ; invocation/log/préflight et
checkpoint dans `results/integration_ru3_reelle_20261020_114418Z/`. Aucun LO
avant clôture et GO distinct, pas de deuxième pipeline ni relance automatique.

**Premier OCR2 réel RED, époque préservée** : originaux
`results/integration_ocr2_reelle_20261020_20261020T111443Z/`, deux nodes réels
échoués,143.59s/exit1/deux warnings. Copies log/XML/summary/invocation/refus/
drifts/timeline byte-identiques/SHA dans
`results/reprise_universelle_20261020/ocr2_failure_received_112017/`.
Deux Line natives aca4b648d3912bb19bb379c8 / ba3fff097c03ab6e35738c3c signalées
source-mutated-after-plan ; six preuves OCR refusées par node, pas douze sources distinctes.
Résumé original : code/modèles stables, owned_remaining vide, pas de DOCX final.
Correctif producteur Hume accepté, retest OCR2 réel ensuite vert ; le résultat
ne réécrit pas cette première époque ni ne prouve une qualité modèle globale.

**Cause active confirmée, générale et non linguistique :**
`results/ocr_native_line_mutation_fix_20261020/checkpoint.md` identifie
`extract/document.py::_attacher_frames_texte`, appelé par `_remplir_page`
après acquisition/sélection OCR et signature des observations. Il écrivait
`layout_frame_id`, `layout_frame_role`, `layout_frame_strategy`,
`layout_frame_bbox` sur les Line acquises. Le probe Hume retrouve les deux
vrais IDs natifs : validation du plan sans erreur avant cet appel, puis deux
Line mutées et six correspondances refusées après. Ses observations OCR sont
reconstruites, pas les octets OCR/IR du runtime non exportés ; il n'exécute
aucune reconnaissance OCR/modèle/CLI/LO. Inventaire identique, Span inchangés,
digests stricts correctement bloquants : ne pas re-signer après mutation pour
effacer le défaut. Correction bornée à `pdfexact/extract/document.py` et cinq
tests views désormais acceptée, sans modification IR/Scene/OCR/digests ; aucune
gate OCR2 réelle passée pour autant. Le pattern lossy replace du helper legacy diagnostiqué
par Averroes est séparé, inactif sur ce chemin et non patché pour ce bug.

**Acceptation producteur bornée607 :** vues locales préservant les metadata pour
l'analyse des frames, vraies Line/Span acquises remises inchangées dans les
owners dérivés, groupes contigus sans aliases de siblings. Deux lots disjoints
280/156.96s et327/7 deselected/44.56s donnent607 cas GREEN uniques, pas une
nouvelle fullsuite ni tous les570 cas de4. Les282 source3,114 source4 et177
stage5 sont inclus dans607 ; les cinq nouveaux tests views aussi. Contrôle
final d'un cas renforcé1 GREEN non ajouté au total. SHA producteur
`8ff74887ef1e9abb44b6c3086716aa84eadd6d23010bc687dfb013ca0ec97119`,
29 entrées du gel et sept fichiers protégés concordants à11:38:59 ; handles
Hume clos selon checkpoint, acceptation parent après diff/gel/fermeture.
Preuve bornée : `producer_frames_607_acceptance_113859.md` dans le dossier de
reprise. Premier OCR2 RED inchangé ; retest réel vert reçu ensuite, GO RU réel
acquis, aucune autre inférence/LO en parallèle par ce worker.

Commande utilisateur RU préparée spans100dpi/PaddleCPU/VysiRoot/p1-3 :
`results/reprise_universelle_20261020/ru3_cli_prepared_HOLD_111347.md`.
Observateur `observe_native_cli_prepared_111347.py` préparé, AST seul/non exécuté :
runpy du vrai main, observation appels/retours sans modifier fonctions/callbacks
de décision, mêmes références Document/Plan/writer. Helpers de sérialisation
du collecteur après retour, jamais collect()/nouvelle extraction/plan pour
compter ; historiques par vrais états, sans getter paresseux créant un provider.
Parts manifeste/XML lues seulement du vrai DOCX écrit ; absences/gaps explicites.
Sorties non créées, aucun lien résultat fabriqué ; LO après CLI et GO séparé,
profil temporaire isolé. Source SHA/préflight11:22:05 dans
`ru3_hold_preflight_112017.json` : RAM disponible1.570 GiB/results3.253 GiB,
autre Python PID290402 actif/non possédé/non touché, type non inféré. Source RU
SHA concordant et production/scripts inchangés au relevé, pas freeze du fix Hume.

Actualisation : acceptation parent de la correction backend étroite seulement,
10/10 et connecté 323/1 vérifiés dans les JUnit. Audit visible Sagan désormais
accepté : 82/1 API-gap xfail inchangé et 12 connectés, preuve indépendante
`results/reprise_universelle_20261020/audit_scope_acceptance_105818.json`.
Galileo final1201/7 et GO fullsuite parent reçus : unique run terminé/archivé
`results/integration_universelle_full_20261020_110245Z/`, handle61756 CLOS/libéré.
Mapping non coché, design reçu/backlog sans production avant premier runtime RU.
Séquence effective demandée après passage des gates : **suite nonvisuelle
complète → deux CLI OCR réelles → RU trois pages → LO du même DOCX/corpus
sériel**, un seul job lourd, un Plan par conversion, aucun rerun automatique.
Commandes et limites vérifiées :
`results/reprise_universelle_20261020/preflight6_execution_readiness_104831.md`.

- [x] Consigner l'acceptation parent de la correction backend étroite sur 10/10 et SHA concordant, JUnit relus sans rerun ; pas un mapping XML/qualité globale accepté.
- [x] Consigner l'acceptation parent des contrats audit visible Sagan : 82 passed/1 API-gap xfail inchangé, 12 connectés distincts, 62 RED corrigés, source/snapshot/JUnit concordants dans `audit_scope_acceptance_105818.json` ; editability_verified=False, aucune preuve NativeEditability globale.
- [x] Recevoir/consigner acceptation parent Galileo1201/7/175.01s et GO6-UNIT-FULL ; JUnit1201 uniques, trois cas legacy migrés et SHA source/tests concordants dans `galileo_final_artifact_observed_105818.json`. Ancien323/1 préservé, pas une preuve rendu1owner.
- [x] Clore l'unique fullsuite61756 : sortie/JUnit/échec/skips/warnings/SHA/membership archivés,162 chemins stables, processus hôte absents ; RED non masqué, aucun rerun automatique ni OCR2.
- [x] Recevoir migration default15 GREEN/2.42s acceptée, `results/cli_default_shadow_test_fix_20261020/report.md`, production inchangée ; époques fullsuite et OCR2 distinctes.
- [x] Consigner/archiver OCR2 réel RED2/143.59s, refus du garde non masqué, originaux/copies/SHA préservés, aucun rerun de ce worker.
- [x] Consigner la cause active générale `_attacher_frames_texte` et le GO Hume producteur seul/cinq tests views ; helper legacy Averroes séparé/inactif/non patché, gardes IR/Scene/OCR/digests stricts conservés. Le probe reconstruit ne remplace pas les deux vrais tests OCR.
- [x] Recevoir l'acceptation parent du correctif producteur Hume seul sur607 GREEN, gel/protected SHA concordants et JUnit disjoints relus ;282/114/177 inclus, pas de somme ni qualification runtime.
- [x] Consigner l'acceptation parent de la revue indépendante frames Sagan sans P1 concret : `results/review_frames_source_preservation_20261020.md`, revue close et limites conservées (vues source/index zéro, clip, FlowParagraph non explicitement testés). Aucun nouveau test, run ou qualification globale déduit.
- [ ] Exécuter/qualifier benchmark19 uniquement après RU direct, LO et autorisation : préparation Laplace21 unit GREEN sans NN seulement, RUN HOLD. SourceMap design non implémenté/gap natif toujours ouverts.
- [x] Recevoir les deux vrais tests OCR2 GREEN après frames :2 passed/123.80s/exit0, fin11:41:01, aucune tâche propre résiduelle/code-modèles stables selon summary ; neuf archives/SHA et JUnit relus, premier RED conservé.
- [x] Démarrer UNE vraie CLI RU sur GO6-RU3-REAL avec observateur préparé :11:45:30, handle46279, dossier exclusif `integration_ru3_reelle_20261020_114418Z`, préflight hôte et source SHA concordant, endpoints vides/PaddleCPU/racines explicites. Aucun résultat final déduit du démarrage.
- [x] Clore le même handle46279 et consigner l'interruption -15/1202.97s causée par la limite temporelle non autorisée du wrapper ; gaps tous explicites, aucun export ni compte plan/provider inventé. Aucun processus propre résiduel/SHA163 stables post-abort, pas de relance ni LO.
- [x] Consigner le relais parent GO CLI directe exacte à Averroes sans profiler/runpy/wrapper/deadline globale ; worker docs uniquement, aucun redémarrage propre ni modification du gel. Handle46279 clos et PID340249/340250 absents déjà acquittés.
- [x] Consigner le coût runtime général mesuré du graphe d'inventaire : stack py-spy RU direct et probe Hume trois vrais records, copies9/6 contre3/2 en collection ; chemin des traces/RED/freeze à recevoir, aucun nouveau run du worker docs.
- [x] Recevoir clôture réelle43536/PID414241 à13:02:01, exit137 AVANT l'ordre SIGINT, zéro enfant propre ; aucun signal parent réalisé, cause UNKNOWN/OOM non prouvé. Intention stop mesuré distincte de sortie réelle et de l'ancien harness46279.
- [x] Consigner GO production Hume après fermeture : `_inventory_for_document` seulement, deux copies de collection, tests déterministes ; aucune modification production/tests par ce worker docs.
- [x] Recevoir l'acceptation parent du patch performance/source-contract Hume six lignes/deux copies de collection : cinq focus GREEN et882 uniques,570/282 historiques inclus sans cumul, gardes stricts inchangés, tests copy-count/body-metadata/fraîcheur entre phases. Source du constat parent et limites dans `results/reprise_universelle_20261020/perf_inventory_882_acceptance_parent.md` ; aucune relecture/exécution supplémentaire déduite pour ce worker.
- [x] Consigner GO Averroes chaîne conditionnelle OCR2 courant clos/vert -> RU DIRECT0/valide3p/clos -> helper LO existant isolé/limite120s LO seule -> trois PNG source et trois contrôle ; aucun observer/replan/deadline globale CLI.
- [x] Recevoir du parent OCR2 réel POST-perf2 GREEN/108.27s ; époque courante distincte des deux tests pré-perf, aucun compteur ajouté aux882 et aucune qualification lecteur/native editability déduite.
- [x] Consigner refus RU courant avant sorties dans `results/e2e_ru3_cli_direct_20261020_20261020T131636Z/` :9 parents TextBox (7 unverified-transform,2 uncovered `p2`), erreurs Line/Span antérieures absentes, aucun produit/LO/rendu réussi. Anciennes époques137/20min préservées.
- [x] Recevoir clôture réelle de la capture error-only42865/exit1 et export scellé selon parent ; ne pas déduire un succès RU ni attribuer cette fermeture à l'ancien run131636Z sans preuve distincte.
- [x] Consigner diagnostic Hume du vrai Plan+IR : perte ParentID dans `_ligne_unit`,7 cibles15 blanches/28 visibles exclues,2 racines33 lignes matérialisées sans ParentID ; sept signatures agrégées/historiques concordants sans diff données/style. Défaut d'ordre anchors+flow `_compile_page`27–30 avant0–26 également actuel.
- [x] Consigner GO production Hume limité à text_segmentation ancestry/registre typé et render_plan `_compile_page` ordre ; gardes/digests/signatures intacts, patch perf six lignes conservé, zéro exception document/langue et aucun patch de ce worker.
- [x] Recevoir gel/revue/acceptation parent des producteurs ancestry/ordre946/7/130.96s/51033 clos, `results/parent_lineage_compile_order_fix_20261020/checkpoint.md` ; captures lourdes/SHA d'origine sur place, pas de duplication147MB.
- [x] Recevoir et exécuter par l'acteur autorisé le GO runtime réel POST946 : deux OCR puis CLI directe réussis, preuves dans `results/e2e_current_parents_order_20261020_20261020T151652Z/` ; aucune exécution de ce worker docs.
- [x] Recevoir conversion RU directe achevée et vrais DOCX/bboxes/catalogue/manifeste ; sourcecoverage376/376/package valide, pas mapping sourceXML ni scène/plan autonomes fabriqués. LO/visuel restent ouverts, anciens runs non requalifiés.
- [ ] Conserver/valider au fullgoal les rôles per-source sous un conteneur commun ; deux owners obligatoires tant que les rôles parents acquis restent incompatibles et sans traçage agrégat légitime.
- [ ] Valider le mapping XML Laplace sur les vrais objets/ranges du package écrit : design reçu selon parent, backlog fullgoal ; pas de production mapping avant le premier runtime RU ni case cochée depuis un manifeste.
- [x] Préparer la suite nonvisuelle, OCR2 exacts, RU3, LO standalone et sous-ensemble réel Rita du collecteur existant, sans exécution : `golden_table_prepared_104831.json`, pas une nouvelle famille ou un second runner.

Autorisation CODE6 initiale historique, remplacée pour l'audit par le GO CODE
actuel consigné plus haut, préservée dans
`results/reprise_universelle_20261020/acceptation_code5_go6_code_103816.md` :
Averroes `01a158db-18e9-7773-ac6c-4d9f7a52f5d0`, façade bbox→backend principal,
même objet Plan exact, contenu legacy préservé ; Sagan
`01a158e0-0749-77d1-9eb3-99f00dd97dea`, tests RED audit supplémentaires
seulement avant freeze backend. Elle n'autorisait aucun fullsuite/corpus/NN/LO.
L'acceptation backend ultérieure et le GO Sagan actuel ne ferment pas le mapping.

Le socle de sept cas est conservé. Deux contrôles d'acquis utilisateurs sont
ajoutés, sous réserve des futurs gates d'exécution : Katrina
`0fd83d2aa11747d4_000152.pdf` p1 et bandeau/lettrine L colorée
`4e4a2d80e91be727_000583.pdf` p1. Présence sous Vysi et SHA vérifiés ; pas de
nouveau rendu ni de reflow acceptable présumé. La même page 4e4a porte le
golden crédit vertical, sans conversion ou plan supplémentaire nécessaire.
Neuf cas ainsi préparés, pas neuf résultats GREEN ni douze familles closes.

Golden existant relu : proposition additionnelle Rita p13, vrai tableau à
en-têtes groupés, et St. Lawrence p1-2, brochure avec lien imprimé p2. Les JSON
existants ne prouvent pas une annotation cliquable : la gate liens natifs/URI
et relations OOXML reste à qualifier. Utiliser le manifeste/collecteur existant,
pas un second runner. Détails :
`results/reprise_universelle_20261020/preparation6_corpus_et_ressources_20261020.md`
et `corpus6_sources_100959.json` dans le même dossier. Nouveau contrôle sans
parsing PDF : `corpus6_sources_103816.json`, 10:38:56 UTC, quatre fichiers/SHA
et manifeste inchangés. Références de rendu exactes et mappings IR/sortie/XML
restent à observer ; le DOCX historique Katrina présent/hashé n'est pas promu
automatiquement en référence utilisateur exacte.

Relevé HÔTE renouvelé 10:58:40 : RAM disponible **2.762 GiB**, swap utilisé
**3.593 GiB**, huit CPU ; libres results **3.265 GiB** et /tmp **9.952 GiB**.
Aucun Python/pytest/CLI/LO correspondant hors commande de lecture ; service
Ollama préexistant laissé intact/inutilisé. `preflight6_105818.json` dans le
dossier de reprise : cgroups scope/ancêtres lisibles sans plafond explicite,
racine unknown, pas pic de modèle. Ressources à renouveler avant lancement.
Neuf cas préparés : huit PDF présents/SHA concordants, fixture CJK/RU non
assignée/persistée ; extensions Rita/St. Lawrence aussi hashées sans conversion.
CODE5/backend étroit/audit visible/Galileo acceptés ; fullsuite autorisée en
cours. Aucune fausse disponibilité 9/9 ni gate modèle/rendu fermée. Nouveau
préflight de départ 11:02:47 dans le dossier fullsuite : RAM disponible2.865 GiB,
results libres3.260 GiB ; aucun job test/CLI/LO correspondant avant lancement.
Aucun modèle/CLI réel/corpus/fullsuite/rendu de qualification lancé pour cette
préparation ; l'union UNIT5 autorisée séparément est documentée ci-dessus.

## Readiness Fullplan

Sections 23/24 relues : les six correctifs ne terminent pas les dix étapes de
migration, les **12 familles × 7 artefacts** ni les **10 critères**. Readiness
priorisée et preuve attendue pour chaque critère :
`results/reprise_universelle_20261020/readiness_fullplan_23_24_104831.md`.
Actualisation après LO isolé : Galileo946 et OCR2/RU ont leurs preuves bornées,
mais contrôle LO absent malgré deux essais clos. Audit actuel du todo/plan et
priorités vérifiables : `results/reprise_universelle_20261020/readiness_after_lo_isolation_20261020.md`.
Mapping XML Laplace toujours ouvert (design non implémenté), matrice ancien/nouveau de
tous les appelants/options/renderer/extracteurs et registre de pertes. Profils
Word ET LO et suppressions des dix catégories section20 restent des gates
propres ; code ancien non supprimé avant migration/tests/corpus complets.
Aucune phase universelle cochée depuis le seul succès backend.

## Passage Correctif 4→5

Point 5B : note `/tmp/phase5-B-api-ready.md` relue, copie préservée dans
`results/reprise_universelle_20261020/phase5_B_api_ready_received_095419.md`.
Huit mocks transport GREEN rapportés, 20 deselected/0.40 s ; aucun JUnit relu
ici, aucun freeze 5 ni qualité/budget par conversion déduit. Intégration des
producteurs en cours selon le parent. Préflight 6 documentaire préparé dans
`results/reprise_universelle_20261020/preflight_etape6_prepare.md`, commandes
non exécutées lors de cette préparation. CODE5 désormais accepté et GO CODE6
borné reçu ; preuves backend/audit et GO d'exécution distinct restent requis.

Le parent accepte l'étape corrective bornée 4 après sa revue source/rapport et
la revue marqueur, puis donne GO5 A/B. Revue confidence indépendante terminée
sans défaut concret identifié :
`results/reprise_universelle_20261020/revue_gate4_confidence.md` et
`revue_gate4_confidence_checks.json`. Référence testée :
`results/correction_source_contracts_phase4_confidence_20261020/checkpoint.md`
et `freeze_sha256.txt`, 23 entrées de gel et 14 protégées concordantes.

Evidence confidence liée au vrai ID/type/composants ordonnés, reconstruite
depuis la source acquise ; agrégat `None` si divergence, zéro/inconnu séparés.
Altération/perte de confidence Line/Span, preuve requise absente ou fausse et
faux agrégat sont refusés dans les contrats relus. Pas d'ID fabriqué, pas
d'assouplissement paint, RenderPlan byte-identique au gel précédent. Les seize
FAIL de l'ancienne union intermédiaire sont tous GREEN dans le gel 570 ; les
douze anciens GREEN gel3 cités alors ne sont pas des échecs de cette fin.

- [x] Recevoir le freeze confidence, vérifier SHA et inclusion exacte des 543+27 dans les 570, sans rerun.
- [x] Terminer la revue indépendante du patch confidence, puis consigner l'acceptation parent de l'étape corrective 4.
- [x] Consigner GO5 A/B : périmètre correctif documenté `analysis/semantic.py`, `layout/paragraph_planner.py`, `layout/text_comprehension.py`, `layout/text_comprehension_ai.py`, `layout/text_comprehension_local.py` et `analysis/text_segmentation.py`. Répartition fine A/B portée par les missions du parent, pas inventée ici.
- [x] Recevoir les gels finaux A/B et exécuter l'union UNIT5 unique autorisée ; 970 GREEN/7 deselected, archives et SHA concordants dans le checkpoint d'intégration du 20 à 10:32.
- [x] Recevoir l'acceptation parent CODE5 sur les preuves contractuelles bornées UNIT970 et du cycle provider mocké ; aucune garantie globale ni qualité réelle déduite.
- [x] Consigner GO CODE6 Averroes façade et Sagan tests RED audit seulement avant freeze backend ; pas de GO fullsuite/corpus/NN/LO ni clôture d'une phase universelle.
- [ ] Qualifier root/modèle/qualité réels et benchmark 19 après autorisation distincte en 6 ; mapping source→XML/rendu toujours INCOMPLETE.

## Reprise Après Pause Du 20 Octobre

Preuve de coordination :
`results/reprise_universelle_20261020/reprise_apres_pause_085827.md`, enregistrée
à 08:58:27 UTC depuis le message parent de cette conversation. L'utilisateur a
explicitement révoqué la pause par « continues ». Le parent signale un
`get_goal` encore `paused` ; ce worker ne prétend ni avoir relu ce goal ni avoir
changé son statut. Aucun nouvel objectif créé, plan universel complet inchangé.

État transmis à 08:58, historique : Hume reprend le dernier FAIL 4, marker 103 GREEN/1 RED.
Les compteurs sont rapportés par le parent, sans XML/log/SHA/commande/handle
final transmis ici ; ils ne deviennent ni un total GREEN ni un freeze. Les
constats production et hôte de la section suivante restent datés de 08:40,
pas des vérifications de l'état à 08:58.

- [x] Consigner la reprise utilisateur et distinguer son autorisation du statut UI `paused` rapporté ; ownership docs/preuves conservé.
- [x] Recevoir du parent le rapport/freeze Hume et l'artefact gate4 ; gel 543 puis gel confidence 570, chemins et SHA dans la revue ci-dessus.
- [x] Après réception, revue marqueur statique et revue indépendante confidence ; vrais Line/Span, ordre/paint/cache et preuve bornée, aucun nouveau run.
- [x] Consigner l'acceptation parent 4 et GO5 A/B à 09:49:40 UTC ; étape 6 toujours sans GO.

La pause précédente est conservée comme événement historique. Aucune production,
aucun test, audit, plan, modèle ou corpus exécuté à cette reprise documentaire.

## État observé du 2026-10-20

Preuves : `results/reprise_universelle_20261020/README.md`, `git.json`,
`source_snapshot.json`, `artifact_manifest.json`, `inventory.json` et
`host_processes.md`, `host_processes_084013.txt` et `followup_snapshot.json`.
HEAD `03a5b4839773cb1e27ae2255e66307fe59d13a89`, branche
`main`, arbre sale préservé ; le commit ne représente pas les sources modifiées.
Le parent donne l'objectif universel complet ACTIF. `get_goal` de ce worker vaut
`goal=null` et ne permet pas de relire le goal du parent ; aucun objectif modifié.
Le worker docs/evidence de reprise remplace Arendt
`01a129bf-5a02-7bd0-bddf-72b5916606ab`, donné `not_found` par le parent à 08:31 UTC.
Les attributions Arendt/Hubble du journal ci-dessous restent historiques.

| Fichier production du lot 4, suivi à 08:40:35 UTC | SHA-256, tous différents des gels 2/3 |
| --- | --- |
| `pdfexact/analysis/provenance.py` | `ecfd02ae8b4b37affaa511384bd898b7dc676c3d071f143678b49e8eea6cf300` |
| `pdfexact/render/reflow.py` | `ae579b41f0890ebf96856db8f73c89ce697aa9dfdc3d9a7bc0aac970b47b9b48` |
| `pdfexact/render/render_plan.py` | `15bf3ce359296691051fa2904a9d8e8d53272a9a620a29e26ab13e7a47834a6d` |

L'observation initiale de 08:36 concordait encore aux gels 2/3 ; le contrôle
final a détecté les écritures concurrentes du worker 4, mtimes production du
20 à 08:36:53 puis 08:40:28. Le nouveau snapshot conserve les SHA initiaux et
suivants, sans écraser les preuves. Le test fusion a également changé. Cette
activité n'est ni un GREEN, ni une revue, ni un freeze du lot 4.

Le RED initial 4 du 11 précède les changements 2/3 : ses SHA RenderPlan/reflow
différents ne prouvent pas une implémentation 4 depuis le 12. En revanche, les
artefacts nouveaux existent réellement : `tests_observables_red.xml` du 12,
37 failed/12 passed/4.944 s, puis deux XML cache OCR du 20 à 08:25 UTC, chacun
2 failed sur les mêmes node IDs. Le premier échoue sur `page-mismatch`, le
second révèle deux occurrences du composant réel/cache au lieu d'une. Aucun
GREEN 4 ni commande/handle peer non reçu n'est inventé.

Lectures hôte autorisées, hors sandbox, à 08:34:10 puis 08:40:13 UTC : aucun pytest, CLI de
conversion, collecteur/validateur corpus ni LibreOffice correspondant vivant ;
seuls le shell et le filtre d'observation correspondent. Un verrou n'est pas
une preuve de job. Ce constat daté n'annonce pas l'activité future du worker 4.
65737/55071 sont des IDs de sessions historiquement closes, pas des PID hôte.

La consolidation RED ancienne est **achevée sur disque** depuis le 12 à
07:57:24 UTC : quatre époques, 99 node IDs distincts, 78 RED/21 témoins, pas une
union exécutée. Originaux `/tmp`, copies/manifest/sets/rapports concordants sont
préservés dans le nouveau dossier. L'inventaire étendu compte 163 node IDs RED
historiques distincts sur neuf époques ; recouvrements 28 fusion/observables et
2 cache/cache. Les 218/282 acceptés sont séparés ; aucun résultat historique
ne devient baseline du code actuel. Audit RED : 1.33 s console/1.329 s XML ;
backend RED : 3.39 s console/3.387 s XML. Aucun test relancé par ce worker.

- [x] Observer Git, SHA production, derniers résultats et processus hôte en lecture seule ; preuves ci-dessus.
- [x] Relire les compteurs et vérifier les SHA publiés des gels 2/3 et des JUnit backend/audit, préserver les RED et node IDs par époque.
- [x] Corriger l'état documentaire de réception backend/audit et de consolidation RED dans les deux suivis.
- [ ] Recevoir les GREEN/revue/freeze 4 du worker production ; aucun GO5/6 déduit de la reprise documentaire.

La portée demeure le plan entier, sections 2 à 24, et non ces seules corrections.
Backend/mapping/audit, runtime/CLI, lecteurs, corpus, migrations et critères
universels restent ouverts selon leurs gates propres. Seuls les deux suivis et
le nouveau dossier de preuves sont écrits par ce worker.

## Phases

| Phase | Statut | Résultat attendu |
|---|---|---|
| 0. Gel des invariants et contrats | Partielle, clôture historique non établie | contrats/adaptateurs/snapshots complets et comparables à confirmer |
| 1. Géométrie et provenance centralisées | Non validée globalement, correctifs B2/B3 ciblés rapportés | wrappers communs, registre brut complet, métadonnées et consommation à fermer |
| 2. Compréhension et regroupement universels | Non validée globalement ; conservation des blancs ciblée acceptée, sémantique/options à fermer | regroupement unique et indépendant du renderer, script-aware |
| 3. RenderPlan universel | Non validée globalement ; contrats correctifs 3 OCR/natif acceptés sur gel 282 GREEN, runtime/CLI ouverts, garde package B1 distincte | couverture canonique et décision de chaque source/écarté à établir |
| 4. Backend DOCX unique | Migration partielle, critères non satisfaits ; étape corrective 4 acceptée et GO correctif 5 A/B, pas clôture du backend universel | `word_native_rewriter` seul orchestrateur pour tous les chemins |
| 5. Audit par élément et corrections locales | Contrats partiels présents, validation après Phase 4 | couverture source/sortie, corrections locales rejouées et vérifiées |
| 6. Suppression contrôlée des chemins concurrents | Verrouillée | tous appels migrés et critères globaux satisfaits avant suppression |

## Reprise active du 2026-10-12

Le parent confirme la reprise de l'objectif universel dans son `get_goal` et par
continuation utilisateur explicite. La pause demandée le 2026-10-11 après le
release rouge est historique, non le statut présent. Le worker ne crée/modifie
aucun objectif : son propre `get_goal` vaut `goal=null` et ne décrit pas le parent.
Ownership de cette reprise : Arendt modifie uniquement ce suivi et
`docs/todo_corrections_conservation_semantique.md`, sans production/tests, reprise
de benchmark, extraction, plan, modèle ou corpus. État Git sale et ancien journal
conservés. Plan courant relu, SHA-256
`ca6bb1957624836912b6a98a33d3f11b542b69c5165fbfaf3b809b06b3fbed93`.

### Numérotation et correspondance des six corrections

Les **étapes correctives 1-6** du todo ne remplacent ni les **Phases universelles
0-6** (plan section 3), ni ses **dix étapes de migration** (section 23).
Accepter l'étape corrective 2 ne clôt donc pas la Phase universelle 2 ; GO6
d'intégration corrective n'autorise jamais la Phase universelle 6 de suppression.

| Étape corrective | Exigences universelles concernées | Acquis ciblés et preuve encore nécessaire |
|---|---|---|
| 1. RED | Sections 2, 4-8, 11, 19, 22-23 ; contrats et comparaisons Phases 0-3 | Consolidation historique quatre époques/99 IDs achevée, inventaire étendu du 20/163 IDs ; pas de suite globale exécutée ni preuve de tous les types du plan |
| 2. Blancs/payload et paint | Sections 2, 4-8, 12-15, 19, 22 ; non-perte/coordonnées/consommation décidée avant XML | 218 GREEN au gel du 11 octobre, contrats source/IR/XML acceptés ; lecteurs/pixels/fonts/corpus et migration complète non prouvés |
| 3. Lineage OCR/natif | Sections 2.1/2.5, 4-7, 12, 16, 19, 22 ; acquisition par zone et couverture avant écriture | Contrats bornés acceptés, union unique 282 GREEN, observation OCR/paint natif séparés et ambiguïtés conservées. Deux vrais CLI restent ouverts en étape 6 ; aucune clôture universelle 3 |
| 4. Fusions metadata/proofs | Sections 4, 8, 12-15, 19, 22 ; groupes/canonique/paint et clones sans perte | Étape bornée acceptée par le parent sur gel confidence Hume 570 GREEN, revue indépendante OK, contrats 3 inclus ; aucune clôture du backend universel |
| 5. IA/contexte/gardes | Sections 2.2, 8-11, 18, 21-22 ; hypothèses script-aware, options et diagnostics | CODE5 accepté sur UNIT970/SHA stables, contrats mockés bornés ; root/modèle/qualité et budget réel ouverts en 6. Shadow/JSON accepté ne prouve ni qualité ni application qualifiée |
| 6. Intégration corrective | Sections 12-19, 21-24 ; tests/CLI/plan réel/XML/contrôles/mapping | Producteur607 et OCR2 réel2/123.80s acceptés, premier RED préservé ; RU46279 interrompu par limite temporelle du wrapper non autorisée, aucun export/LO. XML/rôles/12×7/10 critères ouverts |

Cette correspondance ne ferme aucune ligne du registre fonction par fonction
des sections 4-22 ci-dessous. Restent notamment les métadonnées de tous les types
IR, tous les extracteurs/classifications/propositions de layout, tables/images/
formes/fonts/liens, autres modes backend, façade/legacy, comparaisons ancien/
nouveau, options uniques, audit source/sortie exhaustif et corrections locales
rerendues avec rollback. Le dernier PDF russe et les blancs ne réduisent pas
l'objectif universel aux seules fonctions touchées par ces corrections.

### Gel 2 réellement relu, pas baseline du RenderPlan 3

Checkpoint : `results/correction_source_contracts_phase2_boundary_20261011/checkpoint.md`.
Dernier lot **218 passed, 4 warnings, 6.12 s, exit 0**, session 11715 close selon
rapport. JUnit relu le 12 : `tests_height_cap_contracts.xml`, 218 cas,
0 failure/error/skip, 6.122 s, timestamp `2026-10-11T20:25:24.576799+00:00`.
Les avertissements sont les quatre replis attendus de partitions IA mockées
invalides. Aucun test relancé, pas d'addition aux 152/165/215/217 précédents.

| Fichier au gel 2 | SHA-256 archivé et état de relecture au 2026-10-12 |
|---|---|
| `analysis/text_geometry.py` | `88235f50359c6691c0e01bb0e6bf53b6f8f5e3f9f3083f402dff48a9709a5e1a`, inchangé |
| `render/geometry_adapter.py` | `a1b8b41bc115fcfdd054cf431b4f52677801bcfd9cdbcda10b64fcece06cedd4`, inchangé |
| `analysis/text_segmentation.py` | `b6232bc8942a08a15cd5fc9de5e06a369617fd57305d5282ec30573d472b75cd`, inchangé |
| `tests/render/test_boundary_blank_paint.py` | `928e744bec99fb58c31e32158281a825a889bc8fcdc2e1f3082ce2ec09e58ad7`, inchangé |
| JUnit `tests_height_cap_contracts.xml` | `2e1b212ccc30254b6303bc8d388ce71ce689c7db05604d4028f10a186206caf6`, inchangé |
| `render/render_plan.py` au gel 2 | `6b7673c82d622af42c90dc222e3f58c97e10777a06050cbdda53e4da8d5a0be2`, référence testée historique |
| `render/render_plan.py` étape 3 observé le 12 | `a761996829158b792d09f4be35f0e464f2769c24a426855547d81522c2aa925b`, différent pendant travail autorisé |

Les contrats vérifient enveloppe paint positive leading/trailing, corps/baseline
conservés à la quantification canonique, espaces ordinaires sans inflation,
step source et hauteur `ink+(N-1)*step`, fragments natifs indépendants déjà
supportés, IDs de matérialisation uniques et couverture stricte. Ce gel accepté
ne constitue PAS une baseline actuelle de l'étape 3, ni un rendu Word/LibreOffice.
Le changement autorisé du RenderPlan n'est ni masqué ni reverté.

Historique intermédiaire du 12, avant acceptation 3 ci-dessous : le checkpoint Pascal **195 passed/
1 failed** sur ancienne signature de mock, avec correction étroitement autorisée
et ajout blank-only/noOCR, est conservé comme historique. Nouveau checkpoint
parent : producteur gelé sur 17 tests, miniIR/anti-whitewash clos ; consumer
76 GREEN rapporté puis huit tests boundary/policy ajoutés. Union finale Hubble
de dix fichiers annoncée vivante, **handle 65737**, `PDFEXACT_TEST_LOCAL_OCR=0`,
filtre `not real_cpu`. Aucun de ces nombres n'est additionné ; tests ajoutés ne
signifie pas GREEN observé. Commande complète/JUnit/code/durée/SHA finaux de
l'union non reçus ici, aucun résultat final inventé. Parent relit le checkpoint
après l'union avant éventuel GO4 ; clôture des contrats/proofs, état des deux
régressions CLI et gel final restent à documenter. Arendt ne poll/restart/cancel
pas cette session peer.

Preuve producteur reçue ensuite :
`results/source_corrections_phase3_20261011/checkpoint.md`, gel
`2026-10-12T07:35:46Z`. Quatre SHA production/tests concordants avec le checkpoint,
XML relus : 14 GREEN/16.968 s, connecté 195 passed/1 failed/40.728 s, mini
blank/mock/binding 3 GREEN/1.848 s, mini acquisition anti-whitewash 3 GREEN/
4.338 s. Aucune addition ; les 17 cas du fichier final incluent les ajouts,
pas un résultat final de 17 tests exécutés ensemble. Legacy spy corrigé dans le
mini-lot autorisé, ancien résultat rouge conservé. Commandes/handles/logs dans
le checkpoint, détail SHA/limites dans le todo correctif. Deux vrais CLI non
exécutés ici, aucune qualité OCR ou lecteur/pixel déduite.

Revue indépendante lecture seule Arendt : aucun P1 concret identifié dans ce
scope. `scene.py:523`/`:526` garde acquisition et raw actif séparés ;
`render/render_plan.py:669`/`:680` compile le payload réel, pas sa copie acquise.
Le helper `analysis/ocr_correspondence.py:312`, `:347`, `:411`, `:420`, `:431`
recalcule population/unicité inverse/preuve/événement puis compare les vrais
composants aux empreintes acquises. Binding indépendant `:121` et
`render/render_plan.py:435` ; paint natif toujours gardé séparément `:181`/`:202`.
Adversaires mutation, faux événement/page/preuve, missing/alias et acquisition
copy relus dans `tests/analysis/test_ocr_correspondence.py` et
`tests/extract/test_ocr_native_source_correspondence.py`. Revue statique seulement,
sans nouveau run ; aucune nouvelle gate cochée ni étape 3 clôturée.
**État remplaçant ces checkpoints intermédiaires : contrats correctifs 3 acceptés,
GO4 donné.** Checkpoint consumer relu :
`results/correction_source_contracts_phase3_consumer_20261011/checkpoint.md`.
Union unique dix fichiers **282 passed, 7 deselected, 53.87 s, exit 0, zéro warning**,
session **65737 close**. XML relu, 282 cas, 0 failure/error/skip, 53.871 s,
timestamp `2026-10-12T07:36:40.653099+00:00` ; SHA vérifié
`16248414ea40e356ec6b89a189106cd37b4939fa873806e62cdc9911fc27de97`.
17 cas producteur et 84 consumer inclus dans 282, pas ajoutés aux mini-lots.
Commande archivée au checkpoint : OCR local désactivé, `not real_cpu` ; les sept
cas réels désélectionnés ne sont pas déclarés GREEN. Ancien legacy spy corrigé
et GREEN dans l'union, ancien FAIL conservé dans les preuves.

Deux vrais CLI de couverture toujours NON exécutés, reste partagé avec l'étape
corrective 6 ; pas de succès empirique déduit des mocks ni de xfail/bypass.
La vérification runtime noOCR sur bon texte natif reste également en 6.
Cases contractuelles 3 documentées/cochées dans le todo ; pas qualification
de toutes les correspondances split/join ou géométries/paint non résolus.
GO4 Hubble : `analysis/provenance.py`, `render/reflow.py`, `render/render_plan.py`,
contrats 3 préservés ; étape 5 HOLD, 6 sans GO. Le gel 3 reste daté, pas baseline
future du code étape 4. La numérotation universelle reste celle du tableau
principal et ses critères ne sont pas effacés par ce passage de gate.

### P1 du chemin utilisateur bbox : couverture du plan différente du XML final

Constat lecture seule Pascal transmis par le parent, branches relues par Arendt :
`scripts/reconstruct_bbox_native.py:253`/`:255` utilise les remplissages bbox avec
le plan unique. `render/bbox_debug.py:620` saute les containers autres que image/
shape ; `:1098` saute text=None. Or `render/render_plan.py:584`/`:586` programme
TABLE/LINK sans instructions textuelles. Ces deux classes n'ont donc pas de
consommateur dans ce chemin final, même si le plan et sa couverture sont valides.
Pas un défaut par ID/document/langue : le dispatch général omet des types pris
en charge par le plan. Aucun rendu de PDF particulier exécuté pour ce constat.

Ne pas confondre garde de plan et contrôle de sortie : `bbox_debug.py:435`
valide le plan, mais `:1110`/`:1112` réécrit le ZIP final sans appeler le validateur
package final, ni produire mapping source/objet XML et audit exhaustif. La
validation éventuelle du package vierge en amont ne couvre pas sa sortie mutée.

Pascal reçoit un nouveau fichier RED et une proposition de façade déléguant le
backend unique existant. Production interdite avant gel 5, pas deuxième renderer
tables/liens ni règle sur PDF ID. Preuves RED/commande/chemin encore attendus,
P1 non corrigé. Gates universelles backend/facade, tous points d'entrée, types,
package/mapping/audit sections 13-19 et comparaison/tests/critères 22-24 ouvertes.
Acceptation corrective 3 sur gel 282 GREEN conservée, Hubble GO4 préserve ce
contrat ; corrective 5 HOLD, 6 sans GO. Aucun switch ou clôture globale déduit.

### Processus anciens et gates globales restantes

Contrôle autoritatif hôte en lecture seule hors sandbox le 12 à 07:28-07:29 UTC :
`ps -C python,python3,python3.10,python3.11,pytest,soffice,soffice.bin,oosplash -o pid,ppid,lstart,etime,stat,args`
ne renvoie que l'en-tête (exit 1, aucune correspondance), de même que
`ps -p 1003788,1024095 -o pid,ppid,lstart,etime,stat,comm` pour les deux anciens
PID conversion/suite. Aucun lock n'est interprété comme activité. Aucun processus
relancé ou tué ; recontrôle au GO6 requis, une observation n'est pas un gel futur.

Rapports historiques relus : release `20261011T112019Z`, handle 9542 terminé,
1047 passed/2 failed/1 skipped, cinq conversions non lancées ; intégration IA
`20261011T125131Z/report.json`, handle 99619 terminé et enfants attendus, union
330 GREEN puis deux échecs de couverture séparés, même signature/six IDs que
le release antérieur. Sonde native 58469 close exit 130 sur demande. Ces essais
ne sont pas réexécutés ni utilisés comme baseline du code courant.

- [ ] Après les contrats correctifs 3 acceptés sur gel 282 GREEN, terminer 4 puis 5 avec revue/freeze et preuves propres, puis les vérifications runtime/CLI en 6 ; consolider tous les prérequis B1-B4/canonique avant nouvelle clôture universelle 0-3.
- [ ] Finir toutes les actions fonction par fonction des sections 4-22 : contrats/metadata, acquisition non destructive, sémantique/décisions/options, tous points d'entrée/backends, package et mappings source/XML ; aucun switch par défaut prématuré.
- [ ] Après gels et GO6, vérifier une seule fois les lots approuvés, vrais CLI/lecteurs, hashes avant/après, pages exactes et diagnostics ; corpus diagnostic borné distinct du golden universel.
- [ ] Phase universelle 4 : backend unique et façade sans décisions concurrentes, pas de planning pendant XML, décisions ancien/nouveau comparées sur corpus, profils lecteurs effectivement testés.
- [ ] Phase universelle 5 : audit exhaustif de chaque source/sortie (ordre/multiplicité, courts/liens/RTL/CJK, quad/angle/baseline, métriques/styles/visibilité/édition), corrections locales bornées du plan avec rollback/rerender/re-audit ; non mesuré=`null`, absent critique bloquant.
- [ ] Douze familles golden réelles avec sept artefacts reliés chacune, toutes pages/mappings et preuves des lecteurs/version : Word ET LibreOffice, pas un profil déclaré pris pour exécution. Manifestes historiques incomplets préservés, synthétiques non promus en documents réels.
- [ ] Fermer les dix critères de réussite section 24 ci-dessous sur toutes les classes, pas seulement les sept cas proposés ; sources/écartés/décisions/risques expliqués.
- [ ] Phase universelle 6 seulement ensuite : tous appelants migrés, wrappers dépréciés comparés/testés, suppression des dix catégories section 20 puis revalidation complète. Aucune suppression autorisée par le seul GO6 correctif.

Budget phase 6 correctif préparé dans
`results/corrections_conservation_phase6_budget_20261011.md` : mesures mémoire
datées du 11, à rafraîchir au GO, aucune inférence/CLI lourde concurrente,
suite isolée par root sémantique inexistant et CLI seule root Vysi pour au plus
un shadow réel par conversion. Aucun modèle/CLI/pytest/corpus lancé dans cette
reprise documentaire ; aucun handle Arendt actif.

## Reprise vérifiée du 2026-10-11

**Historique daté conservé.** Les états « actuel », « RUNNING », « RELEASED » et
consignes de ce chapitre décrivent leurs checkpoints du 11 octobre, avant la
pause explicite puis reprise du 12 ci-dessus. Ils ne constituent pas un nouveau
GO de suite/corpus et ne remplacent pas l'état courant en entrée.

### Périmètre, processus et baseline

- Lecture intégrale du plan et du suivi, inspection de l'état Git sale et recherche
  de `AGENTS.md` dans le dépôt et ses parents : aucun fichier trouvé. Les changements
  de production et de tests déjà présents sont conservés. La vérification initiale
  ne modifie que le présent suivi et crée un nouveau rapport de baseline avec son
  log et son XML JUnit ; aucune correction de production ou de test n'est faite
  pendant cette baseline. L'utilitaire de corpus et ses tests ajoutés ensuite sont
  décrits séparément ci-dessous ; aucun renderer de production n'est modifié ici.
- Plan contrôlé : SHA-256
  `ca6bb1957624836912b6a98a33d3f11b542b69c5165fbfaf3b809b06b3fbed93`.
  HEAD : `03a5b4839773cb1e27ae2255e66307fe59d13a89` ; l'empreinte HEAD seule ne
  décrit pas les changements non commités, d'où les empreintes par fichier.
- À 06:57:37 UTC, contrôle autoritatif de la table des processus **hôte** par
  `ps -eo pid,ppid,lstart,etime,stat,comm`, en lecture seule hors du sandbox :
  aucune ancienne conversion Python, session pytest ou instance
  `soffice`/`soffice.bin`/`oosplash` active observée. Le `ps` du sandbox ne montrait
  que son propre espace de PID et ne pouvait pas établir ce résultat. Aucun handle
  confirmé vivant n'a été relancé. Les fichiers `.~lock` existants restent intacts
  et ne constituent pas une preuve de processus vivant.
- Baseline actuelle lancée **une seule fois**, Python 3.10.20, du
  2026-10-11T06:58:31 UTC au 2026-10-11T06:59:26 UTC environ :

```bash
.converter/bin/python -m pytest -q --ignore=tests/capture_ecran --ignore=tests/visual --tb=short -rs --junitxml=results/refonte_universelle_baseline_20261011T065813Z.xml
```

- Résultat : **792 passed, 1 skipped, 6 warnings in 55.40s ; code retour 0**.
  JUnit : 793 cas, 0 échec, 0 erreur. Le seul test ignoré est
  `tests/render/test_package.py::test_libreoffice_ouvre_le_fichier`, motif :
  `LibreOffice headless ne peut pas convertir dans cet environnement`.
  Les avertissements concernent quatre replis de segmentation IA invalide,
  `pkg_resources` déprécié et l'absence de `ccache`.
- Preuves nouvelles, sans écrasement des résultats antérieurs :
  `results/refonte_universelle_baseline_20261011T065813Z.json`,
  `results/refonte_universelle_baseline_20261011T065813Z.log`,
  `results/refonte_universelle_baseline_20261011T065813Z.xml`.
  Le JSON conserve commande, résultat, HEAD et SHA-256 avant/après de 122 fichiers
  de code/tests/configuration ; **aucune différence pendant la baseline**.
- Les 63 empreintes `code_after` du rapport du 10 octobre correspondent au code
  présent avant cette baseline. Les 60 artefacts de son registre d'empreintes
  existent et correspondent encore à leurs SHA-256 ; les quatre PDF source
  référencés conservent également leurs empreintes. `git diff --check` : code 0.
  Une baseline non visuelle verte ne valide ni le corpus visuel ni les phases.

### Acquis antérieurs retrouvés et limites actuelles

Le rapport `results/verification_couches_texte_natif/validation_couches_texte_natif.json`
est terminé le 10 octobre à 19:11:24 UTC. Il documente 792 tests passés, les couches
source, les angles dirigés, la propagation et l'embedding des polices, une preuve
d'édition native et les régressions Tideman/Katrina/NASA. Ses commandes finales sont
dans `final_stable_commands.json` ; leurs quatre codes de sortie sont 0. Ces acquis
restent des progrès partiels sous la Phase 4, pas sa clôture.

Les PDF LibreOffice de contrôle existent dans
`results/verification_couches_texte_natif/` pour `e03fb6c45305fb13_000588`,
`dc738585d318b299_000019` (3 pages), `0fd83d2aa11747d4_000152` et
`0c6daef79b7165c1_000744`. Ce sont des rendus réels archivés. Le présent contrôle
vérifie leurs empreintes et les résultats consignés ; il ne rejoue pas ces rendus
et ne constitue pas une nouvelle inspection visuelle.

Limites explicites du rapport conservées : police CFF opaque non identifiée,
substitution Trebuchet MS de confiance 0,60 sans équivalence métrique prouvée,
différences de graisse/italique/retours de prose, groupes de transparence non pris
en charge exactement hors du cas isolé graphics-only Normal, compréhension
sémantique en repli géométrique, largeur source 648 pt contre environ 649,162 pt
dans le PDF LibreOffice. `fonts_exact=false` et `pixel_identity=false` ; aucune
certification universelle ou typographique Word n'en découle.

### Affirmations historiques à ne plus reprendre comme état actuel

| Affirmation du journal | Preuve présente et qualification au 2026-10-11 |
|---|---|
| Dernière mise à jour au 9 octobre, suite à 365/370/386 tests | Historique daté conservé ; baseline actuelle 792/1/6, code 0. |
| Phases 0 à 3 « terminées » sans réserve | Quatre P1 reproduits dans l'audit des contrats : plan vide accepté, sources perdues, adaptateurs avec perte, frontières/options non respectées. Clôtures historiques provisoires ; résoudre ces défauts et les autres exigences des sections 4 à 11 avant toute nouvelle clôture. |
| Toujours commencer par créer contrats/tests/RenderPlan | Déjà présents et testés ; contrôler leur couverture effective et combler les écarts, sans recréer des moteurs parallèles. |
| « Faire consommer le validateur par le package » encore entièrement à faire | Au snapshot initial, consommation dans la branche native avec erreurs ajoutées après XML. Garde pré-écriture renforcée ensuite par Lovelace : 23 tests verts et régression 158/1 rapportés par le parent, voir checkpoint ci-dessous. Couverture canonique et autres gates restent distincts. |
| Audits z-order/overflow/polices/éditabilité entièrement « à ajouter » | Les quatre fonctions existent et sont appelées ; leur profondeur, l'association source/XML et leur effet bloquant restent à vérifier. Aucun test direct identifié de ces fonctions ni de `construire_audit_elements`/rollback. |
| LibreOffice ne peut jamais produire le PDF de contrôle | Vrai pour les essais historiques cités et pour le test ignoré de cette baseline dans le sandbox ; quatre exports archivés du 10 octobre ont réussi. Pas de conclusion globale d'indisponibilité ni de disponibilité actuelle hors sandbox. |
| Façade DOCX migrée = backend unique terminé | `construire_document_xml` appelle encore `construire_document_xml_compat`. La branche package legacy ignorait le plan au snapshot initial ; le nouveau garde refuse désormais le plan explicite avec `native_rewriter=False`. Sans plan explicite, le moteur legacy demeure : façade universelle non achevée. |
| Contrat natif conforme sur article/brochure = corpus validé | `phase4_verify_article.json` et `phase4_verify_brochure.json` ont `certification_finale=null` ; `phase5_audit_article.json` a `conforme=false`, 0 page rendue et aucun audit élémentaire. Les comptes XML ne prouvent pas la conformité visuelle. |

### Critères de sortie de Phase 4 : backend unique

Références : phase 4, sections 12 à 16, 18 à 19, étapes 5 à 7 de la section 23.
Cocher seulement avec chemin d'appel, commande et preuve de résultat conservés.

**Réactivation obligatoire des prérequis, audit Pascal du 2026-10-11 :**
`docs/audit_contrats_refonte_2026-10-11.md` contient la matrice des Phases 0 à 3,
les champs/API manquants des contrats et de l'IR, et les sondes R1 à R11.
Les quatre P1 suivants sont reproduits, pas simplement des preuves manquantes.
Cette phrase rapporte le diagnostic daté du11 octobre, PAS quatre échecs
reproduits aujourd'hui : rapprocher B1-B4 des correctifs acceptés et du vrai
RU376/376 avant tout constat courant. Leur portée universelle reste ouverte.
Les validations historiques restent provisoires et ne permettent aucune
activation du nouveau backend par défaut avant résolution et tests de comportement
verts. Le développement préparatoire de Phase 4 ne clôt pas ces prérequis.

- [ ] **B1, couverture avant écriture :** refuser un plan vide pour un document non
  vide ; réconcilier chaque source active/écartée avec une sortie, une transformation
  tracée ou une non-représentabilité motivée. Vérifier les sources absentes du plan
  et faire échouer avant ouverture ZIP, pas seulement ajouter un diagnostic après XML.
- [ ] **B2, non-perte avant scène :** attribuer IDs avant filtres et conserver les
  perdants de déduplication, spans retirés et marqueurs de liste ; relier chaque
  remplacement/fusion aux sources d'origine et à une décision motivée accessible.
- [ ] **B3, adaptateurs sans perte :** faire partager l'identité canonique scène/
  plan ; conserver `z_order=0`, `opacity=0`, origine OCR/native, lignes/spans/quads/
  baselines/styles, clipping/compositing/paths et preuves/historique, sans reconstruire
  un contrat différent à chaque adaptation.
- [ ] **B4, frontières et options effectives :** empêcher les passes frame/colonne
  ultérieures de refusionner des groupes ambigus, respecter
  `preserve_line_boundaries='always'`, et résoudre une seule fois les overrides
  d'options ; vérifier confiance 0,8 sous seuil explicite 0,9 et toutes les passes.

Ces quatre contrôles sont des conditions nécessaires ; les autres exigences des
sections 2 à 11, dont les helpers IR manquants et les snapshots comparatifs, restent
à satisfaire dans la matrice de l'audit avant de clore les Phases 0 à 3.

- [ ] Confirmer d'abord les critères des Phases 0 à 3 contre l'audit des contrats,
  notamment les sources avant/après filtrage et les éléments écartés ; conserver
  tous les écarts des sections 4 à 11 comme travail restant.
- [ ] Faire converger tous les points d'entrée, notamment CLI, package, façade
  legacy et scripts bbox, sur un seul `RenderPlan` préparé avant écriture et un
  seul orchestrateur de matérialisation ; aucune branche cachée par booléen.
- [ ] Achever la portée universelle de l'entrée bbox après correction étroite TABLE/LINK déjà acceptée10/10 et vrai RU/package valide : tous appelants/types, mapping XML et audit complets restent à prouver. Ne pas présenter l'ancien défaut de dispatch comme encore non corrigé dans le scope accepté.
- [ ] Faire déléguer `docx_writer.construire_document_xml` au renderer unique ;
  maintenir le chemin historique seulement comme adaptateur de migration comparé,
  sans décisions propres de page, regroupement, fit, z-order ou filtrage.
- [ ] Terminer `native_contract` en validateur/adaptateur non destructif ; ses
  créations/fusions historiques ne doivent pas constituer un second regroupement.
- [ ] Faire consommer au renderer uniquement les décisions, contraintes, régions,
  styles et orientation déjà validés ; supprimer son pouvoir de classifier ou
  regrouper pendant l'écriture, y compris `_shape_should_overlay` et les branches
  de compatibilité encore actives. Conserver les wrappers jusqu'à Phase 6.
- [ ] Conserver le même ordre total de peinture pour texte, images, formes et
  fallbacks ; produire le mapping `element_id`/sources vers objets XML, sans tri
  par catégories et sans omission silencieuse.
- [ ] Supprimer l'usage des grilles artificielles comme flux général ; les vraies
  tables et tables de layout explicites doivent être distinguées par décision.
- [ ] Déplacer les primitives sans changer leur XML vers `text_backend`,
  `image_backend`, `table_backend`, `shape_backend`, `text_runs`,
  `orientation_backend`, `geometry_adapter`, `font_backend` et `background`, selon
  les fonctions des sections 13 à 19 ; sections déjà mutualisées à conserver.
- [ ] Piloter frames/VML/WPS par un contrat d'orientation, conserver bbox, baseline,
  taille et direction ; texte courbé en segmentation éditable ou fallback local
  explicite, avec risque lecteur déclaré.
- [ ] Conserver police/taille/styles/liens/langue et tracer chaque adaptation ;
  pas de compression, clamp d'interligne ou déformation silencieux.
- [ ] Valider ZIP/XML, relations, médias, polices, numbering, styles et provenance
  pour chaque sortie ; rendre diagnostics du contrat/plan visibles et bloquants
  selon leur gravité, même hors mode verbose.
- [ ] Comparer décisions et rendus du chemin historique et du chemin unique sur
  le golden corpus complet ; prouver les profils Word et LibreOffice testés avec
  risques/fallbacks et preuves des lecteurs effectivement exécutés.

**État constaté au snapshot de baseline, avant les développements concurrents :**
`render_plan`, `reflow`, `section_layout` et `compatibility`
existent ; les backends spécialisés listés ci-dessus ne sont pas présents sous ces
chemins. `package.py:193` sélectionne encore deux moteurs et
`docx_writer.py:2210` reste une façade vers le moteur legacy. La Phase 4 reste
ouverte, indépendamment du résultat de la baseline.

### Critères de sortie de Phase 5 : audit et correction locale

Activation/validation après les critères de Phase 4. Références : section 17,
tests d'audit section 22, étapes 8 et 9 section 23.

- [ ] Émettre un `AuditRecord` pour chaque source et chaque objet produit, y
  compris tables, cellules, liens, formes, rasters, éléments écartés et sorties
  sans source ; rattacher les records au registre canonique et au mapping XML.
- [ ] Contrôler rappel, précision **et ordre/multiplicité** des tokens, bbox/quad,
  angle dirigé/baseline, police/taille/style, visibilité après occlusion/z-order,
  débordement et éditabilité réelle par élément.
- [ ] Détecter page/élément absent, texte court et scripts RTL/CJK sans les exclure
  par tokenisation latine ; un état `missing` doit bloquer le verdict approprié.
- [ ] Agréger par élément, zone et page avec erreurs critiques, corrections et
  non-représentables explicites ; aucun ratio global ne compense une perte locale.
- [ ] Comparer réellement couches, métriques de police et édition DOCX ; les
  diagnostics de doublons `z_index`, taille positive ou nombre global de `w:t`
  ne suffisent pas à valider ces dimensions.
- [ ] Faire de `certifier_et_reparer` une boucle audit -> correction locale tracée
  du plan -> rerender -> audit, bornée par `max_repair_passes` ; zéro passe interdit
  les mutations. Conserver l'audit avant/après chaque correction.
- [ ] Remplacer les retraits/inserts destructifs directs par corrections locales
  avec rollback du plan et provenance ; vérifier aussi l'absence de pertes sur
  les éléments voisins. Aucun raster global silencieux.
- [ ] Conserver une preuve d'éditabilité et des sources remplacées pour tout
  fallback raster ; retour bloquant si un élément critique reste non vérifié.
- [ ] Renforcer comparaison structurelle, edges et alignement de tokens/ zones
  critiques ; moyenne grayscale et nombre de mots restent secondaires.
- [ ] Ajouter des tests d'audit pour texte recouvert, horizontal au lieu de vertical,
  ordre faux à même nombre de mots, fond faux sous image dominante, élément absent,
  doublon natif/OCR, texte intégré à image, fallback local déclaré et rollback.
- [ ] Vérifier `INCOMPLETE` et code CLI d'échec si l'export DOCX->PDF manque, ainsi
  que la validité du dernier rendu après réparation ou restauration.

**Écarts observables :** `AuditRecord` ne porte pas encore toutes les mesures
exigées (ordre, quad, angle/baseline observés, z-order). Le constructeur parcourt
l'IR de sortie, ignore les liens et des textes sans tokens, et utilise des sets de
tokens. Pour une page absente il crée `status="missing"` tandis que
`AuditReport.errors` ne retient que `status="error"`. Les diagnostics structurels
sont partiels. Le budget de passes ne correspond pas encore à une boucle complète.
La suite `tests/test_final_audit.py` contient six tests de couverture visuelle/
rapport ; la recherche dans `tests/` n'identifie pas de tests directs du nouveau
constructeur de records, des quatre audits dédiés ou du rollback. Ces constats
doivent être traités par des tests de comportement lors de l'implémentation.

### Critères de Phase 6 : suppression verrouillée

- [ ] Clore les critères des Phases 0 à 5 avec preuves actuelles et écarts résolus.
- [ ] Pour chaque fonction à déplacer/remplacer/déprécier, inventorier tous les
  appelants, migrer les imports et démontrer l'absence d'appel métier legacy ;
  conserver les wrappers nécessaires pendant la période de compatibilité prévue.
- [ ] Passer tests unitaires, contrats, sémantique, rendu, audit et golden tests
  après migration complète ; expliquer chaque échec, skip et diagnostic.
- [ ] Comparer visuellement toutes les familles golden et vérifier les profils
  Word/LibreOffice. Nommer les lecteurs/version effectivement exécutés sans
  supposer Microsoft Word installé ni prendre un profil déclaré pour un essai réel.
- [ ] Supprimer seulement après ces preuves les dix catégories de la section 20 :
  filtres d'intersection, décisions locales concurrentes, regroupements dupliqués,
  seuils renderer cachés, grilles générales de flow, compression silencieuse,
  raster global sans rapport, scores globaux seuls, couches triées par catégorie,
  `FlowParagraph` final créé par extracteur avant décision.
- [ ] Rejouer les vérifications pertinentes après suppression ; publier registre
  final des pertes/non-représentables, diagnostics expliqués et verdict par cas.

### Registre de couverture des sections 4 à 22

Chaque ligne reste ouverte jusqu'à un rapprochement **fonction par fonction** des
actions conserver/déplacer/remplacer/supprimer/transformer du plan avec code,
appelants et tests. La présence d'un module ou un test nominal ne clôt pas sa ligne.
L'audit `docs/audit_contrats_refonte_2026-10-11.md` est maintenant disponible : ses
matrices et sondes établissent les quatre P1 de réactivation ci-dessus. Ce suivi
reprend ses conclusions ; il n'écrit pas dans le fichier de l'autre worker.

- [ ] **Section 4, IR :** compléter métadonnées/confiances de tous les types,
  provenance/édition/fallback, pages/options/registre, helpers `iter_elements`,
  `element_text`, `element_source_ids`, `element_geometry`, clone et validation ;
  aucune décision cachée ni paragraphe final fabriqué par extraction.
- [ ] **Section 5, document :** acquisition seule, registre avant filtrage, sources
  natives/OCR par zone, relations non destructives image/texte/table/formule,
  regroupement universel, frames concurrents, géométrie/quantification unique,
  fallback local motivé et inventaire de chaque élément conservé/écarté.
- [ ] **Section 6, texte :** `FontResolution` et `TextRecoveryResult` explicites,
  ToUnicode/glyph IDs/ordre, confiance d'espacement/lisibilité, quad/baseline/script,
  source de chaque span/ligne ; supprimer le filtre dur de lisibilité.
- [ ] **Section 7, blocs/images/layout/orientation :** candidats de blocs scorés,
  hash/alpha/dimensions/clip/peinture, vues sans filtrage, remplacements proposés
  avec confiance, candidats de frames classés, orientation/courbure/sens complets.
- [ ] **Section 8, sémantique :** implémenter et centraliser toutes les fonctions
  script/langue/frontières/listes/frames/colonnes/validation, seuils en options,
  ambiguïtés conservées, groupes établis avant matérialisation.
- [ ] **Section 9, compréhension :** hypothèses de rôles, preuves/confiances et
  occlusions liées aux IDs ; remplacer filtres/protections destructifs par
  annotations/contraintes, déplacer géométrie et ordre de lecture.
- [ ] **Section 10, planner :** décisions avec IDs/raisons/conflits/fallback,
  projections compatibles sans retrait direct, annotation et résolution de conflits,
  dépréciation contrôlée de `filtrer_elements_selon_plan`/`plan_regions`.
- [ ] **Section 11, IA texte :** modèle/prompt/version/réponse brute, schéma strict,
  inconnus et conflits explicites, fusion AI/native avec confiance ; aucune écriture
  directe dans l'IR final ni suppression par simple suggestion IA.
- [ ] **Section 12, contrat natif :** diagnostic par ID/mode/perte/risque, inspection
  runs/frames/ancres/relations/provenance, adaptateur sans second regroupement,
  migration de toutes les fonctions sémantiques et de création autonome.
- [ ] **Section 13, rewriter :** point unique sur scène/plan validés, mapping XML,
  aucun regroupement/classification/fit implicite, régions déjà décidées, ordre de
  peinture total, texte natif et orientation pilotés par contrat/profil.
- [ ] **Section 14, writer :** façade déléguée, transfert tables/sections/ancres/
  runs/fonds/reflow/colonnes/contraintes ; absence de politiques propres et grilles
  générales ; adaptations typographiques et verticales explicites et auditées.
- [ ] **Section 15, drawing :** primitives seules, séparation geometry/orientation/
  text_runs/table/shape, z-order/wrap uniforme, styles/liens/langue, crop/alpha/
  provenance, géométrie des cellules et paths/clipping/transparence conservés.
- [ ] **Section 16, package :** emballage seul avec plan explicite, relations
  dédupliquées/mappées, fonts/métriques/substitutions diagnostiquées, validation de
  toutes les parties OOXML et manifeste interne source/plan pour audit.
- [ ] **Section 17, audit :** tous les champs/agrégations/mesures et fonctions
  prévus, corrections du plan avec rollback/rejeu, métriques globales secondaires ;
  appliquer tous les critères détaillés de Phase 5 ci-dessus.
- [ ] **Section 18, CLI :** pipeline fixe complet, délégation des décisions,
  profils balanced/visual-first/editable-first/Word/LibreOffice, options validées et
  code d'erreur pour perte critique ou vérification manquante.
- [ ] **Section 19, backends :** fonctions de construction/ordre/index/fallback du
  plan, six modes texte, quatre modes image, quatre fonctions table, cinq fonctions
  shape et capacités/fallbacks/risques lecteur centralisés, sans moteurs concurrents.
- [ ] **Section 20, suppressions :** inventaire exhaustif des dix catégories,
  appelants migrés et preuves ; suppressions uniquement à la Phase 6 autorisée.
- [ ] **Section 21, options :** structure unique pour source/provider/langue/
  détection/priorités/profil/fallback/audit/budget, snapshot transmis de bout en bout ;
  aucune option ne désactive provenance/z-order/non-perte/vérification.
- [ ] **Section 22, tests :** contrats, sémantique (dont CJK/arabe/capitales,
  adresses/titres/captions/crédits), tous modes de rendu et cas d'audit adverses ;
  corpus et artefacts complets ci-dessous, avec verdict et diagnostics expliqués.

### Golden corpus : douze familles et sept artefacts par cas

Pour **chaque cas**, conserver les sept artefacts reliés par identifiants et
empreintes : **PDF source, scène IR canonique, RenderPlan, DOCX, PDF de contrôle,
AuditReport et verdict**. Un catalogue `.extraction.json`, un log contenant les
comptes du plan ou un PDF de rectangles ne remplacent pas à eux seuls la scène,
le plan sérialisé, l'audit ou le PDF réellement rendu du DOCX.

- [ ] Brochure type St. Lawrence : sept artefacts et comparaison ancien/nouveau.
- [ ] Article à deux colonnes : sept artefacts et ordre de lecture vérifié.
- [ ] Formulaire : sept artefacts, structure et champs/contenu conservés.
- [ ] Tableau irrégulier : sept artefacts, cellules/fusions/bordures et contenu.
- [ ] Carte vectorielle : sept artefacts, paths/clips/peinture et labels.
- [ ] Scan incliné : sept artefacts, OCR/orientation/confiances/fallback déclaré.
- [ ] Texte vertical : sept artefacts, sens/angle/baseline/bbox/taille/édition.
- [ ] Texte courbé : sept artefacts, mode segmenté éditable ou fallback explicite.
- [ ] Image avec texte intégré : sept artefacts, provenance et non-duplication.
- [ ] Polices Type3 et substitutions : sept artefacts, identité/métriques/pertes.
- [ ] Transparence et clipping : sept artefacts, compositing supporté et limites.
- [ ] Document RTL/CJK : sept artefacts, direction, ordre et tokenisation adaptés.

La taxonomie existante `docs/corpus_taxonomy_pdf_native.json` décrit le corpus
source ; elle n'est pas le registre de validation golden exigé. Aucun registre
complet reliant ces douze familles aux sept artefacts n'a été identifié dans
`tests/`, `docs/` et `results/` lors de l'inspection initiale. L'inventaire partiel
ajouté ensuite est détaillé ci-dessous. Les quatre régressions
archivées sont à préserver et intégrer, sans les compter comme douze familles
certifiées ni réduire le chantier au dernier PDF.

### Inventaire golden et utilitaire isolé, 2026-10-11

**Harness existant inspecté :** `tests/visual/harness.py` réutilisable pour SSIM et
origines/baselines, mais `comparer()` ne compare que `min(nombre_source,
nombre_sortie)` pages et ne conserve pas scène/plan/audit/verdict. Son export
LibreOffice n'enregistre pas le profil isolé, la version du lecteur ni les empreintes
liant DOCX et contrôle. `scripts/reconstruct_bbox_native.py` extrait une fois,
prépare un plan et conserve catalogue texte/DOCX/PDF annoté, mais ne persiste pas
la scène canonique, le plan consommé, un contrôle DOCX réellement rendu ou un
AuditReport. `SceneDocument.snapshot()` et `exporter_manifest_render()` sont les
points de réutilisation pour la collecte, sous réserve des quatre P1 ci-dessus.

**Écritures supplémentaires autorisées après la baseline :** nouveaux fichiers
`scripts/validate_golden_corpus.py` et `tests/test_golden_corpus.py`. Aucun fichier
de production, script bbox existant ou test appartenant aux autres workers n'est
modifié. Le vérificateur lit un manifeste explicite, valide la présence et la
structure minimale des sept artefacts, calcule leurs SHA-256 et contrôle pagination
et preuve de rendu liée aux empreintes/version/lecteur/code retour. Il ne convertit
ni ne répare, et ne certifie jamais `OK` : au mieux `READY_FOR_REVIEW`, sinon
`INCOMPLETE`. Tout nouveau rapport est créé en mode exclusif, sans écrasement.

**Commandes exécutées :**

```bash
.converter/bin/python -m pytest -q tests/test_golden_corpus.py
.converter/bin/python scripts/validate_golden_corpus.py results/refonte_universelle_golden_inventory_20261011T070821Z.manifest.json --root /home/raphael/Mes_Projets/converter --out results/refonte_universelle_golden_inventory_20261011T070821Z.json
```

Tests : **7 passed in 0.09s, code 0**. Inventaire : **code 3, `INCOMPLETE`**,
12 lignes de familles, **0/12 avec preuves complètes**. La baseline globale 792/1/6
reste celle du snapshot antérieur aux nouveaux utilitaires et aux modifications
concurrentes ; elle n'a pas été relancée ni présentée comme validation de ces ajouts.

Dans la matrice suivante « oui » signifie fichier présent et structure minimale
lisible, pas conformité visuelle. Plusieurs lignes réutilisent le même PDF : elles
ne représentent pas douze documents distincts ni douze familles confirmées.

| Famille | Source/candidat | Source | Scène | Plan | DOCX | Contrôle | Audit | Verdict |
|---|---|---|---|---|---|---|---|---|
| Brochure | `63980...000582`, 2 pages, fixture historique | oui | non | non | oui | non | non | non |
| Article à deux colonnes | `e03fb...000588`, famille dans taxonomie | oui | non | non | oui | oui | non | non |
| Formulaire | Non identifié | non | non | non | non | non | non | non |
| Tableau irrégulier | `5c4cc...000155`, table candidate seulement | oui | non | non | non | non | non | non |
| Carte vectorielle | `0688...000029`, vectoriel dense, carte non confirmée | oui | non | non | non | non | non | non |
| Scan incliné | `6885...000282` p.110, scan, inclinaison non établie | oui | non | non | non | non | non | non |
| Texte vertical | `e03fb...000588`, directions source/LO archivées | oui | non | non | oui | oui | non | non |
| Texte courbé | IR synthétique testé, PDF golden non identifié | non | non | non | non | non | non | non |
| Image avec texte intégré | `0c6d...000744` p.1, texte bitmap intégré non confirmé | oui | non | non | oui | oui | non | non |
| Type3 et substitutions | `e03fb...000588`, substitution CFF, Type3 non identifié | oui | non | non | oui | oui | non | non |
| Transparence et clipping | `e03fb...000588`, groupes Normal, clipping complet non établi | oui | non | non | oui | oui | non | non |
| RTL/CJK | Non identifié | non | non | non | non | non | non | non |

Les chemins complets, pages sélectionnées, preuves de classement, empreintes et
motifs par rôle sont conservés dans le manifeste et le rapport JSON cités. Les PDF
de contrôle existants restent reconnus comme exports réels historiques ; leur
version de lecteur n'étant pas consignée, la liaison complète exigée pour un
nouveau passage du harness reste à collecter. Les catalogues/logs/rapports globaux
historiques sont conservés comme preuves secondaires, sans être renommés en scène,
plan canonique ou AuditReport absents.

**Proposition concrète de collecte après stabilisation des prérequis :**

- [ ] Réutiliser l'extraction unique du runner bbox et persister la scène source
  canonique avant normalisation/filtrage, avec options, provenance, état des
  écartés et empreinte du source ; ne pas reconstruire une scène depuis le catalogue.
- [ ] Persister le plan exact consommé par chaque chemin comparé et les diagnostics/
  mappings disponibles ; rendre explicite une donnée manquante au lieu de fabriquer
  une décision historique ou une équivalence ancien/nouveau.
- [ ] Produire les DOCX ancien/nouveau dans un nouveau répertoire daté, puis invoquer
  le rendu de contrôle existant avec profil isolé et enregistrer commande, version
  effective, code retour, pages, SHA-256 entrée/sortie et avertissements.
- [ ] Réutiliser uniquement l'audit observationnel sur le vrai PDF de contrôle,
  conserver AuditReport et verdict qualifié ; pas d'appel à
  `certifier_et_reparer`, pas de réparation Phase 5. Marquer `INCOMPLETE` si rendu,
  couverture source/plan/audit ou lecteur réellement vérifié manque.
- [ ] Comparer toutes les pages sélectionnées sans troncature par `min`, relier les
  sept artefacts et conserver toutes les sorties anciennes. Aucun backend de rendu
  supplémentaire ni activation par défaut avant les quatre P1 verts.

### Collecteur observationnel isolé, 2026-10-11

Mission suivante autorisée : scripts, tests et nouvelles sorties seulement, sans
modification du package, des backends ni de l'audit de production par ce worker.
Le collecteur `scripts/collect_golden_corpus.py` réutilise le manifeste du
vérificateur, sans déduire une famille ou une politique depuis le nom d'un cas.
Il traite les cas séquentiellement et conserve les sept rôles d'artefacts ; un
artefact non produit reste absent, jamais remplacé par un faux résultat.

**Implémenté et vérifié sur mocks/fixtures, pas sur le corpus réel :**

- [x] Extraction par l'API `extraire`, scène fournie ou factory
  `scene_from_legacy_document`, snapshot avant préparation du plan ; export strict
  supplémentaire du contrat de scène quand c'est un dataclass. Les types non
  sérialisables font échouer la collecte au lieu d'être convertis silencieusement
  en chaînes. La complétude de l'acquisition brute n'est pas affirmée.
- [x] Plan réel de `build_document_render_plan`, sérialisation des décisions,
  sources, couverture et instructions de matérialisation ; transmission du même
  objet à `ecrire_docx(..., native_rewriter=True, render_plan=plan)` pour cet outil
  explicite seulement. Aucune activation par défaut du pipeline n'en découle.
- [x] Validation centrale liée au document si l'API l'expose, contrôle pages/
  sources avant écriture, puis détection de mutation du plan après writer/audit.
  Les preuves de transformation/doublon restent du ressort du validateur central.
- [x] Copie du PDF source complet, sélection explicite conservée dans l'ordre
  demandé, sous-PDF de comparaison pour les pages non contiguës. Aucun `min` sur
  les nombres de pages ; tailles raster différentes signalées sans crop silencieux.
- [x] Options demandées et effectives, SHA-256 source/code/config/tests avant/après,
  diagnostics writer et étapes/erreurs conservés. Arrêt avant le cas suivant si
  le code change ; un nouveau répertoire est obligatoire, sans écrasement.
- [x] Export LibreOffice instrumenté suivant le harness existant, profil temporaire
  isolé, commandes/version/code/stdout/stderr et liaison SHA-256 DOCX/PDF. Cette
  invocation est testée avec subprocess simulé, pas exécutée sur le corpus ici.
- [x] Appel uniquement à `construire_audit_elements` sur les éléments réellement
  préparés et le vrai contrôle quand disponible ; conservation des records,
  couverture d'IDs et états non `ok`, sans utiliser son agrégat comme certification.
  Aucun appel à `certifier_et_reparer`, aucune correction Phase 5.
- [x] Verdict toujours `INCOMPLETE` dans cette version observationnelle : audit
  actuel explicitement partiel, contrôle manquant ou simulé jamais promu en
  réussite. Le vérificateur rejette désormais les preuves `fixture`/`simulated`
  comme preuve de rendu réel, même avec sept fichiers présents.

**Preuves ciblées :**

```bash
.converter/bin/python -m pytest -q tests/test_collect_golden_corpus.py tests/test_golden_corpus.py --tb=short --junitxml=results/refonte_universelle_collector_fixture_20261011T072733Z/tests.xml
.converter/bin/python scripts/collect_golden_corpus.py --check-api --out-dir results/refonte_universelle_collector_api_20261011T072901Z
```

- Tests : **21 passed in 1.94s, code 0**, JUnit 21 cas, 0 skip/erreur/échec.
  Le test API utilise scène/plan/writer réels sur un petit IR synthétique ;
  extraction, lecteur et audit y sont simulés. Il ne prouve aucune fidélité visuelle.
- Les empreintes globales avant/après ces tests diffèrent sur quatre fichiers
  concurrents : `analysis/provenance.py`, `extract/document.py`,
  `render/render_plan.py`, `tests/analysis/test_plan_source_coverage.py`.
  Les fichiers du collecteur restent identiques. Ne pas présenter ce passage
  ciblé comme baseline globale stable ni rejouer la baseline 792/1/6 pour le masquer.
- Rapport détaillé avec empreintes complètes, commandes et qualifications :
  `results/refonte_universelle_collector_validation_20261011T072901Z.json`.
  Logs/XML : répertoire `results/refonte_universelle_collector_fixture_20261011T072733Z/`.
- Exemple archivé dans son sous-répertoire `observation/` : PDF synthétique de
  trois pages, sélection `[3, 1]`, pipeline/lecteur **simulés**, sept fichiers
  structurellement présents, `render_evidence_bound=false`, verdict `INCOMPLETE`.
  Famille non confirmée ; cet exemple n'ajoute aucun cas golden validé.
- Checkpoints API successifs conservés, sans remplacement :
  `results/refonte_universelle_collector_api_20261011T072317Z/`,
  `results/refonte_universelle_collector_api_20261011T072553Z/`,
  `results/refonte_universelle_collector_api_20261011T072901Z/`.
  Dernier passage : code 0, imports/signatures reconnus, code inchangé pendant
  ce checkpoint ; aucune conversion exécutée.

**B1, nouvelle observation bornée et ownership :** le dernier checkpoint reproduit
le document non vide/plan vide sur page 7 ; `native_contract.conforme=false`, erreur
`missing-source-inventory:probe-source`, writer non appelé. La lecture du package
modifié en parallèle montre maintenant le refus avant fonts/XML/ZIP et le refus
d'un plan explicite sur la branche de compatibilité. Le fichier de l'autre owner
`tests/render/test_b1_package_source_gate.py` couvre ces branches et la préservation
de destination ; il a été lu, **pas exécuté par ce worker**. Aucun patch de
production supplémentaire proposé sur ce travail déjà possédé : rapprocher les
résultats de l'owner et les autres sondes avant de cocher B1 ou les Phases 0 à 3.

**Besoins API communiqués au parent pour Hubble/Pascal :**

- [ ] Hubble : garder le plan/instructions exacts sans mutation pendant XML ;
  exposer un mapping source/objet XML exploitable par l'audit exhaustif. Les
  diagnostics actuels ne constituent pas ce mapping complet.
- [ ] Pascal : exposer une scène/observation brute immuable avant filtres et
  garantir son registre ; compléter le passage de `AnalysisOptions` à l'extraction,
  qui n'accepte toujours pas cet objet partagé au checkpoint. Les arguments
  effectifs d'extraction sont enregistrés séparément, sans prétendre le contraire.
- [ ] Stabiliser les contrats et obtenir les résultats des quatre P1 avant un
  passage réel du collecteur ; aucune conversion lourde n'a été lancée pendant
  les mutations des deux owners.
- [ ] Identifier/qualifier les douze familles réelles et collecter les sept
  artefacts réels par cas, avec lecteurs/version effectivement exécutés. Le profil
  demandé dans les options n'est pas la preuve de Microsoft Word exécuté.
- [ ] Après Phase 4 seulement, achever l'audit exhaustif source/sortie, les mesures
  locales manquantes et les corrections bornées de Phase 5 ; Phase 6 reste verrouillée.

### Mesures qualifiées et checkpoint Lovelace, 2026-10-11

**Renforcement du collecteur demandé après le premier checkpoint :**

- [x] Chaque record exporté distingue `available_measures` et
  `unmeasured_requirements`. Ordre/multiplicité, quad/angle/baseline, identité/
  taille/style/métriques de police, visibilité/occlusion/z-order/overflow,
  éditabilité, précision des objets de sortie et binding source/XML non prouvés
  sont exportés à **`null`**, jamais à une valeur parfaite par défaut.
- [x] Les scores tokens ensemblistes sont nommés proxies ; la similarité d'une
  région visuelle n'est plus présentée comme rappel/précision de tokens. Un IoU
  nul par défaut ou une liste vide de styles ne prouve pas une mesure effectuée.
  `raw_report` conserve la sortie originale pour provenance seulement, avec une
  politique explicite interdisant d'en lire les valeurs par défaut comme des mesures.
- [x] Records `error` **et `missing`** répertoriés comme critiques ; `ok` brut
  devient `unverified` dans l'export qualifié. Aucun agrégat `conforme` n'est utilisé
  pour rendre `OK` ; sept fichiers et PDF LibreOffice ne lèvent pas les critères
  manquants. Le verdict reste `INCOMPLETE`.
- [x] Empreintes du source original/copie/sélection et du DOCX/PDF de contrôle
  avant/après observation ; mutation signalée explicitement. Un test altère
  volontairement source et contrôle et vérifie cet échec.

Nouveau passage ciblé, distinct des snapshots conservés :

```bash
.converter/bin/python -m pytest -q tests/test_collect_golden_corpus.py tests/test_golden_corpus.py --tb=short --junitxml=results/refonte_universelle_collector_fixture_20261011T073406Z/tests.xml
.converter/bin/python scripts/collect_golden_corpus.py --check-api --out-dir results/refonte_universelle_collector_api_20261011T073406Z
```

Résultat : **23 passed in 2.37s, code 0**. Checkpoint API : code 0, imports et
signatures reconnus, B1 vide/non-vide rejeté, aucune conversion, code inchangé sur
ce checkpoint. Empreintes avant/après tests ciblés : modifications concurrentes
sur `analysis/provenance.py`, `tests/analysis/test_plan_source_coverage.py` et
`tests/analysis/test_upstream_source_contracts.py`, pas sur les fichiers possédés
du collecteur. Pas de conclusion de stabilité globale.

Rapport complet :
`results/refonte_universelle_collector_validation_20261011T073406Z.json`.
Nouvelle fixture simulée conservée séparément dans
`results/refonte_universelle_collector_fixture_20261011T073406Z/observation/` :
sept fichiers présents, rendu réel non établi, famille non confirmée,
`INCOMPLETE`, source/contrôle inchangés pendant cette observation. L'exemple et les
rapports précédents ne sont ni remplacés ni promus en golden réel validé.

**Avancement transmis par le parent, attribution Lovelace, non rejoué ici :**

- [x] Sous-gate **package/native_guard B1 : 23 tests GREEN**, garde pré-écriture
  complet selon le rapport de l'owner. Ce sous-gate ne coche pas le B1 canonique
  ni l'ensemble des prérequis des Phases 0 à 3.
- Régression rapportée : **158 passed, 1 skipped in 25.84s**, incluant
  matérialisation/sourcepaint Hubble et fichiers de compatibilité legacy ;
  `git diff --check` code 0. Le motif du skip, la commande et les empreintes exactes
  restent à rapprocher du rapport de l'owner ; ils ne sont pas inventés ici.
- Tranche suivante possédée par Lovelace : validation OOXML atomique et manifeste
  package, préparée sans switch du backend par défaut. Ce worker ne modifie aucun
  de ces fichiers de production.
- [ ] Couverture canonique et autres gates des owners toujours non clos ; aucune
  phase globale cochée, aucun corpus lourd lancé et aucun travail Phase 5/6 activé.

### Readiness des sources et release, 2026-10-11

**Aucune conversion, aucun lecteur ni pytest lancés dans cette tranche.** Le
scope se limite aux manifestes, observations PDF source et présent suivi : aucun
fichier de production, collecteur ou test modifié. Aucun signal de full suite
n'est reçu ; le gel du scope Pascal ne vaut pas gel global.

Dossier nouveau, sans écrasement d'anciens snapshots :
`results/refonte_universelle_release_readiness_20261011T074615Z/`.
Le rapport `readiness_report.md` et `api_requirements.json` détaillent les preuves,
limites et besoins à transmettre à Pascal/Hubble/Lovelace. Le catalogue existant
`docs/corpus_taxonomy_pdf_native.json` est réutilisé : 150 PDF, 4184 pages. Sondage
source borné à leurs premières pages et 19 pages candidates, soit 169 pages ;
textes/polices/widgets et géométrie native de dix pages, sans rendu raster ni OCR.
Ce sondage ne prouve pas l'absence d'une famille sur les 4184 pages.

`golden_manifest.json` contient douze familles, chacune avec les sept rôles
d'artefacts requis. Chemins des sources relatifs à la racine du dépôt et SHA-256
réels ; original intégral à conserver en `source.pdf`, sélection séparée explicite.
**Huit appartenances étayées par les sources, quatre cas manquants ; aucune
famille golden validée par un rendu dans cette tranche.**

| Famille | Source réelle et sélection | Preuve source / limite |
|---|---|---|
| brochure | `63980ecfaee8ef36_000582.pdf`, p1-2 | St. Lawrence nommé et lien explicite de brochure p2 ; ancienne incertitude d'identification levée |
| article deux colonnes | `114462c1ca5dfdc4_000347.pdf`, ordre p3, p2 | article Seidel / Journal of Climate ; deux pistes natives x 68-296 et 308-536 pt |
| formulaire | `ed65a432e4091cf9_000018.pdf`, p1 | formulaire NTSB rempli, labels/valeurs et bboxes ; pas de revendication de champs interactifs |
| tableau irrégulier | `5c4ccaaadf5acb5b_000155.pdf`, p13 | Rita, en-têtes fusionnés/groupés, sous-colonnes de dommages ; distinct de Katrina |
| carte vectorielle | `077bbf325240285f_000547.pdf`, p7 | RIL CBM BLOCKS, toponymes/frontières, 20270 entrées natives ; rotation PDF 90 |
| scan incliné | **MISSING** | candidat `6885...`, p110/111, bitmap sans texte natif ; inclinaison non établie |
| texte vertical | `4e4a2d80e91be727_000583.pdf`, p1 | crédit PEGGY GREB direction [0,-1], page rotation 0 ; doublon source explicite |
| texte courbé | **MISSING** | candidat carte `0688...`, p1 ; directions variables sans preuve de baseline courbe continue |
| image avec texte intégré | **MISSING** | candidat bitmap `6885...`, p110 ; texte intégré non inspecté, pas inféré de la seule image |
| Type3 et substitutions | `b3eba9bc82a22181_000816.pdf`, p1 | ressource Type3 xref 27 / T1 utilisée dans la trace ; substitution/métriques sortie non mesurées |
| transparence et clipping | `63980ecfaee8ef36_000582.pdf`, p1 | deux groupes opacity 0.600006/0.699997 et neuf clips imbriqués |
| RTL/CJK | **MISSING** | aucun cas réel qualifié par le sondage ; ArialUnicodeMS ne prouve pas le script |

Le partage de source brochure/transparence est déclaré et repose sur deux traits
réels indépendants, pas sur un quota. Le widget `Text4` du rapport juridique
`5370...` ne suffit pas à qualifier un formulaire et n'est pas utilisé. Les quatre
régressions acquises ne remplacent aucune ligne de ce manifeste.

`regressions_manifest.json` et `release_commands.json` préparent séparément
sourceframe/e03 p1, Tideman p1-3, Katrina p1, NASA p1, **et le cinquième cas demandé
`96a80f28f8366209_000751.pdf`, p1**. Ce dernier existe : 2 pages, 384101 octets,
SHA-256 `96a80f28f8366209da9d1073401aaae8ad75207bdf41641c1681fd0ec3308747`.
L'ancien crash `matchTemplate` 382x426 contre 1056x566 px et le rerun CPU à 49 zones
IA sont des acquis historiques documentés, non rejoués ici. Cinq recettes runner
et douze recettes collecteur sont consignées, sorties sous un nouveau
`results/refonte_universelle_release_<RELEASE_ID>/`. Les recettes sans source
qualifiée sont bloquées ; les autres attendent les gates et le signal parent.

**Mapping explicite, mais pas encore observé :** chaque sélection a un tableau
source 1-based / index source 0-based / ordinal sélection-sortie attendu. Les
indices IR réels et ordinals de sortie observés restent `null`. L'article p3,p2
doit donner sortie 1 depuis p3 puis sortie 2 depuis p2 ; la table p13 donne sortie
1 depuis index source 12, pas index 0. Le collecteur doit encore exporter et
contrôler ce binding runtime, ainsi que ses descripteurs d'artefacts relatifs
(ses anciens exports absolus restent conservés). Aucune hypothèse
`page.index == enumerate`, aucun `min` ni troncature de pages autorisés.

Validation d'inventaire seulement, via l'utilitaire existant :

```bash
.converter/bin/python scripts/validate_golden_corpus.py results/refonte_universelle_release_readiness_20261011T074615Z/golden_manifest.json --root . --out results/refonte_universelle_release_readiness_20261011T074615Z/inventory_validation.json
```

Résultat **code 3, INCOMPLETE** : huit cas à 1/7 fichiers (source), quatre à 0/7,
0/12 familles complètes. Vérifications structurées des douze manifestes unitaires,
sélections/maps attendus, séparation des cinq régressions, recettes et entrées
de tests ciblés : aucune erreur. Les quinze empreintes source contrôlées sont
inchangées avant/après. **Aucun pytest ni rendu réel n'en est déduit.**

`readiness_validation.json` conserve les empreintes de code observées
`8fda445fd2b2df92e310cf0e9629f4bf2db77d9343a1daf14cf9daff97774d7b` puis
`6338ec81cb61d078f7b92a526bbda38875c34f82e97493c2593b3492be23b7a2`.
Six changements concurrents : `analysis/geometry.py`, `ir.py`, `scene.py`,
`render/package.py`, `tests/analysis/test_upstream_source_contracts.py` et
`tests/render/test_section16_package_integrity.py`. Il ne s'agit pas d'un gel,
ni de l'empreinte testée par la baseline antérieure 792 passed / 1 skipped.

**Checkpoint parent Pascal, non rejoué ici :** 31 nouveaux tests B2/B3 et lot de
168 GREEN en 2.35s ; scope production figé, append du rapport audit seulement.
Fichiers annoncés : scène/IR, extract document-text-native-ocr, géométrie analyse ;
six helpers IR, source IDs de fabrique, clonage sans perte, ties/inventaire brut,
OCR/angle. Restent partiels font/media/line/table/link, consommation géométrique
complète et limites crops fail-closed. Hubble attend encore deux mutations reflow
et deux anciennes assertions scène après signal Pascal. Aucune phase globale
n'est marquée complète et la full suite n'est pas relancée.

- [ ] Rapprocher les correctifs et preuves B1/B2/B3/B4 avec les matrices du plan
  et l'append audit Pascal ; fermer explicitement couverture canonique et gates
  des owners, pas seulement les sous-lots verts.
- [ ] Compléter, dans le seul scope collecteur/tests proposé, le mapping observé
  source/IR/sortie, les refus de pages perdues/dupliquées/réordonnées/rebasées et
  les chemins relatifs des PDF conservés avec hashes. Besoins API aux trois owners
  consignés dans `api_requirements.json`, sans patch production demandé ici.
- [ ] Qualifier quatre cas réels manquants : scan incliné, texte courbé, image
  avec texte intégré, RTL/CJK. Aucun label forcé ni simulation déclarée golden.
- [ ] Attendre un gel global et signal parent ; revalider alors les processus
  hôte autoritativement, jamais par lock seul, sans redémarrer un handle vivant.
- [ ] Exécuter une seule full suite non visuelle sur l'empreinte figée, lot ciblé,
  cinq régressions et douze collectes séquentielles éligibles ; enregistrer hashes
  avant/après chaque étape et sur tout le lot, arrêter sur mutation sans rerun
  automatique ni écrasement.
- [ ] Produire les contrôles DOCX réels, versions/commandes/codes des lecteurs et
  profils isolés ; LO hôte sur approbation ciblée si nécessaire. `soffice` trouvé
  à `/usr/bin/soffice` n'est pas une preuve d'exécution ; Word reste inconnu/non testé.
- [ ] Garder les audits/verdicts `INCOMPLETE` tant que l'audit exhaustif réel
  manque : ordre/multiplicité, courts/CJK/liens, métriques/styles/visibilité,
  éditabilité et binding objets XML. Non mesuré = `null`, jamais score parfait.
  Sept fichiers, LO réel et `report.conforme` ne suffisent pas à rendre `OK`.
- [ ] Fermer les exigences par module des sections 4-22 et les critères globaux
  section 24, sans activation Phase 5 ni suppression Phase 6 prématurées.

### Checkpoint worker figé, 2026-10-11

**Scripts/tests de ce worker figés ; aucun handle exec encore ouvert.** Seuls
`scripts/collect_golden_corpus.py` et `tests/test_collect_golden_corpus.py` ont été
modifiés dans cette tranche. Aucun fichier de production modifié par ce worker.
Le validator et ses tests restent inchangés, les anciens snapshots sont conservés.

Le collecteur exporte maintenant le mapping source sélectionnée / index IR-scène
réel / ordinal de sortie attendu, contrôle identité et ordre avant écriture puis
après plan/writer, refuse pages rebasées/perdues/supplémentaires/dupliquées/réordonnées
et mappings demandés périmés. Les sept artefacts et la sélection sont liés à des
chemins relatifs avec SHA-256, vérifiés après déplacement de la collecte en test.
Un contrôle avec un nombre de pages incorrect est refusé avant audit, sans `min`.
Un ordinal PDF présent ne prouve pas son contenu source : binding contenu
`UNVERIFIED`, sortie réellement liée non établie, verdict toujours `INCOMPLETE`.

Dernier lot ciblé : **35 passed in 3.13s, code 0**, JUnit 35 cas, zéro échec,
erreur ou skip. Commande :

```bash
.converter/bin/python -m pytest -q tests/test_collect_golden_corpus.py tests/test_golden_corpus.py --tb=short -rs --junitxml=results/refonte_universelle_missing4_20261011T080500Z/collector_tests.xml
```

L'itération précédente 32 passed en 3.48s reste archivée séparément. Aucun lot
complet, aucune conversion ni lecteur réel lancés ici. Pendant les 35 tests, seul
`tests/render/test_section16_package_integrity.py` a changé concurremment ; les
fichiers possédés sont inchangés. `git diff --check` code 0. Empreintes et résultats
complets : `results/refonte_universelle_missing4_20261011T080500Z/availability_checkpoint.json`.

Recherche source complémentaire en lecture seule : premières pages de 100 PDF
`pdf_scanned` et d'un PDF distinct en backup externe accessible. Neuf sources
avec caractères arabes, aucun CJK trouvé sur cet échantillon. Le calendrier
`c9cfee544a325b21_bouarfa_chaoual_1438.pdf` p1 porte un composant RTL réel :
arabe natif et positions x décroissantes dans un mot ; couverture CJK non prouvée.
Le bitmap original xref14/masque15 de
`12254564203abfbc_jarvisimports2000ltd355-2007-9-10_text.pdf` p1 a été décodé et
inspecté : instructions anglais/français intégrées à l'image. PNG original,
empreinte, source/page/xrefs/transform conservés ; ce n'est ni un rendu de page
PDF par le convertisseur ni un PDF de contrôle DOCX. Ce nouveau trait réel n'est
pas promu en golden complet et l'ancien manifeste reste intact.

**Non faits :** générateur et quatre fixtures adversariales synthétiques non
créés, conformément à l'option de restitution bornée disponibilité/état de l'art.
DejaVu Sans arabe et Droid Sans Fallback CJK existent, empreintes/couverture
contrôlées ; Pillow RAQM et PyMuPDF Story/insert_htmlbox sont disponibles. Le
rapport consigne les quatre entrées géométriques indépendantes proposées et la
nécessité de marquer tout futur fixture synthétique, sans le compter comme réel.
Scan incliné, baseline courbe continue et CJK réel restent non établis ; aucun
de ces manques ne bloque les cinq conversions diagnostiques désormais demandées.

Milestones parent, non rejoués : Hubble **319 passed, 6 warnings, 80.47s**, quatre
échecs précédents résolus ; intégration finale crop validator avec Pascal en cours
au dernier checkpoint. Lovelace **183 passed, 1 skipped**, validation package,
atomicité et manifeste en revue finale ; motif du skip non fourni. Aucun de ces
sous-lots ne clôt une phase globale.

**Instruction de lancement actuelle :** attendre seulement le signal explicite
`released` après réception des checkpoints des trois owners production, puis
full suite unique et cinq conversions diagnostiques. Ne plus attendre les
familles supplémentaires ou des fixtures parfaites pour ces diagnostics. Un refus
légitime fail-closed de crop doit être consigné comme refus, sans faux `OK` ; les
gates golden, lecteurs et critères globaux restent distincts et ouverts.

### Release d'intégration autorisé, 2026-10-11

Le parent a explicitement donné `RELEASED integration`. Checkpoints rapportés,
non rejoués séparément par ce worker : Lovelace production figée, **190 passed,
1 skipped**, deux empreintes dans son rapport ; Pascal producteur crop figé,
**37 passed, 1 deselected**, plus 115 tests de régression ; Hubble consommateur
figé, **76 passed en 182.06s** sur plan/media/coverage, sonde une image vers 24
tiles et parent avec `plan.validate() == []`, adversaires inclus. Aucun de ces
résultats ne ferme automatiquement les exigences globales des phases.

À 11:20 UTC, contrôle de la table de processus hôte : la conversion utilisateur
`a92188dd5fa88ea3_000177.pdf` est vivante, PID **1003788** ; elle est laissée
intacte, sans relance ni suppression de lock. Aucun pytest préexistant observé.
La suite unique de ce release est lancée dans un répertoire neuf :
`results/refonte_universelle_release_20261011T112019Z/`.

```bash
.converter/bin/python -m pytest -q --ignore=tests/capture_ecran --ignore=tests/visual --tb=short -rs --junitxml=results/refonte_universelle_release_20261011T112019Z/full_suite.xml
```

État au lancement : **RUNNING**, verdict final ci-dessous. PID pytest hôte
**1024095**, PID 6 dans son namespace sandbox ; handle outil **9542**, conservé
et seulement pollé. Snapshot production avant :
`0ee5e5a22f197cada2443833b242f1b3dd2305bb56454714f7ea352045121b7f` ;
snapshot code/tests/scripts avant :
`8fded6cfe496dc878372e9e537523dee07b8b8fae9a7fc039e695c96f3dddd85`.
Les fichiers `production_before.json`, `code_before.json`, `git_before.json`,
`full_suite_started.json` et le log sont conservés dans ce répertoire. Les
snapshots après et le rapport JUnit qualifié ont été ajoutés à la fin du handle.
Si échec ou mutation, checkpoint avec IDs/traces avant toute conversion ou
nouvelle suite ; corrections seulement par les owners puis nouveau release.

Les cinq diagnostics autorisés sont e03 p1, Tideman p1-3, Katrina p1, NASA p1
et `96a80f28f8366209_000751.pdf` p1. Les familles golden manquantes ne bloquent
pas leur exécution après suite verte stable. Tout refus de crop, artefact manquant,
écart de pages ou limite d'audit sera conservé ; corpus **INCOMPLETE**, sans
certification pixel/police exacte, Word non présumé testé.

**Verdict final de cette exécution unique : FAIL, code retour 1.** Début
`2026-10-11T11:20:20.696092+00:00`, fin
`2026-10-11T11:27:15.535337+00:00` ; pytest **1047 passed, 2 failed,
1 skipped, 6 warnings in 411.79s**. JUnit : 1050 cas, 2 échecs, 0 erreur,
1 skip. Handle 9542 terminé, aucun job de ce worker laissé vivant. Aucune relance
de suite, aucune correction production/test, aucun diagnostic réel lancé.

Empreintes avant/après identiques : 511 fichiers de production non-cache,
SHA-256 `0ee5e5a22f197cada2443833b242f1b3dd2305bb56454714f7ea352045121b7f` ;
137 fichiers code/tests/scripts/configuration,
SHA-256 `8fded6cfe496dc878372e9e537523dee07b8b8fae9a7fc039e695c96f3dddd85`.
Zéro fichier changé dans les deux snapshots. `git diff --check` code 0.

Échecs exacts, présents dans `full_suite.log` et `full_suite.xml` :

- `tests/test_cli.py::test_word_native_rapidocr_reste_page_exacte`, ligne 105,
  `assert code == 0`, obtenu 1.
- `tests/test_cli.py::test_word_native_ecrit_le_diagnostic_de_contrat`, ligne 133,
  même assertion et même code 1.

Les deux stderr affichent `invalid-word-native-contract: uncovered-source` pour
les mêmes six observations :

```text
p0:ocr:TextBox:180a27c01e5e69e45d931f90
p0:ocr:Line:886aecc3d2e6e189abf37875
p0:ocr:Span:283c3308e87ebf227daa1986
p0:ocr:TextBox:eb0e6baaf2508c18d81292a5
p0:ocr:Line:e0c8c0bea4f3c3192d69a8ee
p0:ocr:Span:c5d9d2bcaabef3bdb8f09cd0
```

C'est un défaut d'intégration observé sur `rapidocr / word-native / line`, pas
un refus crop ni une simple absence de preuve golden. La lecture du CLI confirme
la chaîne extraction -> contrat -> package natif ; elle ne suffit pas à attribuer
la cause racine à un owner ou à décider quelle relation OCR manque. Le checkpoint
est remis au parent avant tout edit, pour attribution ciblée producteur/plan.
Ne pas masquer les sources par une exemption ni affaiblir le garde pré-ZIP.

Skip exact : `tests/render/test_package.py::test_libreoffice_ouvre_le_fichier`,
ligne 198, `LibreOffice headless ne peut pas convertir dans cet environnement`.
Ce skip ne vaut ni test lecteur réussi ni impossibilité générale de LO hôte.
Six warnings : quatre replis de segmentation IA invalide (couverture/ordre/
doublons), une dépréciation `pkg_resources`, un avertissement `ccache` absent.
Les logs capturés signalent aussi un provider de compréhension textuelle absent
et un repli géométrique ; ne pas les transformer en preuve sémantique.

Preuves ajoutées sans écrasement : `production_after.json`, `code_after.json`,
`full_suite_report.json`, `failure_checkpoint.json`, en plus du log et du JUnit.
Le checkpoint consumer Hubble publié dans
`docs/checkpoint_phase4_consumer_2026-10-11.md` est lu et référencé ; ses 76 tests
verts restent un sous-lot, distinct de cette régression CLI maintenant révélée.

| Vérification autorisée | État réel après ce checkpoint |
|---|---|
| Suite non visuelle unique | Exécutée une fois, FAIL 2/1050, hashes stables |
| e03 p1, Tideman p1-3, Katrina p1, NASA p1, 96a80 p1 | 0/5 exécutés ; attendent correction attribuée et reprise autorisée |
| PDF bboxes / DOCX / contrôles LO de ce release | Aucun produit ; pas de faux succès ni réutilisation d'anciens rendus |
| Mapping exact, font/layers/alpha/source coverage et screenshots réels | Non faits pour ces cinq diagnostics, toujours à effectuer |
| Golden 12 familles, audit exhaustif, Word et critères globaux | INCOMPLETE ; aucune case globale cochée |

Le release n'est pas annulé et le but global reste actif. Prochaine gate de
vérification : correctif OCR ciblé attribué par le parent, tests propriétaires,
nouveau signal de reprise et nouveau snapshot/répertoire ; jamais relancer
automatiquement la suite rouge ou un handle vivant. Après vert stable seulement,
effectuer les cinq diagnostics, sans attendre les familles golden manquantes.

### Critères globaux finaux du plan, section 24

- [ ] Un seul `RenderPlan` décide du mode de chaque élément.
- [ ] Aucun renderer ne classifie ou ne regroupe.
- [ ] Aucun extracteur ne crée directement un paragraphe final.
- [ ] Décisions ancien/nouveau comparables, divergences tracées.
- [ ] Chaque source retrouvée dans le DOCX ou explicitement non représentable.
- [ ] Audit local détectant les erreurs même sous une image dominante.
- [ ] Corrections applicables et vérifiées sur les autres classes du corpus.
- [ ] Options limitées aux politiques déclarées, invariants toujours actifs.
- [ ] Profils Word et LibreOffice testés, lecteurs réellement exécutés identifiés.
- [ ] Aucune politique concurrente de z-order, regroupement ou filtrage.

**Consigne de reprise actuelle :** traiter les phases dans l'ordre, rapprocher
d'abord les validations historiques des audits des contrats et des chemins
backend, finir les critères de Phase 4 puis Phase 5, et garder Phase 6 verrouillée
jusqu'à satisfaction de tous les critères. Ne pas interpréter cette baseline ou
les correctifs couches/angles/polices comme une clôture de phase.

## Journal d’implémentation

### 2026-10-12 - P1 entrée bbox : matérialisation TABLE/LINK et preuve de sortie

P1 lecture seule Pascal/parent confirmé dans les branches : bbox_debug:620/
:1098 exclut TABLE/LINK planifiés ; :1110 écrit le ZIP final sans validation
package finale/mapping/audit. Le garde de plan présent ne couvre pas cette
omission XML. Pascal reçoit RED + proposition de façade vers backend unique,
production HOLD jusqu'au gel 5 ; pas deuxième renderer ni PDF ID particulier.
Preuves à recevoir, aucune correction déclarée. Acceptation contractuelle 3
sur 282 GREEN et GO4 maintenus ; objectifs/gates universels non réduits.
Arendt docs seulement, aucun run ni handle propre.

### 2026-10-12 - Contrats correctifs 3 acceptés, GO4 Hubble

Union unique finale relue : 282 passed/7 deselected/53.87 s/exit 0/zéro warning,
session 65737 close ; SHA XML `16248414ea40e356ec6b89a189106cd37b4939fa873806e62cdc9911fc27de97`.
Checkpoint `results/correction_source_contracts_phase3_consumer_20261011/checkpoint.md`,
XML 282 cas sans failure/error/skip. Pas de somme avec lots antérieurs.
Acceptation parent et GO4 provenance/reflow/RenderPlan, préservation des contrats
3. Deux vrais CLI non exécutés et gate runtime noOCR restent ouverts/partagés
avec 6 ; étape 5 HOLD, 6 sans GO. Cases contractuelles 3 cochées au todo seulement,
aucune Phase universelle clôturée. Objectif ACTIF entier, anciens checkpoints
intermédiaires du 12 conservés ci-dessous et désormais historiques. Aucun
pytest/modèle/CLI/plan lancé par Arendt, aucun handle propre.

### 2026-10-12 - Étape corrective 3 : preuve producteur et revue indépendante

Checkpoint producteur/SHA et quatre XML relus, détail au chapitre actif et au
todo correctif. 14 GREEN puis mini-lots recouvrants, ancien 195/1 rouge conservé,
17 cas du fichier final non promus en run 17 GREEN. Aucun P1 concret relevé dans
la revue statique acquisition/raw réel, preuve recomputée, événement/identités/
page binding/paint/inventaire et adversaires. Union Hubble 65737 non dupliquée,
résultat/revue parent encore attendus ici ; étape 3 non close, 4/5 HOLD, aucun GO6.
Documentation seule, aucun modèle/test/conversion et aucun handle Arendt.

### 2026-10-12 - Étape corrective 3 : union finale encore vivante

Checkpoint transmis par le parent : gel producteur 17 tests et miniIR/
anti-whitewash clos ; consumer 76 GREEN, huit ajouts boundary/policy, union dix
fichiers handle 65737 annoncée vivante, OCR local désactivé et `real_cpu` exclu.
Pas d'addition, pas de résultat final déduit ; commande/JUnit/code/SHA/revue
restent attendus. Étape 3 non clôturée et aucun GO4 acquis. Étapes 4/5 HOLD,
intégration 6 sans GO ; objectif universel toujours ACTIF dans toute sa portée.
Le constat hôte de 07:28-07:29 ci-dessus précède ce nouveau job, il ne prouve
pas son état actuel. Documentation seule ; aucun nouveau run ni handle Arendt.

### 2026-10-12 - Objectif universel actif, intégration documentaire des six corrections

Reprise explicite du parent consignée dans l'état global et le chapitre du 12.
L'étape corrective 2 est acceptée sur le gel IR/XML 218 GREEN daté, pas sur
le RenderPlan 3 courant modifié. Étape corrective 3 Pascal/Hubble en cours,
4/5 HOLD, aucun GO lourd/corpus avant étape 6. Les anciens états de pause du
11 octobre dans le todo restent historiques, explicitement datés, non actuels.
Correspondance avec toutes les sections du plan et gates globales conservées
ci-dessus ; aucune Phase universelle cochée ni suppression autorisée.
Lecture de preuves/processus seulement, deux suivis modifiés, aucun test ou
modèle lancé et aucune ancienne sortie écrasée.

### 2026-10-09 - Analyse layout universelle obligatoire et branchement spans

**Correction générale implémentée :**

- `pdfexact/extract/document.py` exécute maintenant `analyser_page()` et
  `detecter_layout_ia()` pour chaque page avant les branches de texte. Le passage
  n'est plus conditionné par `text_mode` ou `ocr_layout`.
- `scripts/reconstruct_bbox_native.py` garde le même contrat obligatoire pour son
  orchestrateur unique.
- `pdfexact/cli.py` transmet toujours `layout_ai=True`. L'ancien
  `--no-layout-ai` reste accepté pour compatibilité de commande, mais ne peut plus
  supprimer l'analyse universelle.
- `detecter_layout_ia(..., required=False)` conserve le comportement demandé : une
  panne du moteur n'arrête pas la conversion, mais retourne un statut
  `layout_ai_fallback` et un avertissement explicite.
- `_attacher_frames_texte()` accepte maintenant les zones IA sans plan OCR. Les
  textes PDF natifs du mode `spans` reçoivent donc les mêmes cadres sémantiques
  que les chemins OCR, tout en restant des `TextBox`/runs Word éditables.

**Validation :**

- tests ciblés extraction/layout/contrats : `36 passed, 2 warnings` ;
- le test d'intégration vérifie l'appel layout IA et l'attachement d'une zone au
  texte natif `spans` ;
- compilation et `git diff --check` passent.

**Branchement complémentaire :**

- le même `PageUnderstanding` et le même `planifier_regions()` sont maintenant
  produits pour `spans`/`glyphs` lorsque le chemin OCR n'est pas actif ; ils ne
  déclenchent pas les filtres OCR, mais fournissent le contexte spatial commun au
  renderer et aux cadres des textes natifs ;
- validation intégration élargie : `60 passed, 3 warnings` ;
- suite non visuelle complète après ce branchement : `386 passed, 1 skipped,
  3 warnings`.

**Limites encore ouvertes :**

- le dispatch vers les autres runtimes visuels disponibles dans VYSI n'est pas
  encore complet dans `pdfexact/layout/ai.py` ; le dispatch local PaddleX et
  Ultralytics est maintenant present, mais aucun poids Ultralytics n'est fourni
  dans le corpus VYSI actuel ;
- le benchmark visuel complet et la certification DOCX->PDF restent à exécuter.

### 2026-10-09 - Dispatch local des runtimes visuels

**Fait :**

- `pdfexact/layout/ai.py` ne limite plus la politique à PaddleX : les providers
  `paddlex`, `ultralytics`/`yolo` et `auto` sont dispatchés depuis l'artefact local.
- Le chemin Ultralytics suit le contrat VYSI : poids locaux uniquement, cache par
  provider/modèle/device, exécution CPU par défaut et normalisation vers le même
  `LayoutAIZone` canonique.
- `auto` sélectionne Ultralytics seulement pour un fichier local `.pt`/`.onnx`;
  les répertoires de modèles restent sur PaddleX. Aucun téléchargement implicite
  n'est ajouté.
- Les tests couvrent le choix de provider et le fallback averti d'un provider
  indisponible.

**Validation :**

- suite non visuelle : `386 passed, 1 skipped, 3 warnings` ;
- exécution réelle du PDF PowerPoint de regression en CPU :
  `layout_ai_detected`, `21` bboxes, `10` images/composites, `8` formes,
  `3` blocs texte ; sorties générées dans `results/` ;
- `git diff --check` et compilation Python passent.

**Limite :** le corpus VYSI ne contient actuellement aucun poids Ultralytics
local identifié pour une exécution réelle de ce provider. Le code est branché et
testé par contrat, mais PaddleX reste le backend effectivement exécuté avec les
modèles `PP-DocLayout*` disponibles.

### 2026-10-06 - Règle de reprise validée

Le plan `docs/plan_refonte_modules_universels_reconstruction.md` est désormais la
spécification stricte du chantier, et non une simple orientation d’architecture.

À la reprise :

- exécuter les phases dans l’ordre exact du plan ;
- traiter chaque fonction selon son statut prévu : conserver, déplacer, remplacer,
  supprimer ou transformer ;
- ne créer aucune logique parallèle non prévue par le plan ;
- ne déclarer une phase terminée qu’après ses critères de validation ;
- conserver les acquis et ne supprimer les anciens chemins qu’après comparaison,
  tests et validation visuelle ;
- mettre à jour ce fichier après chaque étape avec les fichiers, fonctions, tests et
  résultats réels.

La prochaine reprise commence par la validation complète de la Phase 0, puis passe
à la Phase 1 uniquement après inscription de ses critères satisfaits.

### 2026-10-07 - Phase 0 validée, Phase 1 en cours

**Phase 0 validée :**

- contrats de scène complétés avec factory, snapshot, invariants, ordre de peinture
  et recouvrements non destructifs dans `pdfexact/scene.py` ;
- décisions complétées avec bbox/orientation/z-order attendus et validation ;
- `Document.scene` est alimentée en observation à la fin de `extract/document.py` ;
- options universelles complétées avec layout provider, z-order et fallback explicites ;
- les filtres historiques journalisent désormais leur `reason_code` via provenance ;
- 8 tests de contrats et extraction ajoutés ;
- validation : `23` tests de rewriter ciblés puis `359 passed, 1 skipped, 3 warnings`
  avec `pytest --ignore=tests/visual` ;
- les 9 échecs du harness visuel ne sont pas liés à cette phase : LibreOffice ne peut
  pas écrire `/run/user/1000/dconf/user` dans l'environnement de test.

**Phase 1 commencée :**

- les primitives `aire`, `intersection`, `recouvrement`, `centre` et recouvrement
  symétrique sont maintenant déléguées à `analysis/geometry.py` dans les blocs,
  l'extraction principale, le planner, la compréhension, la carte de layout, l'IA
  de layout et les renderers ;
- les suppressions de tableaux, formes, visuels, textes et doublons positionnés sont
  journalisées par provenance au lieu de disparaître silencieusement.

**Reste avant validation Phase 1 :**

- migrer les derniers duplicats géométriques recensés dans `ocr.py`, `styles.py`,
  `tables.py`, `images.py`, `classifier.py`, `final_audit.py` et `drawing.py` ;
- brancher le registre de provenance sur les suppressions OCR/native et les fallbacks ;
- ajouter les tests de non-perte et de compatibilité des wrappers historiques.

### 2026-10-07 - Phase 1 validée, Phase 2 en cours

**Phase 1 validée :**

- les opérations bbox/rect/clip/axes/union sont centralisées dans
  `pdfexact/analysis/geometry.py` ; les fonctions historiques restantes sont des
  wrappers de compatibilité ;
- migration effectuée dans `extract/blocks.py`, `extract/document.py`,
  `extract/images.py`, `extract/layout_map.py`, `extract/ocr.py`,
  `extract/styles.py`, `extract/tables.py`, `layout/ai.py`, `layout/analyzer.py`,
  `layout/classifier.py`, `layout/planner.py`, `layout/understanding.py`,
  `final_audit.py`, `render/drawing.py`, `render/docx_writer.py` et
  `render/word_native_rewriter.py` ;
- `Page.discarded_elements` conserve les objets écartés par segmentation, filtres,
  doublons, plan layout, zones protégées et fallback raster ;
- les décisions de filtrage portent un `reason_code` dans `decision_history` ;
- la scène canonique inclut les éléments écartés avec état `warning` et snapshot ;
- validation : `361 passed, 1 skipped, 3 warnings` avec
  `pytest -q --ignore=tests/visual`.

**Phase 2 commencée :**

- `analysis/semantic.py` existe et protège déjà les frontières de listes et de styles ;
- le prochain travail consiste à déplacer les regroupements de
  `render/word_native_rewriter.py` et `render/native_contract.py` vers ce module,
  puis à produire des groupes sémantiques portant script, continuité, colonnes et
  frontières de ligne avant toute décision de rendu.

### 2026-10-07 - Phase 2 validée, Phase 3 en cours

**Phase 2 validée :**

- `pdfexact/analysis/semantic.py` est maintenant le moteur universel de script,
  langue, continuité, frontières de paragraphe, listes, frames et colonnes ; il ne
  dépend d'aucun XML ni backend Word ;
- les seuils sémantiques utilisés par le regroupement sont des options explicites
  de `AnalysisOptions`, avec conservation des frontières en cas d'ambiguïté ;
- `extract/document.py` délègue le regroupement des lignes sans frame au moteur
  universel ;
- `render/word_native_rewriter.py` délègue listes, paragraphes, frames et colonnes
  à `analysis/semantic.py` ; ses fonctions historiques restent des adaptateurs de
  compatibilité ;
- `render/native_contract.py` délègue texte, styles, listes, continuité et colonnes
  au même moteur ; aucune suppression historique n'a encore été faite ;
- tests ajoutés pour scripts, frontières réelles, continuité inter-frame et listes ;
- validation : `364 passed, 1 skipped, 3 warnings` avec `pytest -q --ignore=tests/visual`.

**Phase 3 commencée :**

- le prochain travail est de rendre `RenderPlan` obligatoire et observable pour
  chaque élément, avec bbox/orientation/z-order attendus et vérification avant
  materialisation DOCX ;
- les décisions locales restantes du renderer doivent devenir des adaptateurs
  temporaires lisant le plan, sans nouvelle classification pendant l'écriture.

### 2026-10-07 - Progression Phase 3

**Fait :**

- `RenderDecision` porte maintenant systématiquement la bbox, l'orientation et
  le z-order attendus de l'élément source ;
- `RenderPlan` valide les décisions, détecte les identifiants dupliqués et expose
  une recherche par `element_id` ;
- `build_render_plan`, `build_page_render_plan` et `build_scene_render_plan`
  enregistrent chaque décision dans la provenance de l'élément ;
- `word_native_rewriter.py` refuse désormais un élément absent du plan au lieu de
  réintroduire sa décision heuristique locale ; les erreurs du plan remontent dans
  `RewriteDiagnostics` et invalident le verdict ;
- tests de couverture complète du plan et de contraintes attendues ajoutés ;
- validation intermédiaire : `365 passed, 1 skipped, 3 warnings` avec
  `pytest -q --ignore=tests/visual`.

**Résolution finale de la Phase 3 :**

- le plan préconstruit est maintenant transmis au package DOCX et consommé par le
  renderer ;
- `_decision` reste uniquement comme symbole historique non appelé par le chemin
  planifié, en attente de la suppression contrôlée de Phase 6.

### 2026-10-07 - Phase 3 validée, Phase 4 en cours

**Phase 3 validée :**

- `RenderPlan` porte les éléments préparés par page, les décisions vérifiées et
  les divergences ;
- `build_rewrite_render_plan` prépare le regroupement sémantique puis construit le
  plan avant l'écriture ;
- `package.ecrire_docx` transmet ce plan au rewriter natif ;
- `rewrite_document_xml` consomme le plan fourni et ne reconstruit pas un plan
  concurrent pendant la matérialisation ; son ancien mode interne reste seulement
  un adaptateur de compatibilité pour les appels directs ;
- validation ciblée : `106 passed, 1 skipped` sur les contrats, le package et le
  rewriter.
- validation complète non visuelle après transmission du plan : `365 passed,
  1 skipped, 3 warnings` avec `pytest -q --ignore=tests/visual` ;
- vérification de corpus exécutée sur les familles
  `63980ecfaee8ef36_000582.pdf` et `4e4a2d80e91be727_000583.pdf` ; les deux
  sorties natives sont des packages DOCX ouvrables, avec plan validé et aucune
  perte signalée par le contrat natif.

**Phase 4 commencée :**

- transformer `native_contract.py` en validateur/adaptateur sans second moteur de
  regroupement ;
- réduire `docx_writer.py` à une façade de compatibilité et conserver ses
  primitives nécessaires aux documents non natifs ;
- faire passer les profils DOCX, ancres, orientations et formes par le plan sans
  perdre les primitives XML déjà validées.

### 2026-10-07 - Phase 4, regroupement et façade DOCX migrés

**Fait :**

- créé `pdfexact/render/reflow.py` comme pré-traitement partagé du rendu ; il
  délègue paragraphes, listes, frames et colonnes à `analysis/semantic.py` puis
  matérialise les groupes avant toute écriture XML ;
- ajouté `build_document_render_plan` dans `render/render_plan.py` ; il indexe la
  liste exacte des éléments préparés qui seront rendus ;
- `render/package.py` construit désormais directement ce plan central et le
  transmet au rewriter ; `word_native_rewriter.py` conserve seulement des wrappers
  de compatibilité pour ses anciens appelants ;
- supprimé du chemin CLI natif la mutation préalable par
  `corriger_document_word_native` ; la préparation est maintenant non destructive
  et déterministe dans le plan ;
- ajouté `valider_contrat_word_native` et `NativeContractReport` dans
  `render/native_contract.py` ; la validation du contrat ne modifie plus l'IR ;
- isolé l'ancien assembleur dans `docx_writer.construire_document_xml_compat` ; le
  package natif ne l'utilise plus comme moteur concurrent ;
- mutualisé les sections dans `render/section_layout.py`.
- ajouté les validations package (`valider_package_ooxml`, `valider_relations`,
  `valider_medias`, `valider_fonts`) et l'export de manifeste stable du plan ;
- `ecrire_docx` accepte maintenant un `render_plan` explicite tout en gardant le
  booléen historique comme adaptateur.
- ajouté `CorrectionLocale` et `appliquer_correction_avec_rollback` dans
  `final_audit.py` ; les récupérations visuelles sont maintenant tracées avec
  zone, cause, éléments retirés et élément inséré avant leur réécriture ;
- ajouté `corrections_locales` au rapport de certification.
- ajouté `render/compatibility.py` avec les profils Word, LibreOffice, WPS et
  strict OOXML ; les risques verticaux/courbés sont désormais signalés dans
  `RewriteDiagnostics` et dans le rapport CLI au lieu d'être implicites.
- étendu l'IR historique (`FlowParagraph`, `TextBox`) avec `source_ids` ; les
  fusions sémantiques et les `ElementRecord` du plan conservent désormais tous les
  fragments sources au lieu de ne garder que le premier identifiant.
- ajouté les audits dédiés `auditer_overflow`, `auditer_z_order`,
  `auditer_font_metrics` et `auditer_editability` ; leurs diagnostics sont
  séparés des `AuditRecord` texte et du score visuel global.

**Validation :**

- compilation `compileall` réussie ;
- `128 passed, 1 skipped, 3 warnings` sur rewriter, package, CLI et contrats ;
- `365 passed, 1 skipped, 3 warnings` sur toute la suite non visuelle avant la
  dernière façade ;
- aucune suppression de primitive historique effectuée avant la comparaison corpus.
- vérification corpus native : `4e4a2d80e91be727_000583.pdf`, 1 page, plan valide,
  26 paragraphes de flux, 3 images, 2 cadres orientés, 0 manque ;
- vérification corpus native : `63980ecfaee8ef36_000582.pdf`, 2 pages, plan valide,
  56 paragraphes de flux, 8 images, 3 cadres orientés, 0 manque.

**Reste Phase 4 :**

- faire consommer le rapport du validateur par le package et le rapport utilisateur ;
- déplacer les primitives de texte/ancres restantes vers des backends dédiés sans
  changer leur XML ;
- comparer le writer de compatibilité et le rewriter unique sur le golden corpus
  avant toute activation globale.

### 2026-10-07 - Préparation non activée de la Phase 5

La Phase 4 reste active. Les éléments ci-dessous sont uniquement les contrats
préparatoires exigés avant l'activation de la Phase 5 ; aucune correction locale
automatique n'est encore déclenchée par ce nouveau rapport.

### 2026-10-07 - Plan de correction visuelle universelle implemente

Le plan detaille et son suivi sont dans
`docs/plan_correction_visuelle_universelle.md`.

**Fait :**

- contrat visuel canonique et etats `extracted`/`planned` ajoutes dans `scene.py`
  et `ir.py` ; la scene conserve style, baseline, orientation, opacite et sources ;
- extraction des spans et lignes enrichie avec bboxes et quad disponibles ;
- metriques de resolution de police conservees dans `FontAsset` ;
- regroupement geometrique protege contre l'elargissement de region au rendu ;
- decisions universelles distinguees pour flux, paragraphe verrouille, texte tourne
  et texte courbe ;
- rewriter natif: bbox source contractuelle, runs continus pour le flux courant,
  lignes preservees uniquement pour les roles geometriques, ordre de peinture
  visuel explicite ;
- audit: verification elementaire des textes et visuels, styles, derive bbox,
  zones et scores, avec echec obligatoire si le rendu DOCX n'est pas disponible ;
- le chemin `native_rewriter` ne peut plus ignorer une zone visuellement differente ;
- manifeste RenderPlan enrichi des styles attendus ;
- test suite non visuelle: `365 passed, 1 skipped, 3 warnings`.
- test CLI reel: `results/sortie_4e4a2d80e91be727_000583_universal_visual_contract.docx`
  genere avec `flow=25`, `cadres ancres=2`, `images=3`, `manquants=0`,
  `hors-page=0` ; le statut final est correctement `INCOMPLETE` car l'export PDF
  du DOCX n'a pas ete disponible pour la comparaison visuelle.

**Regle de verite :** la certification visuelle finale reste impossible tant que
le moteur de rendu DOCX utilise pour la comparaison ne produit pas effectivement
le PDF de sortie. Dans ce cas, le statut est `INCOMPLETE`, jamais `OK`.

**Fait :**

- ajouté `AuditRecord` et `AuditReport` dans `final_audit.py` ; chaque élément
  texte produit désormais un rappel/précision token, une bbox de sortie, une
  visibilité, une orientation attendue, une éditabilité estimée et des causes ;
- intégré la collecte des records dans `certifier_et_reparer` ;
- ajouté `audit_elements` et `audit_elements_en_erreur` à `CertificationFinale` ;
- le verdict final exige maintenant l'absence d'erreur élémentaire en plus des
  métriques globales existantes ;
- conservé les métriques globales comme diagnostics secondaires et non comme
  preuve suffisante de conformité.

**Validation :**

- `103 passed, 1 skipped, 3 warnings` sur audit, CLI et package ;
- compilation et `git diff --check` réussis.
- les tests ciblés audit/CLI passent : `28 passed, 3 warnings`.
- tests rewriter/package/CLI après profils lecteurs : `114 passed, 1 skipped,
  3 warnings`.
- tests ciblés après traçabilité des fusions : `106 passed, 1 skipped`.
- tests audit/CLI/package après audits structurels : `103 passed, 1 skipped,
  3 warnings`.
- validation globale finale de cette reprise : `365 passed, 1 skipped, 3 warnings`
  avec `pytest -q --ignore=tests/visual` ; compilation et `git diff --check`
  réussis.
- test réel actuel exécuté sur `4e4a2d80e91be727_000583.pdf` ; sortie
  `results/test_current_4e4a2d80e91be727_000583.docx` : 26 paragraphes de flux,
  3 images, 2 cadres orientés, 0 manque, 0 hors-page ; validations ZIP/XML,
  relations, médias et polices toutes vides.

**Activation différée jusqu'à la fin de la Phase 4 :**

- ajouter les audits séparés de z-order, overflow, police/métriques et
  éditabilité DOCX ;
- remplacer les mutations directes de récupération par des corrections locales
  tracées avec rollback ;
- tester les records sur les cas texte vertical, texte recouvert, doublon et
  texte présent dans une image.

### 2026-10-06 - Phase 0 démarrée

**Fait :**

- créé `pdfexact/scene.py` ;
- créé `pdfexact/analysis/__init__.py` ;
- créé `pdfexact/analysis/options.py` ;
- créé `pdfexact/analysis/geometry.py` ;
- créé `pdfexact/analysis/provenance.py` ;
- créé `pdfexact/analysis/decisions.py` ;
- créé `pdfexact/analysis/semantic.py` ;
- ajouté un adaptateur `scene_from_legacy_document` pour observer l’IR existant sans le casser ;
- ajouté le registre de cycle de vie des éléments ;
- ajouté les options universelles et les modes de rendu explicites ;
- ajouté la règle de conservation terminale et les décisions non destructives ;
- créé ce fichier de suivi persistant.

**Non fait volontairement :**

- aucun ancien renderer supprimé ;
- aucun filtre historique remplacé en production ;
- aucun changement de sortie DOCX activé par défaut ;
- aucune modification de comportement utilisateur avant les tests de comparaison.

**Validation à faire :**

- tests unitaires des nouveaux contrats ;
- branchement observationnel dans `extract/document.py` ;
- comparaison du nombre et des bboxes d’éléments avant/après ;
- contrôle des imports et de la compatibilité Python 3.10.

### 2026-10-07 - Correction IA obligatoire et géométrie visuelle

**Fait :**

- `layout/ai.py` expose `LayoutAIRequiredError` et interdit le fallback
  géométrique silencieux dans le chemin Word-native.
- `extract/document.py` et `final_audit.py` exigent maintenant une détection IA
  réussie; un modèle absent, un provider indisponible, une erreur ou une sortie
  vide bloque le chemin au lieu de produire une fausse réussite.
- `render/render_plan.py` marque les pages à plusieurs bandes x comme
  `page-geometry-locked`; `analysis/decisions.py` choisit alors un conteneur
  positionné au niveau de la page.
- `render/word_native_rewriter.py` garde les textes sous forme de vrais
  paragraphes/runs Word dans ces conteneurs, avec reflow interne et sans
  paragraphes artificiels par ligne.
- `extract/document.py` dédoublonne également le chemin PDF natif mixte et
  supprime les fragments isolés contenus dans un titre/légende ainsi que les
  crédits verticaux dupliqués.
- `final_audit.py` part désormais de `conforme=False` et ajoute une erreur
  bloquante si LibreOffice ne produit pas le PDF de comparaison; `cli.py` renvoie
  le code 3 dans ce cas.

**Validation :**

- `365 passed, 1 skipped, 3 warnings` avec `pytest -q --ignore=tests/visual`.
- Test réel avec le modèle `/home/raphael/Mes_Projets/vysi/ai_models`:
  `layout_ai_detected`, 21 cadres éditables positionnés, fragments `A`, `S` et
  `y` supprimés du DOCX.
- L’export headless LibreOffice disponible dans ce sandbox retourne encore le
  code 1 sans produire de PDF; le verdict final reste donc volontairement
  bloquant (`audit_rendu_verifie=false`).

**Règle de vérité :** le contrat XML Word-native ne vaut jamais certification
visuelle. Une sortie n’est conforme qu’après rendu DOCX réel et comparaison
élément par élément avec le PDF source.

### 2026-10-08 - Corrections géométriques, présentation par bloc et compréhension IA

**Implémenté conformément au plan :**

- `pdfexact/ir.py` : `TextGeometry` transporte les bbox de lignes, quads,
  baselines et zones d’exclusion ; `TextBox` et `FlowParagraph` conservent la
  présentation propre à chaque bloc.
- `pdfexact/analysis/text_geometry.py` : contrat universel de forme
  (`rectangular-flow`, `exclusion-flow`, `variable-width-flow`, `oriented`),
  alignement local et dérivation des exclusions à partir des retraits réels.
- `pdfexact/extract/text.py` et `pdfexact/render/reflow.py` : recalcul du contrat
  géométrique et de la présentation après extraction et fusion, sans élargissement
  silencieux de bbox.
- `pdfexact/extract/catalog.py` : persistance de `geometry`,
  `exclusion_bboxes`, `line_bboxes`, `line_quads`, `baselines` et `presentation`
  pour chaque bloc texte.
- `pdfexact/render/render_plan.py` : exposition du type géométrique, des lignes,
  exclusions, styles de runs et propriétés de présentation.
- `pdfexact/render/word_native_rewriter.py` : régions irrégulières rendues par
  tranches de paragraphes Word-native avec retraits ligne par ligne ; jonctions
  sémantiques et suppression des traits d’hyphénation de coupure ; textes
  verticaux, obliques et courbes conservés dans le backend éditable WPS/VML.
- `pdfexact/analysis/semantic.py` : une décision IA acceptée peut confirmer ou
  refuser une jonction, sans remplacer les contraintes géométriques ni le fallback.
- `pdfexact/cli.py` : lorsqu’un endpoint sémantique est configuré dans
  `PDFEXACT_TEXT_UNDERSTANDING_URL` ou `PDFEXACT_TEXT_ORIENTATION_URL`, le chemin
  CLI active automatiquement le fournisseur correspondant ; aucune IA disponible
  n’est prétendue active sans endpoint réel.
- `pdfexact/layout/text_comprehension.py`, `text_comprehension_ai.py` et
  `extract/orientation.py` : chaque décision indique `ai_used` et
  `fallback_used`.
- `pdfexact/final_audit.py` : contrôle de la perte de lignes, de la disparition
  des exclusions et de l’aplatissement des largeurs variables ; ces erreurs
  bloquent le statut conforme.

**Validation :**

- tests ciblés : `55 passed, 3 warnings` ;
- suite non visuelle complète : `370 passed, 1 skipped, 3 warnings` ;
- génération réelle du corpus `4e4a2d80e91be727_000583.pdf` :
  `results/4e4a2d80e91be727_000583_bboxes_native_paragraphs_after_plan_v4.docx` ;
- manifeste associé : 16 blocs texte, 16 présentations persistées, 4 types de
  géométrie détectés, 16 zones d’exclusion ; XML et package ZIP validés.

**Limite de certification :** la conformité visuelle finale reste conditionnée à
la disponibilité effective de l’exporteur DOCX->PDF ; l’audit est fail-closed et
ne déclare pas `OK` sans rendu réel.

### 2026-10-10 - Segmentation Codex et correction du repere du PDF annote

- Reference visuelle independante produite par inspection Codex : 10 objets de
  premier plan et 2 couches de fond, avec coordonnees, PDF numerote et legende.
- Cause du diagnostic tourne confirmee : `annotate_pdf_bboxes()` passait les
  coordonnees visibles canoniques a une API d'ecriture en coordonnees natives.
- Correction generique du dessin des rectangles et contours : transformation
  inverse centralisee par `PageGeometry`, respect des CropBox decalees et
  restauration de la rotation source. Contours de paragraphes fermes.
- Validation : 16 cas de repere et de rendu pixel ; 43 tests cibles passes.
- Run CPU reel : IA active avec 3 macro-zones ; 21 elements IR. Les cadres du
  diagnostic sont maintenant correctement orientes.
- Causes restantes confirmees : remplacement injustifie de bboxes PDF par la
  recherche visuelle, absence d'ordre de peinture transporte pour les images,
  objets masques conserves comme visibles, objets inclus dans les fonds bitmap.
- L'experimentation de filtrage/fusion cosmetique des cadres a ete retiree.
  Aucun compte de cadres reduit n'est utilise comme preuve de segmentation.
- Audit detaille : `docs/audit_segmentation_codex_2026-10-10.md`.

La segmentation manuelle sert de benchmark. Ses coordonnees ne sont pas utilisees
par le convertisseur de production. La conformite visuelle DOCX reste a valider.

### 2026-10-10 - Correction du plantage OpenCV sur un autre PDF

- L'analyse PaddleX fonctionne sur la page 1 de `96a80f28f8366209_000751.pdf`
  et produit 49 zones. Le plantage suivant etait dans la recherche chromatique.
- `_template_bbox_from_chroma()` comparait des gabarits dont un axe pouvait
  depasser la cible. OpenCV rejetait les dimensions incompatibles.
- Controle generique ajoute avant `resize`/`matchTemplate` : ignorer une echelle
  trop large ou trop haute. Sans candidat admissible, le controle retourne `None`
  et le placement PDF reste disponible dans l'extracteur.
- Quatre tests reproduisant le probleme avant correction passent maintenant.
  Suite cible images/geometrie : 78 tests passes.
- Commande utilisateur relancee en CPU avec succes : PDF annote et DOCX generes
  dans les chemins demandes. La qualite visuelle finale reste a valider.

## Prochaines étapes obligatoires

La liste de création des contrats/registre/RenderPlan précédemment présente ici
était antérieure aux validations historiques. Elle est remplacée par les critères
non cochés de la reprise du 2026-10-11, avec les preuves de la baseline ci-dessus.

1. Résoudre les quatre P1 B1 à B4 avec tests de comportement verts, puis confirmer
   les Phases 0 à 3 contre toutes les exigences des sections 4 à 11 ; inscrire les
   autres écarts fonction par fonction. Aucune activation par défaut avant ces preuves.
2. Achever la Phase 4 sur tous les chemins : façade/backend unique, primitives
   spécialisées, un seul plan, mapping XML, corpus et profils lecteurs.
3. Achever ensuite la Phase 5 : audit exhaustif source/sortie, corrections locales
   du plan avec rollback et vérification après chaque passe.
4. Constituer les sept artefacts de chacune des douze familles et passer les
   critères globaux ; expliquer toute limite, diagnostic ou test ignoré.
5. Autoriser la suppression contrôlée de Phase 6 seulement après ces preuves,
   puis revalider les chemins migrés et mettre à jour le verdict final.

## Règle de reprise après fermeture de Codex

À la reprise, lire ce fichier puis le plan d’architecture. Ne passer à la phase
suivante que si les critères de validation de la phase active sont inscrits ici avec
les commandes et résultats correspondants.
