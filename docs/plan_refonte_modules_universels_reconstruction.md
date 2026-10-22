# Plan complet de refonte vers des modules universels de reconstruction PDF -> DOCX

## Mise à jour, correction, déplacement, suppression et ajout des modules

**Projet :** `pdfexact`  
**Objectif :** rendre les logiques de compréhension, détection, extraction, reconstruction, réécriture Word-native et audit universelles, traçables et réutilisables pour tout type de PDF pris en charge.  
**Principe directeur :** les différences entre PDF doivent modifier les données et les options, jamais contourner les invariants fondamentaux.

---

## 1. Décision d’architecture

### 1.1 Problème à corriger

L’architecture actuelle contient plusieurs centres de décision qui se recouvrent :

```text
extract/document.py
    -> compréhension / filtres / déduplication / regroupement
layout/understanding.py
    -> classification / zones protégées / stratégie
layout/planner.py
    -> protection / filtrage / plan
render/native_contract.py
    -> regroupement / conversion en paragraphes
render/word_native_rewriter.py
    -> regroupement / décision / rendu OOXML
render/docx_writer.py
    -> autre décision / autre reflow / autre rendu
render/drawing.py
    -> primitives + décisions de formes / ancres
final_audit.py
    -> contrôle tardif + récupération partiellement destructive
```

Ce découpage permet qu’une correction réussie dans un fichier soit contournée dans un autre chemin. Le plan remplace ces décisions distribuées par un contrat universel unique.

### 1.2 Architecture cible

```text
PDF
 |
 v
[Acquisition brute]
 |
 v
[Scene IR canonique]
 |
 +--> détection et extraction
 +--> géométrie et orientation
 +--> compréhension sémantique
 +--> provenance et confiance
 +--> déduplication non destructive
 |
 v
[RenderPlan universel]
 |
 v
[Backend DOCX unique]
 |
 v
[DOCX]
 |
 v
[Rendu de contrôle]
 |
 v
[Audit par élément + corrections locales]
```

### 1.3 Règle absolue

Les modules peuvent avoir des implémentations spécialisées par type d’élément, mais ils doivent consommer et produire les mêmes contrats :

```text
PageScene -> ElementRecord -> SemanticRecord -> RenderDecision -> AuditRecord
```

Une branche spécialisée ne peut jamais :

- supprimer un élément sans provenance et justification ;
- modifier le repère géométrique ;
- réinventer son propre z-order ;
- réinventer ses propres seuils de fusion ;
- contourner l’audit par élément ;
- remplacer un paragraphe par une image sans déclaration de perte d’éditabilité.

---

## 2. Contrats universels à ajouter avant toute suppression

### 2.1 Nouveau module : `pdfexact/scene.py`

Ce module devient le modèle canonique indépendant de l’extraction et du rendu.

#### Types à ajouter

```python
class SourceKind(Enum):
    PDF_NATIVE = "pdf-native"
    OCR = "ocr"
    IMAGE = "image"
    VECTOR = "vector"
    LAYOUT_AI = "layout-ai"
    INFERRED = "inferred"

class ElementKind(Enum):
    TEXT = "text"
    IMAGE = "image"
    SHAPE = "shape"
    TABLE = "table"
    LINK = "link"
    RASTER_COMPOSITE = "raster-composite"

class RenderMode(Enum):
    NATIVE_FLOW = "native-flow"
    NATIVE_LIST = "native-list"
    NATIVE_TABLE = "native-table"
    POSITIONED_TEXT = "positioned-text"
    EDITABLE_FRAME = "editable-frame"
    ANCHORED_IMAGE = "anchored-image"
    ANCHORED_SHAPE = "anchored-shape"
    LOCAL_RASTER = "local-raster"
    KEEP_BOTH_AMBIGUOUS = "keep-both-ambiguous"

class VerificationState(Enum):
    DETECTED = "detected"
    CLASSIFIED = "classified"
    GROUPED = "grouped"
    RENDERED = "rendered"
    VERIFIED = "verified"
    WARNING = "warning"
    FAILED = "failed"
```

#### `ElementRecord`

Champs obligatoires :

- `element_id` stable et reproductible ;
- `page_index` ;
- `kind` et `role` ;
- `source_kind` et `source_ids` ;
- bbox, quadrilatère, polygone et chemin éventuel ;
- baseline et points d’orientation ;
- `z_order`, clipping, opacité et compositing ;
- texte, spans, langue et script ;
- style et métriques de police ;
- confiance de détection, extraction, rôle et géométrie ;
- candidats de doublon ;
- `render_decision` ;
- historique des décisions ;
- état de vérification.

#### Fonctions à ajouter

- `creer_element_record(...)` : crée un élément avec provenance obligatoire.
- `ajouter_preuve(element, preuve)` : attache une preuve sans écraser les précédentes.
- `enregistrer_decision(element, decision)` : journalise la décision et sa justification.
- `marquer_conserve(element, mode)` : rend explicite la conservation.
- `marquer_non_representable(element, raison)` : autorise un fallback déclaré.
- `valider_invariants_scene(scene)` : vérifie qu’aucun élément n’est orphelin ou sans état.
- `ordonner_elements_par_peinture(scene)` : produit un ordre total stable.
- `reperer_recouvrements(scene)` : construit les relations de superposition sans suppression.

#### Fonctions à ne pas ajouter

Le modèle canonique ne doit pas contenir de XML DOCX, de seuil AI ni de décision liée à LibreOffice. Il reste neutre.

### 2.2 Nouveau module : `pdfexact/analysis/options.py`

#### `AnalysisOptions`

Options explicites :

- `use_native_pdf_text` ;
- `ocr_provider` ;
- `ocr_granularity` ;
- `layout_provider` ;
- `language` et `script` ;
- `detect_curved_text` ;
- `detect_z_order` ;
- `preserve_reading_order` ;
- `preserve_line_boundaries` ;
- `allow_raster_fallback` ;
- `target_reader` ;
- `visual_priority` / `editability_priority` ;
- seuils configurables par profil, jamais codés dans les fonctions.

#### Règle

Une option peut modifier une politique explicite. Elle ne peut pas supprimer l’invariant « chaque élément reçoit une décision et une vérification ».

### 2.3 Nouveau module : `pdfexact/analysis/decisions.py`

#### `RenderDecision`

Champs :

- `mode` ;
- `reason_codes` ;
- `confidence` ;
- `constraints` ;
- `fallback_mode` ;
- `editable` ;
- `expected_bbox` ;
- `expected_orientation` ;
- `expected_z_order` ;
- `requires_verification`.

#### Fonctions

- `decider_mode_universel(element, scene, options)` ;
- `verifier_decision(decision, element)` ;
- `decision_requires_fallback(decision)` ;
- `decision_is_safe_native_flow(decision)` ;
- `decision_is_lossless(decision)`.

Cette décision devient la seule source autorisée pour choisir flow, liste, table, frame, image, forme ou raster.

### 2.4 Nouveau module : `pdfexact/analysis/geometry.py`

Déplacer ici toutes les opérations géométriques communes :

- aire ;
- intersection ;
- recouvrement par rapport à une zone ;
- union ;
- clipping à la page ;
- centre ;
- projection x/y ;
- IoU bbox ;
- IoU quadrilatère ;
- distance baseline ;
- angle et orientation ;
- détection de chemin/courbure.

Objectif : supprimer les copies de `_aire`, `_intersection`, `_recouvrement_source`, `_centre_dans`, `_clip_bbox` et équivalents dispersées dans plusieurs modules.

### 2.5 Nouveau module : `pdfexact/analysis/provenance.py`

Fonctions :

- `creer_source_id(...)` ;
- `lier_source_ocr_native(...)` ;
- `calculer_candidats_doublon(...)` ;
- `marquer_doublon_sans_supprimer(...)` ;
- `expliquer_filtrage(...)` ;
- `expliquer_fallback(...)` ;
- `registre_elements(scene)`.

Ce module est obligatoire pour rendre l’audit explicable.

---

## 3. Plan de migration par phases

### Phase 0 - Gel des invariants

1. Ne supprimer aucune fonction métier immédiatement.
2. Ajouter les nouveaux contrats et des adaptateurs vers l’IR actuel.
3. Ajouter des snapshots de scènes pour les PDF déjà validés.
4. Mesurer les décisions actuelles sans changer le rendu.

### Phase 1 - Centralisation géométrique et provenance

1. Créer `analysis/geometry.py` et `analysis/provenance.py`.
2. Remplacer les helpers locaux par des wrappers temporaires.
3. Ajouter un registre d’éléments à chaque page.
4. Interdire les suppressions sans `reason_code`.

### Phase 2 - Compréhension et regroupement universels

1. Créer `analysis/semantic.py`.
2. Déplacer les fonctions de regroupement de `document.py`, `native_contract.py` et `word_native_rewriter.py`.
3. Remplacer les heuristiques de casse par un modèle script-aware.
4. Conserver les frontières de ligne lorsque la confiance est insuffisante.

### Phase 3 - Décision de rendu unique

1. Créer `analysis/decisions.py`.
2. Faire consommer `RenderDecision` par tous les backends.
3. Désactiver progressivement les décisions internes concurrentes.
4. Ajouter un mode diagnostic qui explique chaque élément.

### Phase 4 - Backend DOCX unique

1. Garder les primitives XML de `drawing.py`.
2. Faire de `word_native_rewriter.py` l’orchestrateur unique.
3. Transformer `docx_writer.py` en façade de compatibilité puis réduire son périmètre.
4. Supprimer les grilles de positionnement utilisées comme flux artificiel.

### Phase 5 - Audit par élément et correction locale

1. Remplacer les seuils globaux de `final_audit.py` par des `AuditRecord`.
2. Vérifier chaque élément source et chaque élément produit.
3. Réparer localement, jamais par rasterisation globale silencieuse.
4. Rejouer la vérification après chaque correction.

### Phase 6 - Suppression contrôlée

Supprimer uniquement après :

- migration de tous les appels ;
- tests unitaires et golden tests ;
- comparaison visuelle sur corpus ;
- validation Word/LibreOffice ;
- absence de diagnostics non expliqués.

---

## 4. Module `pdfexact/ir.py`

### Rôle cible

`ir.py` reste un fichier de compatibilité et de types bas niveau. Le modèle canonique de traçabilité va dans `scene.py`. L’IR historique ne doit plus porter des décisions de rendu cachées.

### Types existants

#### `FontAsset`

- **Conserver** : données de police, chemin, statut d’embedding.
- **Ajouter** : métriques disponibles, couverture Unicode, équivalence validée, source de substitution.
- **Ajouter** : `font_confidence` et `metrics_confidence`.
- **Ne pas laisser** : la résolution de police décider seule d’une reconstruction.

#### `FontRef`

- **Conserver** : référence de span.
- **Ajouter** : script, langue, rôle typographique et identifiant canonique.
- **Déplacer** la résolution effective dans `extract/text.py` ou `fonts.py`.

#### `MediaItem`

- **Conserver**.
- **Ajouter** : dimensions natives, mode couleur, alpha, hash, provenance et résolution DPI.
- **Ajouter** : distinction média source / média composite de fallback.

#### `Span`

- **Conserver** les attributs typographiques.
- **Ajouter** : `source_kind`, `source_id`, `quad`, `baseline`, `language`, `script`, `z_order`, `confidence`.
- **Ajouter** : `glyph_ids` et `to_unicode_status` pour les PDF difficiles.
- **Supprimer progressivement** les champs dont la sémantique est ambiguë ; les remplacer par des enums.

#### `Line`

- **Conserver** comme unité d’observation, pas comme paragraphe.
- **Ajouter** : points de baseline complets, quad, direction de lecture, script et score de segmentation.
- **Ajouter** : `boundary_before` et `boundary_after` avec confiance.

#### `TextBox`

- **Conserver** comme groupe géométrique.
- **Ajouter** : `group_id`, rôle et preuves de regroupement.
- **Ne plus supposer** qu’un TextBox est nécessairement une textbox DOCX.

#### `FlowParagraph`

- **Conserver temporairement** pour compatibilité du renderer.
- **Ajouter** : `paragraph_confidence`, `source_line_ids`, `render_decision_id`.
- **Déprécier** sa création directe par les extracteurs.
- **Créer** uniquement après décision sémantique sûre.

#### `ImageEl`, `ShapeEl`, `RasterEl`

- **Conserver**.
- **Ajouter** : z-order, clipping, opacité, groupe parent, source et confiance.
- **RasterEl** doit toujours porter la cause du fallback et les éléments source qu’il remplace.

#### `TableBorder`, `TableCell`, `TableRow`, `TableEl`

- **Conserver** pour les tables reconnues.
- **Ajouter** : confiance cellule/ligne/table, preuves de grille, source des textes, fusion explicite.
- **Ne pas confondre** une table PDF visuelle et une vraie table sémantique.

#### `LinkZone`

- **Conserver**.
- **Ajouter** la provenance, le texte associé et l’ordre de peinture.

#### `Page` et `Document`

- **Conserver** comme conteneurs publics.
- **Ajouter** `scene_id`, `source_pdf_id`, `options_snapshot`, `diagnostics`, `element_registry`.
- **Ajouter** une validation d’invariants avant rendu.

### Fonctions à ajouter à `ir.py`

- `iter_elements(document)` ;
- `element_text(element)` ;
- `element_source_ids(element)` ;
- `element_geometry(element)` ;
- `clone_element_with_metadata(element, **changes)` ;
- `validate_document_ir(document)`.

### Fonctions à ne pas ajouter

Aucune fonction XML ou décision de layout dans l’IR.

---

## 5. Module `pdfexact/extract/document.py`

### Rôle cible

Ce module devient l’orchestrateur d’acquisition PDF -> scène brute. Il ne doit plus prendre seul des décisions de rendu, ne doit plus supprimer des éléments selon des règles de layout et ne doit plus contenir trois implémentations de regroupement.

### Helpers géométriques

Fonctions : `_aire`, `_intersection`, `_recouvrement_min`, `_recouvrement_source`, `_zone_deja_couverte`, `_bbox_intersecte_page`, `_zone_source_deja_couverte`.

- **Déplacer** vers `analysis/geometry.py`.
- **Remplacer** les appels par le module commun.
- **Supprimer** les copies après migration.

### Sélection de source texte

#### `_page_image_pleine_sans_texte_natif`

- **Conserver temporairement** comme observation.
- **Réécrire** pour retourner un diagnostic, pas une décision destructive.
- **Ajouter** confiance et raison.

#### `_page_pdf_natif_dominant` et `_page_pdf_natif_mixe`

- **Conserver** comme statistiques de source.
- **Supprimer** leur rôle de routage exclusif.
- Le choix natif/OCR devient une option et une décision par zone.

#### `_extraire_texte_pdf_natif_word_native`

- **Réécrire** pour créer des lignes source dans la scène.
- **Ne plus créer directement** des paragraphes Word.
- Conserver spans, quad, baseline, orientation, source et confiance.
- Déplacer le regroupement vers `analysis/semantic.py`.

### Formules et OCR

#### `_zones_formules_du_plan`, `_zone_formule_inline_dans_texte`

- **Déplacer** la classification vers `analysis/semantic.py`.
- **Conserver** la géométrie de formule comme preuve.
- Ne jamais filtrer une formule sans l’enregistrer.

#### `_preparer_ocr_visible_page_image`, `_styliser_ocr_depuis_image_scanee`, `_couleur_texte_depuis_rendu`

- **Conserver** dans un nouveau `extract/ocr_adapter.py`.
- Retourner des observations OCR enrichies, jamais des paragraphes finaux.
- Ajouter scores de reconnaissance, orientation et qualité de crop.

### Tables et vecteurs

#### `_zone_touche_tableau`, `_tableau_ressemble_graphe`, `_tableau_ressemble_bandeau_entete`, `_filtrer_tableaux_contredits_par_ia`, `_tableau_confirme_par_layout_ia`

- **Déplacer** vers `analysis/element_detection.py`.
- Transformer `filtrer` en `classer` ou `annoter`.
- Un tableau contradictoire par l’IA doit devenir `ambiguous`, pas être supprimé.

#### `_forme_couverte_par_zone`, `_filtrer_formes_couvertes`, `_element_visuel_couvert_par_zone`, `_filtrer_elements_visuels_couverts`

- **Réécrire** en relations de recouvrement et candidats de doublon.
- **Supprimer** le filtrage silencieux.
- Ajouter opacité, z-order et groupe parent.

### Texte dans les zones visuelles

#### `_element_texte_couvert_par_zone`, `_filtrer_textes_couverts`, `_element_texte_intersecte_zone`, `_filtrer_textes_intersectant_zones`

- **Remplacer** par `annoter_texte_dans_zone(element, zone)`.
- Statuts possibles : `native-over-image`, `baked-in-image`, `duplicate-candidate`, `occluded`, `unknown`.
- Seule la décision universelle pourra choisir de ne pas réécrire.

#### `_bbox_texte_elementaires`, `_ligne_sans_spans_intersectant_zones`, `_bbox_texte_intersecte_zone`, `_zone_contient_lignes_natives`

- **Conserver** comme primitives de preuve.
- **Déplacer** vers `analysis/geometry.py` et `analysis/provenance.py`.

#### `_filtrer_zones_images_avec_texte_natif`, `_zones_images_lisibles_ocr`, `_filtrer_zones_lisibles_ocr`

- **Réécrire** comme plan de sources OCR par zone.
- Ne jamais supprimer l’image et le texte sans relation de doublon explicitement validée.

### Raster et fonds synthétiques

#### `_zones_visuelles_ia_a_rasteriser`, `_zones_formules_a_rasteriser`

- **Déplacer** vers `reconstruction/fallback.py`.
- Retourner des demandes de fallback, pas créer directement des éléments.
- Ajouter budget, motif et portée locale.

#### `_texte_blanc_sur_fond`, `_couleur_int_vers_rgb`, `_couleur_presque_blanche`, `_zone_contient_texte_blanc_natif`, `_ratio_fond_colore_sombre`, `_zone_visuelle_garde_texte_original`, `_bande_fond_depuis_rendu`, `_fonds_synthetiques_texte_inverse`

- **Conserver** les analyses de contraste comme preuves.
- **Déplacer** vers `analysis/appearance.py`.
- **Supprimer** toute règle qui déduit la suppression du texte uniquement d’une couleur ou d’un recouvrement.

### Quantification et cadres de lecture

#### `_limiter_bbox_page`, `_qbbox`, `_quantifier_span`, `_quantifier_ligne`, `_quantifier_element`, `_quantifier_page`

- **Déplacer** vers `analysis/geometry.py`.
- Garantir une seule conversion en EMU et une seule politique d’arrondi.

#### `_securiser_elements_visuels_page`

- **Réécrire** pour annoter les éléments et générer des `ElementRecord`.
- Ne plus trier les éléments uniquement par type.

#### `_cadres_lecture_depuis_comprehension`, `_cadres_lecture_depuis_plan`, `_fusionner_cadres_lecture`, `_score_meme_cadre_lecture`, `_cadres_hors_couverture`, `_dedoublonner_cadres_lecture`

- **Déplacer** vers `analysis/reading_order.py`.
- Introduire un graphe de voisinage et un score de confiance.
- Conserver plusieurs cadres concurrents si le score est proche.

### Frames, regroupements et doublons

#### `_attacher_frames_texte`

- **Réécrire** pour produire des candidats d’appartenance, pas une affectation irréversible immédiate.
- Ajouter direction de lecture, rôle, z-order, style et proximité.

#### `_regrouper_lignes_sans_frame`

- **Déplacer** vers `analysis/semantic.py`.
- Remplacer la logique minuscule/écart fixe par un score script-aware.

#### `_style_ligne_texte`, `_role_frame_inferre`, `_meilleur_frame_ligne`

- **Conserver** comme features.
- **Supprimer** leur pouvoir de décision autonome.

#### `_dedoublonner_textes_positionnes`, `_compact_textbox_line`, `_lignes_dupliquees`, `_meilleur_texte_duplique`, `_score_texte_positionne`

- **Déplacer** vers `analysis/provenance.py`.
- Déduplication non destructive ; conserver le perdant comme candidat lié.

### Diagnostics et orchestration

#### `_diagnostic_layout`, `_bbox_report`, `_inventaire_layout`

- **Conserver et étendre** pour exporter le registre universel.
- Ajouter `element_id`, décisions, conflits, suppressions justifiées et fallback.

#### `_fond_vectoriel_significatif`, `_vectoriel_structurel_significatif`, `_forme_bordure_page_clusterisante`

- **Déplacer** vers `analysis/element_detection.py`.
- Retourner `VectorClassification` avec confiance.

#### `_remplir_page`

- **Réécrire** comme assemblage de scène brute.
- Ne doit plus choisir le renderer final.

#### `extraire`

- **Conserver comme façade publique**.
- Pipeline cible : acquisition -> scène -> compréhension -> registre -> validation.
- Aucun filtrage destructif sans trace.

---

## 6. Module `pdfexact/extract/text.py`

### Rôle cible

Extraire les glyphes et spans fidèlement, sans décider des paragraphes ni des frames.

### Fonctions

#### `_couleur_hexa`, `_bbox_depuis_liste`

- **Déplacer** vers `analysis/geometry.py` ou `extract/pdf_primitives.py`.
- Une seule conversion de couleur et de coordonnées.

#### `_resoudre_police`

- **Conserver** mais retourner `FontResolution` avec statut et confiance.
- Ne jamais remplacer silencieusement une police sans diagnostic.

#### `_style_depuis_nom`

- **Conserver** comme normalisation de style.
- Ajouter détection de script et style incomplet.

#### `_ordre_glyphes`, `_texte_depuis_glyphe`

- **Réécrire** pour gérer ToUnicode, glyph order et fallback.
- Retourner `TextRecoveryResult` avec perte potentielle explicite.

#### `_corriger_espacement`

- **Conserver** seulement comme correction de mesure, pas comme correction de contenu.
- Ajouter `spacing_confidence`.

#### `_ligne_mots_lisible`

- **Supprimer comme filtre dur**.
- Remplacer par score de lisibilité qui reste dans les métadonnées.

#### `_span_ir`, `_ligne_ir`

- **Réécrire** pour alimenter `ElementRecord` et conserver quad, baseline, orientation, source et glyph ids.

#### `extraire_texte`, `extraire_texte_glyphes`

- **Conserver comme adaptateurs de source**.
- Ne doivent plus créer `TextBox` final sans passer par le registre de scène.

---

## 7. Modules `extract/blocks.py`, `images.py`, `layout_map.py`, `orientation.py`

### `extract/blocks.py`

#### `ratio_couverture`, `centre_dans`, `est_dans_zone`

- **Déplacer** vers `analysis/geometry.py`.

#### `_proche_verticalement`, `_compatible_horizontalement`

- **Déplacer** vers `analysis/semantic.py` comme features paramétrables.
- Ne plus fusionner directement sur ces seuls critères.

#### `detecter_blocs_texte`, `detecter_blocs_page`

- **Réécrire** pour produire des candidats de blocs avec scores.
- Ajouter frontières probables, orientation, langue et rôle possible.
- Déplacer la décision de fusion finale vers `semantic_grouping.py`.

### `extract/images.py`

#### `_est_artefact_image`

- **Conserver** comme score d’artefact.
- Ne plus supprimer sans provenance.

#### `_octets_et_extension`, `_bbox_image`, `extraire_images`

- **Conserver**.
- Ajouter hash, alpha, dimensions, clipping et ordre de peinture.

#### `extraire_images_rasterisees`, `extraire_images_inline`, `extraire_images_inline_rasterisees`

- **Conserver comme adaptateurs image**.
- Les images rasterisées par fallback doivent passer par `reconstruction/fallback.py`, pas par l’extracteur.

#### `_est_image_page`, `_aire`, `_ratio_intersection`, `_bbox_intersection`, `_bbox_source_ratio`, `_couverture_par_zones`

- **Déplacer** les helpers géométriques.

#### `_zone_contient_texte_natif`, `_image_inline_ressemble_fragment_texte`, `_image_ressemble_fragment_texte_octets`

- **Réécrire** en détection de relation image/texte et candidat de doublon.

### `extract/layout_map.py`

#### `PageLayoutMap.ajouter`, `ajouter_cadre_lecture`

- **Conserver** comme collecte d’observations.
- Ajouter provenance, confiance et type de géométrie.

#### `lignes_natives`, `lignes_visuelles_natives`, `cadres_colonnes_natives`, `cadres_lecture_natifs`, `zones_visuelles`

- **Conserver comme vues en lecture seule**.
- Ne doivent pas filtrer la scène.

#### `recaler_ligne_ocr`, `remplacement_texte_natif`, `texte_natif_preferable`, `contraindre_bbox_texte`

- **Réécrire** pour produire une proposition et une confiance.
- Les remplacements deviennent des relations de provenance.

#### `touche_visuel`, `proche_petit_visuel`, `_dans_zone_visuelle`, `confirme_texte_natif`, `contredit_texte_natif`

- **Déplacer** vers `analysis/provenance.py` et `analysis/appearance.py`.
- Remplacer les booléens irréversibles par des scores.

#### `_meilleure_ligne_native`, `_meilleure_ligne_visuelle_native`, `_cadre_lecture_pour_bbox`, `_cadre_colonne_pour_bbox`

- **Réécrire** pour retourner une liste classée de candidats.

#### `_cadres_lecture_natifs`, `_completer_cadres_lecture_par_colonnes`, `_cadre_lignes_natives_hors_cadres`, `_cadres_lecture_taxonomie`, `_cadres_colonnes_natives`, `_cadre_texte_natif`

- **Déplacer** vers `analysis/reading_order.py`.
- Unifier avec les cadres AI, vectoriels et OCR.

#### `construire_layout_map`

- **Conserver comme façade**, mais retourner une vue de scène et non une structure concurrente.

#### `_ajouter_lignes_visuelles_natives`, `_bbox_depuis_liste`, `_limiter_page`, `_aire`, `_ratio_intersection`, `_ratio_couverture`, `_ratio_vertical`, `_ratio_horizontal`, `_centre_dans`, `_compact`, `_contient_leader`, `_texte_compatible`, `_similarite_simple`

- **Déplacer** les helpers génériques.
- Les tests de texte deviennent des features réutilisables, jamais des filtres isolés.

### `extract/orientation.py`

#### `configurer_fournisseur_orientation`

- **Conserver**, mais injecter le provider par options.

#### `normaliser_angle`, `angle_depuis_points`, `courbure_depuis_points`

- **Conserver et centraliser** dans le module géométrique.
- Ajouter quadrilatère, baseline et chemin.

#### `classer_orientation`

- **Réécrire** avec classes : horizontal, vertical, rotated, oblique-up, oblique-down, curved, script-vertical, unknown.
- Retourner angle, axe de lecture et confiance.
- Ne pas réduire une courbe à une simple rotation.

---

## 8. Module universel à ajouter : `pdfexact/analysis/semantic.py`

Ce module remplace les regroupements dispersés.

### Fonctions à ajouter

- `normaliser_script_et_langue(element)` ;
- `calculer_features_continuite(previous, current)` ;
- `est_frontiere_de_paragraphe(previous, current)` ;
- `est_continuation_de_ligne(previous, current)` ;
- `detecter_marqueur_liste(element)` ;
- `regrouper_paragraphes(elements, options)` ;
- `regrouper_listes(elements, options)` ;
- `regrouper_frames(elements, options)` ;
- `detecter_colonnes_textuelles(elements, options)` ;
- `preserver_frontieres_ambiguës(groups)` ;
- `produire_flow_paragraphs(groups)` ;
- `valider_groupe_semantique(group)`.

### Règles

- aucune dépendance au XML ;
- aucune dépendance à Word ;
- aucun seuil caché ;
- support script-aware ;
- frontières conservées si confiance insuffisante ;
- listes détectées par combinaison symbole/indentation/répétition/alignement ;
- un cadre géométrique ne suffit jamais à fusionner deux paragraphes.

---

## 9. Module `pdfexact/layout/understanding.py`

### Rôle cible

Classifier les éléments et produire des hypothèses de rôle. Ce module ne doit plus protéger ou supprimer directement des éléments.

### Types

#### `UnderstandingZone`

- **Conserver** pour compatibilité.
- Ajouter `confidence`, `evidence_ids`, `occlusion_status`, `source_ids`.

#### `UnderstandingElement`

- **Conserver** comme résultat de classification.
- Ajouter une liste de rôles candidats, un score par rôle et une décision recommandée.

#### `PageUnderstanding`

- **Réécrire** comme vue de classification de la scène.
- Les propriétés `zones_ocr`, `zones_layout`, `elements_editables`, `elements_immuables` deviennent des vues, pas des autorisations de suppression.

### Méthodes de `PageUnderstanding`

#### `add`, `add_element`

- **Conserver**.
- Enregistrer les preuves et rattacher les `element_id`.

#### `zones_ocr`, `zones_layout`, `elements_editables`, `elements_immuables`, `zones_strategie`, `resume`

- **Conserver comme projections**.
- Ajouter un mode diagnostic détaillé.

### Fonctions

#### `comprendre_page`

- **Conserver comme façade**.
- Ne doit plus décider seule qu’un élément est immuable.
- Appeler les services universels de classification et de provenance.

#### `_decision_zone_ia`

- **Réécrire** pour retourner des candidats de rôle avec scores.
- Interdire les décisions de suppression basées sur une seule classe AI.

#### `filtrer_elements_proteges`, `filtrer_elements_selon_comprehension`

- **Déprécier puis supprimer** comme fonctions destructives.
- Les remplacer par `annoter_elements_selon_comprehension`.

#### `_aire`, `_intersection`, `_recouvrement_source`, `_clip_bbox`, `_fusionner_zones`, `_touche_zone`, `_centre_dans`

- **Déplacer** vers `analysis/geometry.py`.

#### `_zone_ia_deja_decrite_par_source`

- **Déplacer** vers `analysis/provenance.py`.
- Produire relation de doublon, pas suppression.

#### `_lignes_dans_formes_simples`, `_forme_simple_texte`, `_zones_bandeaux_couleur_formes_avec_texte`

- **Conserver comme détecteurs de relations**.
- Ajouter confiance et z-order.

#### `_zones_visuelles_protegees`, `_zones_tables_bandeaux_avec_texte`, `_zones_visuelles_bloquantes`, `_zones_vectorielles_bloquantes`, `_dans_zone_bloquante_texte`, `_lignes_dans_zones_visuelles_protegees`

- **Réécrire** en construction de contraintes de rendu.
- Ne jamais supprimer le texte sans décision de provenance.

#### `_recouvrement_source`, `_table_dense`, `_table_a_du_texte`, `_zone_formula_like`, `_is_color_band`, `_is_page_border`

- **Déplacer** les helpers vers détection/geometry.

#### `_zones_vectorielles_complexes`, `_zones_conteneurs_visuels`, `_clusteriser`

- **Conserver et améliorer** avec graphe de groupes et z-order.
- Ne plus rasteriser sans plan de fallback explicite.

#### `_detecter_colonnes`, `_detecter_regions_colonnes`

- **Déplacer** vers `analysis/reading_order.py`.
- Retourner bandes et scores, pas seulement un nombre de colonnes.

---

## 10. Module `pdfexact/layout/planner.py`

### Rôle cible

Transformer les observations de compréhension en contraintes et propositions de rendu, sans filtrage destructif.

### Types et fonctions

#### `LayoutPlanItem`

- **Conserver temporairement**.
- Ajouter `element_ids`, `reason_codes`, `conflicts`, `fallback`.

#### `planifier_regions`

- **Réécrire** pour produire des `RenderDecision` et non seulement des stratégies textuelles.

#### `zones_protegees_du_plan`, `zones_ocr_du_plan`, `zones_ocr_dur_du_plan`, `zones_layout_du_plan`

- **Conserver comme projections pour compatibilité**.
- Ne doivent plus être utilisées directement pour supprimer des éléments.

#### `filtrer_elements_selon_plan`

- **Déprécier puis supprimer**.
- Remplacer par `annoter_elements_selon_plan` et `resoudre_conflits_plan`.

#### `_zones_texte_du_plan`, `_fusionner_zones`, `_touche_zone`, `_texte_dans_zone_protegee`, `_texte_dans_zone_autorisee`, `_aire`, `_intersection`, `_centre_dans`

- **Déplacer** la géométrie et convertir les autres en fonctions d’annotation.

#### Alias `plan_regions`

- **Conserver temporairement** avec avertissement de dépréciation.

---

## 11. Module `pdfexact/layout/text_comprehension_ai.py`

### Rôle cible

Fournir des hypothèses AI normalisées. L’IA ne doit jamais écrire directement dans l’IR final ni supprimer un élément.

### Fonctions

#### `creer_fournisseur_comprehension_texte_ai`

- **Conserver**.
- Encapsuler score, modèle, prompt, version et réponse brute.
- Ajouter validation de schéma et fallback `unknown`.

#### `creer_fournisseur_orientation_ai`

- **Conserver**.
- Retourner angle, courbure, sens de lecture et confiance.

#### `_orientation_depuis_json`

- **Réécrire** avec validation stricte des angles et classes.

#### `_decision_depuis_json`

- **Réécrire** pour produire une suggestion, jamais une décision finale.

### Ajouts

- `valider_reponse_ai(data)` ;
- `fusionner_hypotheses_ai_native(...)` ;
- `calculer_confiance_fusion(...)` ;
- `marquer_conflit_ai_native(...)`.

---

## 12. Module `pdfexact/render/native_contract.py`

### Rôle cible

Ce module devient le validateur du contrat Word-native et un adaptateur de compatibilité. Il ne doit plus être un second moteur de regroupement.

### Types

#### `DiagnosticWordNative`

- **Conserver**.
- Ajouter compteurs par `element_id`, modes de rendu, pertes d’éditabilité, frames et divergences.

#### `CorrectionWordNative`

- **Conserver temporairement**.
- Renommer conceptuellement en `NativeAdaptationReport`.
- Ne plus corriger silencieusement les paragraphes après décision.

### Fonctions

#### `inspecter_docx_word_native`

- **Conserver et étendre**.
- Inspecter runs, paragraphes, frames, anchors, z-order, textes, relations et provenance si stockée.

#### `_texte_ligne`, `_style_ligne`

- **Déplacer** vers `analysis/semantic.py` ou `scene.py`.

#### `_paragraphe_depuis_ligne`, `_paragraphe_depuis_groupe`

- **Déprécier** leur création autonome.
- Les remplacer par `materialiser_decision_native_flow` dans le renderer unique.

#### `_copier_spans_ligne`, `_texte_span_paragraphe`

- **Conserver comme helpers de materialisation**.

#### `_interligne_groupe`, `_alignement_groupe`, `_alignement_vertical_groupe`

- **Déplacer** vers `analysis/semantic.py` pour produire les attributs du plan.

#### `_lignes_textbox`, `_zones_visuelles_page`, `_forme_fond_de_texte`

- **Déplacer** vers les adaptateurs de scène et de géométrie.

#### `_ligne_touche_zone`, `_ligne_eligible_paragraphe`, `_ligne_dans_frame_texte_fiable`

- **Remplacer** par une décision de sécurité dans `decisions.py`.

#### `_texte_ligne_semantique`, `_groupe_semantiquement_paragraphe`, `_memes_styles`, `_meme_paragraphe`, `_commence_item_liste`, `_groupe_bloc_detecte`

- **Déplacer** vers `analysis/semantic.py`.
- Retirer dépendance à la casse seule et aux seuils codés.

#### `_colonnes_lignes_sans_frame`, `_groupes_paragraphes_sans_frame`, `_groupes_paragraphes_frame`, `_groupes_paragraphes_frame_par_colonne`, `_continuite_semantique`

- **Déplacer entièrement** vers le moteur de regroupement universel.
- Conserver des wrappers pendant une version.

#### `_assembler_textboxes_page`, `_textbox_depuis_lignes`

- **Supprimer après migration**.
- Le flux doit être créé par `semantic.py` + `decisions.py`, avant le renderer.

#### `corriger_document_word_native`

- **Transformer** en validateur/adaptateur sans modification destructive de l’IR.
- À terme : `valider_contrat_word_native(document, render_plan)`.

---

## 13. Module `pdfexact/render/word_native_rewriter.py`

### Rôle cible

Devenir le renderer DOCX principal. Il reçoit une scène et un `RenderPlan` déjà décidés. Il ne doit plus classifier, regrouper ou filtrer les éléments.

### Fonctions de géométrie et inspection

#### `_element_id`, `_area`, `_intersection`, `_overlap_ratio`, `_inside_page`

- **Déplacer** dans les modules communs.
- Garder wrappers temporaires pour compatibilité.

#### `_orientation`, `_role`, `_layout_role`

- **Supprimer de la décision locale**.
- Lire les attributs normalisés de `ElementRecord`.

#### `_lines`, `_is_plain_flow`, `_visuals`, `_text_elements`, `_line_text`, `_first_span`, `_same_text_style`

- **Conserver seulement comme fonctions de materialisation**.
- `_is_plain_flow` devient `decision.mode == NATIVE_FLOW`.

### Listes et regroupement

#### `_starts_list_item`, `_starts_lowercase_continuation`, `_is_text_marker`, `_marker_kind`, `_normaliser_listes`

- **Déplacer** dans `analysis/semantic.py`.
- Supprimer les seuils de liste spécifiques au renderer.

### Régions et continuité

#### `_bbox_union`, `_visual_text_region`, `_roles_compatibles_pour_region`, `_inferred_text_region`, `_is_compact_positioned_text`, `_line_step_emu`, `_spans_ajustes_a_la_ligne`, `_positioned_text_region`

- **Déplacer** dans `analysis/geometry.py` et `analysis/semantic.py`.
- Le renderer ne doit recevoir que la région validée du plan.

#### `_can_join_flow_lines`, `_regrouper_flow_paragraphes`, `_fusionner_flow_paragraphes`, `_regrouper_continuations_par_frame`, `_regrouper_continuations_par_colonne`

- **Supprimer du renderer** après migration vers `semantic.py`.

### Décision

#### `_visual_region_for_text`, `_has_multiple_columns`, `_looks_embedded_in_visual`, `_decision`

- **Supprimer comme centres de décision locaux**.
- Remplacer par `render_plan.decision_for(element_id)`.
- `_looks_embedded_in_visual` devient une preuve d’occlusion/doublon dans `appearance.py`.

### XML de texte

#### `_flow_runs`, `_list_properties_xml`, `_line_height`

- **Conserver** comme primitives de rendu.
- Lire uniquement les propriétés du `RenderDecision`.

#### `_flow_paragraph_xml`, `_positioned_flow_paragraph_xml`

- **Conserver et réécrire** pour respecter exactement la géométrie du plan.
- Ne plus ajuster silencieusement la taille ou les lignes.
- Toute adaptation doit produire un diagnostic.

### Frames et orientation

#### `_frame_body_properties`, `_frame_shape_rotation`, `_text_warp`, `_vertical_text_line_spacing_twips`, `_vertical_rotated_text_xml`, `_text_frame_graphic`, `_frame_xml`, `_vertical_vml_frame_xml`

- **Conserver les primitives**, mais les piloter par `OrientationSpec`.
- Ajouter profils de compatibilité Word/LibreOffice/WPS.
- Le texte vertical doit conserver taille, baseline, direction et bbox source.
- Le texte courbé doit avoir un mode explicite : segmenté éditable ou fallback local.

#### `_host_paragraph`

- **Conserver** comme conteneur technique.
- Interdire qu’il reçoive des éléments hors de l’ordre de peinture calculé.

### Formes et sections

#### `_shape_should_overlay`

- **Supprimer la règle heuristique locale**.
- Utiliser `z_order` et `occlusion_status` du plan.

#### `_section_xml`

- **Conserver**.
- Centraliser dimensions, marges, orientation et sections dans `section_layout.py`.

### `rewrite_document_xml`

- **Conserver comme point d’entrée unique**.
- Nouvelle séquence : valider scene -> charger RenderPlan -> ordonner par z-order -> rendre chaque décision -> enregistrer mapping source/XML -> produire diagnostic.
- Ne plus trier par `image_parts`, `shape_parts`, `flow_parts` sans tenir compte de l’ordre de peinture.
- Ne plus déduire les décisions durant le rendu.

---

## 14. Module `pdfexact/render/docx_writer.py`

### Rôle cible

Ce module ne doit plus être un second moteur de reconstruction. Il devient une façade de compatibilité ou disparaît progressivement.

### Fonctions de tables et sections

#### `_tableau_dense_exact`, `_bbox_dans_table_dense`

- **Déplacer** vers `analysis/table_detection.py`.
- Retourner une décision de table, pas choisir le backend.

#### `_section_xml`, `_section_flux_xml`, `_paragraphe_section_minimal_xml`

- **Déplacer** vers `render/section_layout.py`.
- Utiliser la même section que `word_native_rewriter.py`.

### Fonctions de couches et ancres

#### `_elements_avec_ombres_derriere`, `profil`, `_ordonner_bandeaux_sur_images`, `_est_bandeau_sur_image`, `_profil_image_media`, `_recouvrement_min_bbox`, `_table_recouvre_texte_positionne`

- **Supprimer les politiques locales**.
- Remplacer par le z-order du scene graph et les relations de compositing.

#### `_table_fond_grille_xml`, `_ancres_de_page`, `_ancres_xml`, `_ancres_visuelles_xml`

- **Conserver les primitives utiles**.
- Les faire appeler par le renderer unique.

### Fonctions de typographie et fit

#### `_fond_pour_paragraphe`, `_couleur_sombre`, `_couleur_claire`, `_forme_fond_blanc_page`

- **Déplacer** vers `analysis/appearance.py` et `render/background.py`.
- Ne pas modifier le texte selon la couleur sans décision auditée.

#### `_copier_span`, `_span_reflow`, `_span_avec_texte`, `_spans_sans_bords_vides`, `_spans_reflow_ligne`

- **Conserver** comme utilities de spans.
- Centraliser dans `render/text_runs.py`.

#### `_ajuster_spans_a_largeur`, `_ajuster_spans_a_boite`

- **Réécrire fortement**.
- Priorité : conserver police et taille ; ensuite frame ; ensuite fallback local ; compression typographique seulement en option explicite.
- Chaque changement doit être inscrit dans `AuditRecord`.

#### `_paragraphe_fond_fixe_xml`, `_paragraphe_flux_xml`

- **Déplacer** vers le renderer unique.
- Supprimer les clamps silencieux d’interligne.

### Images et reflow

#### `_image_inline_xml`, `_espace_vertical_xml`

- **Conserver** comme primitives.
- Leur usage doit venir d’un `RenderDecision`.

#### `_ligne_depuis_paragraphe`, `_lignes_depuis_paragraphe`, `_ligne_ajustee_largeur`, `_ligne_prose_probable`, `_paragraphe_ajuste_largeur`, `_texte_ligne_reflow`, `_paragraphe_reflow_naturel`

- **Déplacer** dans `analysis/semantic.py` ou `render/reflow.py` selon responsabilité.
- Ne pas les exécuter automatiquement sur toute page.
- Reflow seulement si `decision.safe_reflow == True`.

### Colonnes et grilles

#### `_colonnes_flow`, `_paragraphes_pleine_largeur_flow`, `_fusionner_colonnes_traversees`

- **Déplacer** dans `analysis/reading_order.py`.
- Les colonnes deviennent des régions textuelles prouvées, pas une simple différence de x.

#### `_table_colonnes_flow_xml`

- **Supprimer comme représentation par défaut**.
- Conserver uniquement pour une décision explicite `NATIVE_TABLE` ou `POSITIONED_LAYOUT_TABLE`.

#### `_bornes_stables`, `_fusionner_fragments_meme_ligne`, `_grille_vertical_layout`, `_grille_regions_flow_xml`

- **Déprécier puis supprimer** comme substitut général du flow.
- Remplacer par paragraphes/runs, frames ou tables sémantiques selon le plan.

### Pages

#### `_page_absolue_xml`, `_page_flux_xml`, `_page_tableau_exacte`

- **Réduire** à des adaptateurs de compatibilité.
- Le choix de page est fait dans `RenderDecision`/`RenderPlan`.

#### `_nombre_lignes_paragraphe`, `_echelle_verticale_flux`

- **Déplacer** vers `analysis/layout_constraints.py`.
- `_echelle_verticale_flux` ne doit plus déformer silencieusement une page ; elle devient un diagnostic ou une option explicite.

#### `construire_document_xml`

- **Conserver comme façade legacy**.
- Déléguer intégralement à `word_native_rewriter.rewrite_document_xml` après migration.
- Marquer la voie historique comme dépréciée.

---

## 15. Module `pdfexact/render/drawing.py`

### Rôle cible

Bibliothèque de primitives OOXML. Ce module ne décide plus si une zone est un paragraphe, une image, une table ou un fallback.

### Fonctions

#### `_ancre`

- **Conserver**.
- Ajouter support uniforme de z-order, wrap, relativeFrom et anchorLock.

#### `_bbox_ligne_word`

- **Déplacer** vers `render/geometry_adapter.py`.
- Utiliser quad/orientation lorsqu’un élément n’est pas horizontal.

#### `_run_xml`, `_runs_paragraphe`

- **Conserver et centraliser** dans `render/text_runs.py`.
- Garantir conservation des styles, liens, espacement, exposants et langue.

#### `_couleur_sombre`, `_rotation_ooxml`, `_copier_span`

- `_couleur_sombre` -> `analysis/appearance.py`.
- `_rotation_ooxml` -> `render/orientation_backend.py`.
- `_copier_span` -> `render/text_runs.py`.

#### `_runs_ligne_avec_leader`, `_largeur_texte_pt`, `_ligne_leader_visuelle_xml`

- **Conserver** comme rendu spécialisé de leaders/table des matières.
- Recevoir une décision explicite et une métrique de police.

#### `_zone_texte_simple_xml`, `zone_texte_xml`

- **Conserver** comme backend de texte positionné.
- Ne pas choisir le mode de positionnement à l’intérieur de la fonction.

#### `_interligne_paragraphe`, `_nombre_lignes_paragraphe`, `_bbox_paragraphe_word`

- **Déplacer** le calcul sémantique dans `analysis/layout_constraints.py`.
- Garder uniquement conversion vers OOXML dans `drawing.py`.

#### `zone_paragraphe_xml`

- **Conserver** comme primitive.
- Doit recevoir une décision `POSITIONED_TEXT` ou `EDITABLE_FRAME`.

#### `image_xml`

- **Conserver**.
- Ajouter alt text, provenance, crop, alpha et mapping source.

#### `_span_ajuste_espacement_cellule`, `_span_contraste_cellule`, `_union_bbox`, `_bbox_spans_cellule`, `_marges_cellule_twips`, `_hauteurs_lignes_table`

- `_union_bbox` -> geometry.
- Les autres restent dans `render/table_backend.py`.
- Aucun ajustement typographique silencieux.

#### `table_body_xml`, `_lignes_cellule_overlay`, `_est_fallback_cellule`, `table_text_overlays_xml`, `_positions_uniques_table`, `_positions_x_table`, `_positions_y_table`, `table_grid_overlays_xml`, `table_cell_background_overlays_xml`, `table_xml`

- **Déplacer** dans `render/table_backend.py`.
- Séparer table sémantique, grille visuelle et overlays.
- Le choix entre eux vient du plan universel.

#### `_rect_rempli_xml`, `_commandes_xml`, `forme_xml`

- **Conserver** dans `render/shape_backend.py`.
- Ajouter clipping, alpha, stroke, path et ordre de peinture.

#### `zone_lien_xml`

- **Conserver**.
- Utiliser provenance et bbox canonique.

---

## 16. Module `pdfexact/render/package.py`

### Rôle cible

Emballage OOXML uniquement. Aucune décision sémantique ou de layout.

### Fonctions et types

#### `Relations.__init__`, `ajouter`, `vers_xml`

- **Conserver**.
- Ajouter détection de doublons, types de relations validés et mapping source.

#### `_style_police`

- **Déplacer** vers `render/font_backend.py`.

#### `_table_polices_xml`

- **Conserver puis étendre** : embedding, substitution, métriques et diagnostic.

#### `ecrire_docx`

- **Conserver comme unique point d’écriture**.
- Ne plus choisir entre deux writers par booléen sans `RenderPlan`.
- Signature cible :

```python
ecrire_docx(document, chemin, render_plan, package_options)
```

- Ajouter validation ZIP/XML, relations, media, numbering, styles et provenance.
- Ajouter manifest interne optionnel des éléments pour l’audit.

### Ajouts

- `valider_package_ooxml(chemin)` ;
- `valider_relations(chemin)` ;
- `valider_medias(chemin)` ;
- `valider_fonts(chemin)` ;
- `exporter_manifest_render(chemin, render_plan)`.

---

## 17. Module `pdfexact/final_audit.py`

### Rôle cible

Audit et correction locale pilotés par la scène canonique. Aucun score global ne peut compenser un élément absent.

### Types à ajouter

#### `AuditRecord`

Champs :

- `element_id` ;
- présence source/sortie ;
- rappel et précision texte ;
- ordre des tokens ;
- IoU bbox et quad ;
- angle et baseline ;
- police, taille et style ;
- visibilité réelle ;
- z-order ;
- mode DOCX et éditabilité ;
- statut et causes.

#### `AuditReport`

- résultats par élément ;
- résultats par zone ;
- résultats par page ;
- erreurs critiques ;
- corrections appliquées ;
- éléments non représentables.

### Fonctions

#### `certifier_et_reparer`

- **Réécrire** comme boucle contrôlée : audit -> correction locale -> rerender -> audit.
- Nombre maximal de passes configurable.
- Ne jamais déclarer conforme sur ratio texte seul.

#### `_detecter_pages_source`

- **Conserver** comme acquisition des pages de contrôle.

#### `_auditer_couverture_visuelle`

- **Conserver et détailler par élément**.
- Une grande image ne doit pas compenser un texte manquant.

#### `_normaliser_zone_visuelle`, `_zone_couverte`, `_ratio_couverture`, `_aire`, `_intersection`

- **Déplacer** la géométrie commune et comparer bboxes/quads.

#### `_auditer_tables_reconstituees`

- **Conserver et étendre** : lignes, cellules, bordures, contenu, dimensions et mode sémantique.

#### `_retirer_table`, `_inserer_visuel_recupere`, `_retirer_elements_dans_zone`

- **Déprécier les opérations destructives directes**.
- Remplacer par mutations tracées du `RenderPlan` avec rollback.

#### `_zone_contient_texte_word`, `_centre_dans_zone`, `_ratio_intersection`

- **Déplacer** vers geometry et utiliser les tokens/source IDs.

#### `_tokens_texte`, `_orientation_texte`, `_tokens_visibles_dans_bbox`, `_taille_texte`, `_texte_imprime_dans_visuel`

- **Conserver et renforcer**.
- Comparer rappel, précision, ordre, orientation, taille et visibilité après z-order.

#### `_auditer_structure_ir`

- **Conserver et étendre** pour vérifier les invariants de scène.

#### `_compter_mots_pdf`

- **Conserver comme métrique secondaire uniquement**.

#### `_auditer_texte_visible`

- **Réécrire par élément**.
- Un texte horizontal ne valide pas un texte vertical.

#### `_auditer_texte`

- **Réduire** le rôle du ratio global.
- Le remplacer par agrégation de `AuditRecord` avec seuils par importance.

#### `_auditer_similarite_zones_finales`, `_auditer_similarite_visuelle`

- **Conserver**, mais compléter par edge/text weighting, zones critiques et z-order.

#### `_exporter_docx_pdf`

- **Conserver**.
- Ajouter profils de lecteur et capture des warnings.

#### `_supprimer_fichier_temporaire`

- **Conserver**.

#### `_similarite_page`, `_similarite_zone`

- **Réécrire** : la différence moyenne grayscale devient une métrique secondaire.
- Ajouter similarité structurelle, edges, OCR/token alignment et zones critiques.

#### `bbox_debug_pt`

- **Conserver** pour diagnostics.

### Ajouts

- `auditer_element_source(...)` ;
- `auditer_z_order(...)` ;
- `auditer_overflow(...)` ;
- `auditer_editability(...)` ;
- `auditer_font_metrics(...)` ;
- `construire_corrections_locales(...)` ;
- `appliquer_correction_avec_rollback(...)` ;
- `verdict_page(...)` ;
- `verdict_document(...)`.

---

## 18. Module `pdfexact/cli.py`

### Rôle cible

Orchestration uniquement. Toutes les décisions métier doivent être déléguées aux modules universels.

### Fonctions

#### `analyser_pages`

- **Conserver**.
- Valider expression et limites sans logique de reconstruction.

#### `convertir`

- **Réécrire** en pipeline fixe :

```text
parse options
 -> extract scene
 -> understand scene
 -> semantic grouping
 -> build render plan
 -> validate invariants
 -> render DOCX
 -> audit rendered DOCX
 -> local repairs
 -> final report
```

- Supprimer les conditions qui choisissent des moteurs concurrents sur des combinaisons implicites.
- Exposer un profil, pas une branche cachée.

#### `_analyseur`

- **Conserver et clarifier** les options.
- Ajouter profils `balanced`, `visual-first`, `editable-first`, `compatibility-word`, `compatibility-libreoffice`.

#### `main`

- **Conserver** comme façade CLI.
- Retourner code d’erreur si des éléments critiques sont perdus ou non vérifiés.

---

## 19. Modules nouveaux de rendu

### `pdfexact/render/render_plan.py`

Fonctions :

- `construire_render_plan(scene, understanding, options)` ;
- `ordonner_render_plan(plan)` ;
- `valider_render_plan(plan)` ;
- `indexer_decisions(plan)` ;
- `calculer_fallbacks(plan)`.

### `pdfexact/render/text_backend.py`

Fonctions :

- `rendre_native_flow` ;
- `rendre_native_list` ;
- `rendre_positioned_text` ;
- `rendre_editable_frame` ;
- `rendre_text_on_path_segmented` ;
- `rendre_text_fallback_local`.

### `pdfexact/render/image_backend.py`

Fonctions :

- `rendre_image_inline` ;
- `rendre_image_anchor` ;
- `rendre_raster_composite` ;
- `rendre_alt_text`.

### `pdfexact/render/table_backend.py`

Fonctions :

- `rendre_table_native` ;
- `rendre_table_positioned` ;
- `rendre_grid_visual` ;
- `valider_cell_geometry`.

### `pdfexact/render/shape_backend.py`

Fonctions :

- `rendre_shape` ;
- `rendre_path` ;
- `rendre_fill_stroke` ;
- `rendre_clip` ;
- `rendre_transparency`.

### `pdfexact/render/compatibility.py`

Fonctions :

- `profil_lecteur(name)` ;
- `feature_supported(profile, feature)` ;
- `fallback_for(profile, feature)` ;
- `record_reader_risk(...)`.

---

## 20. Fonctions à supprimer ou déprécier globalement

Après migration et tests, supprimer les catégories suivantes :

1. filtres qui retirent un élément uniquement parce qu’il intersecte une zone ;
2. décisions locales de `flow` ou `frame` dans plusieurs fichiers ;
3. regroupements de lignes dupliqués ;
4. seuils géométriques codés dans les renderers ;
5. tables de positionnement utilisées comme solution générale au flux ;
6. compression automatique de police sans diagnostic ;
7. rasterisation globale déclenchée par l’audit sans rapport d’éditabilité ;
8. scores de conformité basés uniquement sur nombre total de mots ou différence moyenne d’image ;
9. classement des couches par catégorie plutôt que par z-order canonique ;
10. création de `FlowParagraph` dans les extracteurs avant décision sémantique.

---

## 21. Options universelles à conserver et à centraliser

Toutes les options doivent vivre dans une structure unique, par exemple `ConversionOptions` :

```python
ConversionOptions(
    source_text="native+ocr",
    use_layout_ai=True,
    language="auto",
    detect_orientation=True,
    detect_curves=True,
    preserve_line_boundaries="auto",
    visual_priority=0.8,
    editability_priority=0.8,
    allow_local_raster_fallback=True,
    target_reader="word",
    audit_level="element",
    max_repair_passes=2,
)
```

### Options autorisées

- source OCR/native ;
- provider AI ;
- langue et script ;
- niveau de détection ;
- priorité visuelle/éditabilité ;
- profil de lecteur ;
- fallback autorisé ;
- niveau d’audit ;
- budget de réparation.

### Options interdites

- supprimer les éléments sans rapport ;
- désactiver la traçabilité ;
- ignorer le z-order ;
- ignorer les éléments non reconnus ;
- déclarer conforme sur une métrique globale seulement.

---

## 22. Tests à ajouter et à déplacer

### Tests de contrats

- chaque élément de scène reçoit un `element_id` ;
- aucun élément n’est perdu sans `reason_code` ;
- toute décision a une représentation et un fallback ;
- tout fallback est vérifiable ;
- le z-order est total et stable ;
- les coordonnées restent dans le même repère.

### Tests de sémantique

- paragraphes mono-colonne ;
- colonnes ;
- listes par puces/tirets/symboles dessinés ;
- adresses et titres volontairement séparés ;
- CJK, arabe, texte tout en capitales ;
- captions et crédits ;
- textes verticaux, obliques et courbés.

### Tests de rendu

- runs natifs ;
- images et formes z-order ;
- tables ;
- frames éditables ;
- VML/WPS ;
- fonts substituées ;
- overflow ;
- multi-pages et sections.

### Tests d’audit

- texte présent mais recouvert ;
- texte horizontal à la place du vertical ;
- bonne quantité de mots mais ordre faux ;
- image correcte mais forme de fond erronée ;
- éléments absents ;
- doublons natif/OCR ;
- texte dans une image ;
- fallback raster local déclaré.

### Golden corpus

Créer un corpus avec au moins :

1. brochure type St. Lawrence ;
2. article à deux colonnes ;
3. formulaire ;
4. tableau irrégulier ;
5. carte vectorielle ;
6. scan incliné ;
7. texte vertical ;
8. texte courbé ;
9. image avec texte intégré ;
10. polices Type3 et substitutions ;
11. transparence et clipping ;
12. document RTL/CJK.

Chaque cas doit conserver : PDF source, scène IR, RenderPlan, DOCX, PDF de contrôle, AuditReport et verdict.

---

## 23. Ordre de migration sans perte des acquis

### Étape 1

Ajouter les contrats `scene.py`, `options.py`, `decisions.py`, `geometry.py`, `provenance.py` sans modifier le rendu.

### Étape 2

Brancher `document.py`, `layout_map.py`, `understanding.py` sur les nouveaux contrats en mode observation.

### Étape 3

Déplacer les regroupements vers `semantic.py`, mais comparer ancien et nouveau regroupement dans les tests.

### Étape 4

Créer `RenderPlan` à partir des deux décisions et détecter les divergences.

### Étape 5

Faire rendre `word_native_rewriter.py` à partir de `RenderPlan`.

### Étape 6

Faire déléguer `docx_writer.py` au renderer unique.

### Étape 7

Faire de `drawing.py` un backend de primitives sans décisions.

### Étape 8

Transformer `final_audit.py` en audit par élément et correction locale.

### Étape 9

Activer le registre de pertes et faire échouer les tests en cas d’élément silencieusement absent.

### Étape 10

Supprimer les fonctions dépréciées après validation du corpus complet.

---

## 24. Critères de réussite

La refonte sera considérée réussie lorsque :

1. un seul `RenderPlan` décide du mode de chaque élément ;
2. aucun renderer ne fait de classification ou de regroupement ;
3. aucun extracteur ne crée directement un paragraphe final ;
4. les anciens et nouveaux chemins produisent des décisions comparables ;
5. chaque élément source est retrouvé dans le DOCX ou déclaré explicitement non représentable ;
6. les audits détectent les erreurs locales malgré une image dominante ;
7. les corrections appliquées à un PDF restent actives sur les autres classes ;
8. les options modifient seulement les politiques déclarées ;
9. Word et LibreOffice disposent de profils de compatibilité testés ;
10. le code ne contient plus plusieurs politiques concurrentes de z-order, regroupement ou filtrage.

---

## 25. Verdict architectural

Le projet ne doit pas continuer à empiler des correctifs dans les renderers. La priorité est de reconstruire les frontières de responsabilité :

```text
Extraction       = observer
Compréhension    = classer
Sémantique       = regrouper
Décision         = choisir une représentation
Renderer         = écrire
Package          = emballer
Audit            = comparer
Correction       = réparer localement et tracer
```

Les modules universels ne doivent pas connaître les cas particuliers d’un PDF donné. Les cas particuliers deviennent des **preuves**, des **options**, des **scores** ou des **fallbacks** dans les contrats communs.

La finalité n’est pas d’obtenir un code plus abstrait pour lui-même. La finalité est que la correction d’un problème de flux, de position, de puce, de texte vertical, de police, de superposition ou d’image soit appliquée par le même mécanisme à tous les documents, au lieu d’être attachée à la branche qui avait rencontré le premier exemple.

