**Projet :** converter / pdfexact  
**Date de l'audit :** 6 octobre 2026  
**Périmètre :** extraction, compréhension de page, regroupement sémantique, reconstruction Word-native, emballage OOXML et audit final  
**Question auditée :** le pipeline peut-il produire un DOCX visuellement conforme au PDF, éditable dans Word et en flux natif, pour un PDF quelconque ?

---

## 1. Verdict exécutif

### Conclusion courte

**Non, pas pour n'importe quel PDF au sens strict.** Le pipeline est désormais solide pour une famille importante de documents : brochures et rapports composés de texte natif, images, blocs horizontaux, listes, tableaux détectables, légendes et quelques textes verticaux. Les corrections récentes ont amélioré la conservation des runs, des puces, du flux Word et des crédits verticaux.

Cependant, l'architecture actuelle reste **heuristique et non universelle**. Elle ne peut pas garantir simultanément :

1. la fidélité visuelle pixel par pixel ;
2. la conservation de chaque élément ;
3. un texte intégralement éditable en paragraphes Word natifs ;
4. la conservation exacte de l'ordre de peinture, des masques, des rotations, des courbes et des transformations arbitraires.

Ces garanties sont parfois incompatibles avec le modèle DOCX. Un PDF décrit principalement une **surface peinte** ; un DOCX décrit une **structure de contenu et un moteur de mise en page refluable**. Le convertisseur doit donc effectuer une interprétation, et toute interprétation doit porter une confiance et un mécanisme de repli.

### Niveau global estimé

| Domaine | État actuel | Verdict |
|---|---:|---|
| Texte PDF natif horizontal simple | Fort | Généralement fiable |
| Paragraphes et listes courants | Bon | Fiable avec cas limites |
| Images positionnées | Bon | Visuellement solide |
| Tableaux géométriquement réguliers | Bon | Dépend de la détection |
| Texte vertical simple | Bon après le correctif VML | Cas pris en charge, fragile selon les lecteurs |
| Colonnes et panneaux imbriqués | Moyen à bon | Seuils et heuristiques sensibles |
| PDF scanné / OCR | Moyen | Dépend fortement de l'OCR et du layout AI |
| Texte courbé ou sur chemin | Faible à moyen | Pas de modèle général de courbe |
| Masques, transparence, clipping, groupes vectoriels | Faible | Repli raster souvent nécessaire |
| Polices Type3, encodage incomplet, glyphes sans Unicode | Faible | Extraction parfois impossible |
| Arabe, CJK, langues sans casse, script vertical complexe | Moyen à faible | Heuristiques de regroupement insuffisantes |
| Conformité universelle à tout PDF | Non démontrée | Impossible avec les garanties actuelles |

### Risques critiques

**P0 - Risque conceptuel :** plusieurs couches décident, filtrent et regroupent le texte avec des heuristiques différentes. Un élément peut être filtré dans l'extraction, conservé par l'IR mais rejeté par le rewriter, ou réintroduit par un fallback. Il n'existe pas encore d'invariant central « aucun élément silencieusement perdu ».

**P0 - Risque de rendu :** l'ordre de peinture du PDF est approximé par des bandes de fond, des ancres et des paragraphes. Cette approximation ne garantit pas le z-order réel lorsqu'il y a superposition, transparence, clipping ou texte inclus dans un visuel.

**P0 - Risque d'audit :** l'audit final mesure surtout la couverture textuelle et une différence d'image globale. Une grande photo peut masquer une erreur de texte, de police, d'ordre ou de positionnement. L'audit peut donc déclarer acceptable un document qui n'est pas conforme dans une zone importante.

**P1 - Risque sémantique :** les paragraphes, listes et continuations sont reconstruits à partir de seuils géométriques, de casse et de ponctuation. Cette logique n'est pas suffisamment multilingue ni consciente des frontières de blocs.

**P1 - Risque de typographie :** l'ajustement à la largeur peut réduire la taille de police ou utiliser l'espacement de caractères. Le texte tient dans la boîte, mais le rendu n'est alors plus celui du PDF.

**P1 - Risque d'architecture :** `docx_writer.py` et `word_native_rewriter.py` constituent deux moteurs de reconstruction concurrents. Ils n'ont pas toujours les mêmes règles de regroupement, de positionnement, d'ancrage et de fallback.

---

## 2. Limite fondamentale : PDF et DOCX ne portent pas le même contrat

### 2.1 PDF

Le PDF peut fournir :

- des opérateurs de texte et des glyphes sans notion fiable de paragraphe ;
- des transformations de matrice, rotations et textes sur chemin ;
- des images, masques, clipping paths, transparences et modes de fusion ;
- des formes vectorielles, groupes et ordre de peinture ;
- des polices embarquées dont la correspondance Unicode peut être absente ou incorrecte ;
- une apparence visuelle sans intention sémantique ni ordre de lecture explicite.

### 2.2 DOCX

DOCX distingue notamment :

- paragraphes et runs refluables ;
- tableaux et cellules ;
- images inline ou flottantes ;
- formes et textboxes ancrées ;
- relations, médias, styles, numbering et sections ;
- un moteur de mise en page qui peut varier entre Word, LibreOffice et WPS.

Une reconstruction générale doit donc choisir une représentation par élément :

```text
PDF paint operation
        |
        v
IR element + geometry + role + confidence + source provenance + z-order
        |
        +--> safe native paragraph/run
        +--> native list paragraph
        +--> native table/cell
        +--> anchored editable text frame
        +--> anchored image/shape
        +--> controlled raster fallback
        +--> unresolved/diagnostic, never silent discard
```

Le problème n'est pas seulement de générer du XML valide. Il faut décider **quel contrat éditable et visuel est encore possible** pour chaque élément.

---

## 3. Chaîne complète auditée

### 3.1 Flowchart principal

```text
[PDF]
   |
   v
[PDF natif + OCR + images + vecteurs + layout AI]
   |
   v
[IR: Element, Span, Line, Frame, Page, provenance]
   |
   +--> [filtres de zones / protection des visuels]
   +--> [déduplication natif-OCR]
   +--> [attachement aux frames]
   |
   v
[compréhension: rôle, orientation, bloc, liste, tableau, colonne]
   |
   v
[groupement sémantique et reflow]
   |
   v
[décision de rendu par élément]
   |
   +--> flow Word-native
   +--> paragraphe positionné
   +--> frame editable ancré
   +--> table
   +--> image / forme
   +--> raster fallback
   |
   v
[document.xml + styles + numbering + media + relations]
   |
   v
[DOCX]
   |
   v
[rendu Word/LibreOffice -> PDF de contrôle]
   |
   v
[audit visuel + audit texte + audit géométrique]
   |
   +--> [réparation locale et rerendu]
   +--> [rapport de confiance / anomalies]
```

### 3.2 Invariant qui manque aujourd'hui

Chaque élément détecté devrait avoir un état terminal explicite :

```text
DETECTED -> CLASSIFIED -> GROUPED -> RENDERED -> VERIFIED
                                      |
                                      +--> FALLBACK_RENDERED
                                      +--> AMBIGUOUS_REPORTED
                                      +--> FAILED_REPORTED
```

Dans l'implémentation actuelle, plusieurs filtres peuvent supprimer un élément avant qu'il atteigne un état terminal. C'est acceptable pour supprimer un doublon démontré, mais dangereux lorsqu'il s'agit d'un texte superposé, d'une légende, d'un crédit vertical ou d'un texte dans une image.

---

## 4. Audit du modèle intermédiaire et de l'extraction

### Fichiers concernés

- `pdfexact/ir.py`
- `pdfexact/extract/document.py`
- `pdfexact/extract/text.py`
- `pdfexact/extract/blocks.py`
- `pdfexact/extract/images.py`
- `pdfexact/extract/layout_map.py`
- `pdfexact/extract/ocr.py`
- `pdfexact/extract/orientation.py`

### Logique observée

`document.py` combine les objets natifs PDF, OCR, images, vecteurs et régions de layout. Pour le mode Word-native, `_extraire_texte_pdf_natif_word_native` transforme souvent les lignes natives en `FlowParagraph` unitaires, rattache les lignes à des frames et conserve les spans. Les lignes sans frame sont regroupées à partir de la proximité, du chevauchement horizontal et de propriétés de style.

### Flowchart d'extraction

```text
[Page PDF]
   |
   +--> texte natif disponible ? -- oui --> [spans natifs]
   |                                      |
   |                                      +--> ToUnicode fiable ?
   |                                      +--> matrice/orientation
   |
   +--> OCR activé ? --------------------> [lignes OCR + scores]
   |
   +--> images / vecteurs / IA ----------> [zones et classes]
                                           |
                                           v
                              [déduplication natif/OCR]
                                           |
                                           v
                              [attachement aux frames]
                                           |
                         +-----------------+------------------+
                         |                                    |
                   [frame fiable]                      [sans frame]
                         |                                    |
                  FlowParagraph                         regroupement
                                                              |
                                                              v
                                                   [IR text elements]
```

### Points solides

- conservation des spans et de leur style lorsque la source native le permet ;
- séparation des éléments texte, image, tableau et forme dans l'IR ;
- prise en compte de l'orientation et de la géométrie ;
- déduplication natif/OCR prévue ;
- présence de provenance et de bboxes exploitables par l'audit.

### Défauts de conception

1. **Un PDF ne fournit pas toujours une sémantique de paragraphe.** Faire une ligne PDF = un paragraphe initial protège la géométrie, mais impose ensuite une reconstruction heuristique. Cette étape doit porter le statut « ligne source », pas « paragraphe confirmé ».

2. **L'attachement à un frame par centre/recouvrement est ambigu.** Une ligne située entre deux panneaux ou sur une image peut être rattachée au mauvais bloc. Il manque un score global combinant centre, direction de lecture, z-order, style, continuité et rôle.

3. **Les zones sont essentiellement rectangulaires.** Pour un texte tourné, oblique, sur chemin ou dans un masque, une bbox axis-aligned perd une information indispensable.

4. **La déduplication peut supprimer du texte réel.** Le texte OCR et le texte natif peuvent être proches sans être le même élément, notamment lorsqu'un PDF contient une image avec du texte et une couche invisible d'accessibilité.

5. **La qualité Unicode n'est pas un invariant.** Si le PDF ne fournit pas de table ToUnicode exploitable, l'OCR ou la reconnaissance de glyphes doit être évaluée séparément ; sinon la reconstruction peut être visuellement plausible mais textuellement fausse.

### Risque généralisable

Le pipeline devrait conserver simultanément :

- `source_kind` : native, OCR, image, vector, inferred ;
- `source_id` et provenance ;
- `geometry` : bbox + quadrilatère ou polygone ;
- `z_order` et clipping ;
- `text_confidence` et `role_confidence` ;
- `duplicate_group_id` ;
- `decision_history`.

Sans cet historique, il est impossible de distinguer « non détecté », « volontairement dédoublonné », « filtré car considéré comme intégré à l'image » et « perdu dans la reconstruction ».

---

## 5. Audit de la compréhension de page et du layout AI

### Fichiers concernés

- `pdfexact/layout/understanding.py`
- `pdfexact/layout/planner.py`
- `pdfexact/layout/text_comprehension_ai.py`
- `pdfexact/extract/layout_map.py`

### Flowchart de compréhension

```text
[Éléments IR]
       |
       v
[layout AI disponible ?]
       |
   +---+---+
   |       |
  oui     non
   |       |
[classes] [heuristiques]
   |       |
   +---+---+
       v
[rôle + zone protégée + score]
       |
       +--> titre / paragraphe / liste / caption / credit
       +--> image / tableau / carte / forme / arrière-plan
       +--> texte intégré probable
       +--> inconnu
       |
       v
[plan de reconstruction]
```

### Points solides

- séparation entre compréhension de page et rendu ;
- possibilité de protéger une zone IA composite ;
- classes de rôle utiles pour les légendes, crédits, titres et blocs ;
- plan de régions réutilisable par plusieurs étapes.

### Risques de logique

1. **Le set de classes est fini, le PDF est ouvert.** Une carte, un schéma scientifique, une facture, un formulaire et une brochure ne partagent pas les mêmes catégories.

2. **Les seuils fixes ne s'adaptent pas assez au document.** Les seuils relatifs de taille, recouvrement et densité peuvent fonctionner sur une brochure et échouer sur une affiche, une note juridique ou une page A0.

3. **Une zone « image » peut contenir du texte réel.** Le marquage d'une zone comme composite doit distinguer : image opaque, image avec texte intégré, image avec texte natif superposé, et fond décoratif.

4. **L'incertitude est insuffisamment conservée.** Une classe erronée à haute confiance peut provoquer un filtrage irréversible. La décision correcte en cas de conflit devrait être de conserver les deux candidats jusqu'à la résolution géométrique ou au fallback.

5. **La compréhension sémantique ne doit pas décider seule de la visibilité.** L'IA peut proposer un rôle ; elle ne doit pas supprimer un élément sans preuve de doublon ou de recouvrement opaque.

### Contrat recommandé

```text
classify(element) ->
  role, role_confidence, geometry_confidence,
  occlusion_status, duplicate_candidates,
  recommended_rendering, reasons[]
```

Le renderer doit utiliser ce contrat, mais jamais faire disparaître un élément uniquement parce qu'une classification est incertaine.

---

## 6. Audit du contrat Word-native

### Fichier concerné

- `pdfexact/render/native_contract.py`

### Fonctionnement

`native_contract.py` tente de convertir des groupes de lignes en vrais paragraphes Word lorsque la continuité sémantique, la compatibilité de style et la géométrie le permettent. Les fonctions principales concernées sont notamment :

- `_assembler_textboxes_page` ;
- `_groupes_paragraphes_sans_frame` ;
- `_groupes_paragraphes_frame` ;
- `_groupes_paragraphes_frame_par_colonne` ;
- `_continuite_semantique` ;
- `_groupe_semantiquement_paragraphe` ;
- `_commence_item_liste` ;
- `_ligne_dans_frame_texte_fiable`.

### Flowchart du choix de paragraphe

```text
[lignes candidates]
       |
       v
[même frame / même colonne ?]
       |
       +-- non --> [ne pas fusionner]
       |
      oui
       v
[styles compatibles ?]
       |
       +-- non --> [séparer ou garder runs indépendants]
       |
      oui
       v
[continuité sémantique ?]
       |
       +-- non --> [nouveau paragraphe]
       |
      oui
       v
[liste / indentation détectée ?]
       |
       +-- oui --> [numPr + paragraph indentation]
       +-- non --> [paragraph Word-native]
```

### Défauts et risques

- La continuité fondée sur une ligne commençant en minuscule, la ponctuation ou une distance verticale est utile mais linguistiquement biaisée.
- Les langues sans casse, le CJK, l'arabe, les écritures verticales et les documents tout en capitales ne suivent pas ces indices.
- Une ligne de caption peut être fusionnée avec un paragraphe voisin si le frame n'est pas fiable.
- Une vraie liste peut être détectée comme du texte normal si le symbole n'est pas reconnu ; l'inverse est aussi possible.
- La fusion peut effacer des retours visuels significatifs : lignes volontairement séparées dans un titre, adresse, formule, signature ou tableau.
- La reconstruction native n'a pas encore un modèle de « frontière de bloc sûre » indépendant du rôle détecté.

### Exigence de généralisation

Le contrat devrait retourner une décision avec justification et score :

```text
KEEP_LINE_BOUNDARIES
SAFE_NATIVE_PARAGRAPH
SAFE_NATIVE_LIST
POSITIONED_PARAGRAPH
EDITABLE_FRAME
RASTER_OR_COMPOSITE_FALLBACK
AMBIGUOUS_KEEP_BOTH
```

La décision `SAFE_NATIVE_PARAGRAPH` ne doit être permise que si la fusion ne change pas le nombre de blocs lisibles, l'ordre de lecture, les styles et les limites visuelles importantes.

---

## 7. Audit de `word_native_rewriter.py`

### Fichier principal

- `pdfexact/render/word_native_rewriter.py`

### Architecture actuelle

Le rewriter réalise successivement :

1. création de numbering ;
2. normalisation des listes ;
3. regroupement des lignes en paragraphes ;
4. identification de régions visuelles ;
5. choix `flow` ou `anchored_frame` ;
6. génération de runs et de propriétés de paragraphe ;
7. génération de paragraphes positionnés, frames WPS ou fallback VML ;
8. génération des images, tableaux et liens ;
9. constitution de sections et de couches de page.

### Flowchart de décision de rendu

```text
[élément texte]
       |
       v
[texte embedded dans visuel ?]
       |
   +---+---+
   |       |
  oui     non
   |       |
[ignorer  [rôle / orientation / frame]
 sauf     |
 caption] v
       [page multi-colonnes ?]
             |
        +----+----+
        |         |
       oui       non
        |         |
  [frame/position] [plain flow ?]
                         |
                    +----+----+
                    |         |
                   oui       non
                    |         |
              [Word flow] [frame ancré]
```

### Fonctions sensibles

- `_decision` : choix final entre flux et frame ;
- `_looks_embedded_in_visual` : suppression des éléments considérés intégrés dans un visuel ;
- `_has_multiple_columns` : détection globale par écart horizontal ;
- `_regrouper_continuations_par_frame` : fusion de lignes dans un même frame ;
- `_regrouper_continuations_par_colonne` : fusion par rôle et colonne ;
- `_normaliser_listes` : association marqueur/corps et numbering ;
- `_inferred_text_region` et `_positioned_text_region` : inférence de blocs ;
- `_flow_paragraph_xml` et `_positioned_flow_paragraph_xml` : écriture des paragraphes ;
- `_frame_xml` et `_vertical_vml_frame_xml` : écriture des textboxes ;
- `rewrite_document_xml` : orchestration et ordre de rendu.

### Problèmes de logique

#### 7.1 Suppression par recouvrement

`_looks_embedded_in_visual` peut considérer un texte comme contenu dans une image dès qu'il existe un recouvrement important, une orientation horizontale et un rôle non explicitement protégé. Cette règle est dangereuse pour :

- texte blanc sur fond photographique ;
- titres posés sur une bannière ;
- texte natif au-dessus d'une image décorative ;
- texte avec clipping partiel ;
- doublons d'extraction où un élément doit d'abord être comparé à son candidat.

**Correction conceptuelle attendue :** ne jamais supprimer sur le seul recouvrement. Évaluer opacité, z-order, contraste local, provenance et similarité de contenu. En cas de doute, conserver le texte et marquer `possible_duplicate`.

#### 7.2 Détection globale des colonnes

`_has_multiple_columns` utilise une séparation x approximative. Une page avec une image à droite et un seul paragraphe à gauche peut être faussement interprétée comme une page à deux colonnes. Inversement, deux colonnes très proches peuvent être fusionnées.

**Correction attendue :** détecter des bandes textuelles homogènes, avec projection x, continuité y, densité, frame et rôle. Une image seule ne doit pas créer une colonne de texte.

#### 7.3 Fusion par frame

`_regrouper_continuations_par_frame` peut fusionner des lignes qui appartiennent au même cadre géométrique mais à deux paragraphes, un titre et son corps, ou deux items de liste. Le frame ne constitue pas une frontière sémantique.

**Correction attendue :** valider la fusion par une fonction de coût incluant : style, indentation, marqueur, ponctuation, gap vertical normalisé, longueur de ligne, changement de rôle et trajectoire de lecture.

#### 7.4 Fusion par colonne et dépendance à la casse

`_regrouper_continuations_par_colonne` dépend de la minuscule et de seuils fixes. C'est insuffisant pour les alphabets sans casse, les titres, les adresses et le CJK.

**Correction attendue :** remplacer les indices linguistiques par un module de segmentation de texte configurable par script/langue, avec une politique géométrique de secours et un état `unknown`.

#### 7.5 Orientation

Les textes horizontaux, verticaux et certaines rotations sont pris en charge, mais les courbes et obliques complexes ne sont pas un modèle général de texte sur chemin. Une rotation Word/VML peut reproduire une direction, pas une suite de glyphes sur courbe.

**Correction attendue :** représenter l'orientation par angle, axe de lecture, quadrilatère et chemin éventuel. Si Word ne peut pas le représenter nativement, conserver les glyphes éditables par segments positionnés ou activer un fallback local, en le signalant.

#### 7.6 Ordre des couches

`rewrite_document_xml` construit plusieurs groupes : fonds, liens, flux, flux positionné, frames et tables. Cet ordre est une politique de rendu, pas nécessairement l'ordre de peinture PDF. Une couche tardive peut recouvrir du texte ; une couche de fond peut masquer une légende ; une image peut être envoyée derrière alors qu'elle doit passer devant.

**Correction attendue :** chaque élément doit porter un `paint_order` ou un z-order calculé. Le renderer doit produire un ordre total stable, avec tests de recouvrement et de visibilité par paire.

#### 7.7 Texte vertical

Le correctif VML récent rend visible le texte vertical dans le cas observé. Toutefois, le fallback reste dépendant du support du lecteur et de détails OOXML/VML : type de shape, `w10:wrap`, rotation, géométrie transposée, définition unique du shapetype et hauteur de ligne. Ce n'est pas une preuve de compatibilité universelle Word/LibreOffice/WPS.

---

## 8. Audit de `docx_writer.py` et `drawing.py`

### Fichiers concernés

- `pdfexact/render/docx_writer.py`
- `pdfexact/render/drawing.py`

### Deux chemins de reconstruction

`docx_writer.py` contient le moteur historique de reconstruction, avec paragraphes flux, grilles, tables de positionnement, ancres et règles de fit. `word_native_rewriter.py` constitue un moteur plus récent orienté Word-native. Le package choisit l'un ou l'autre selon le mode.

### Flowchart du writer historique

```text
[Page IR]
   |
   v
[page absolue ou flux ?]
   |
   +--> [flux]
   |       |
   |       +--> colonnes
   |       +--> reflow naturel
   |       +--> ajustement largeur
   |       +--> échelle verticale
   |
   +--> [absolue / grille]
           |
           +--> table de positionnement
           +--> ancres d'images
           +--> cellules / frames
           +--> texte par ligne ou par bloc
```

### Défauts majeurs

1. **Ajustement à la largeur.** `_ajuster_spans_a_largeur` peut réduire la taille de police jusqu'à une borne minimale ou modifier l'espacement des caractères. C'est une stratégie de fit, pas une conservation typographique.

2. **Clamps de line spacing.** `_paragraphe_flux_xml` contraint l'interligne dans une plage fixe lorsqu'il n'est pas en mode exact. Les documents avec très petits corps, grandes capitales, notes, exposants ou polices métriquement différentes peuvent dériver.

3. **Reflow heuristique.** `_paragraphe_ajuste_largeur` convertit les limites de lignes en espaces, retours ou tabulations selon des indices locaux. Cela peut créer des espaces parasites, supprimer une séparation voulue ou changer les retraits.

4. **Échelle verticale globale.** `_echelle_verticale_flux` et `_page_flux_xml` peuvent réduire ou étirer une page entière pour la faire tenir. Le résultat peut cacher une erreur de mesure au lieu de la corriger.

5. **Grilles utilisées comme substitut sémantique.** Les tables de positionnement reproduisent bien certains pixels, mais ne correspondent pas à un flux Word normal et créent des cellules, lignes et contraintes artificielles.

6. **Fonctions de dessin.** `drawing.py` crée des textboxes WPS et des ancres pour les éléments orientés ou positionnés. Le support des formes varie entre lecteurs et la position dépend du repère, de l'ancre, du wrap et du comportement de pagination.

### Conclusion sur les deux writers

Tant que les deux moteurs existent, les corrections faites dans l'un peuvent être contournées par l'autre. Il faut un contrat commun de décision et un seul backend de rendu principal, ou une couche commune de géométrie et de z-order qui rende leurs différences explicites.

---

## 9. Audit OOXML et empaquetage

### Fichiers concernés

- `pdfexact/render/package.py`
- `pdfexact/render/native_contract.py`
- `pdfexact/render/word_native_rewriter.py`
- `pdfexact/render/drawing.py`

### Points solides

- génération séparée du document, styles, settings, numbering, fontTable, relations et médias ;
- inclusion des images et des polices disponibles ;
- utilisation de paragraphes/runs Word natifs pour les blocs sûrs ;
- textboxes et ancres pour les éléments qui ne peuvent pas être en flux.

### Risques

- validation actuelle surtout structurelle ZIP/XML, pas validation de comportement Word et LibreOffice ;
- OOXML, WPS et VML peuvent être acceptés par un lecteur et ignorés ou interprétés différemment par un autre ;
- les positions absolues dépendent des sections, marges, repères d'ancre et unités ;
- l'embedding des polices ne garantit pas que le lecteur les utilise ni que les métriques soient identiques ;
- les relations et content types sont générés manuellement et doivent être testés sur des documents multi-pages, multi-images et multi-sections ;
- une structure XML valide peut produire un document visuellement faux.

### Contrat de compatibilité recommandé

Chaque feature de rendu devrait déclarer :

```text
feature: vertical_text_vml
readers: [Word_desktop, LibreOffice, WPS]
editable: partial
visual_risk: medium
fallback: raster_local_or_segmented_text
verification: required
```

---

## 10. Audit de `final_audit.py`

### Fichier concerné

- `pdfexact/final_audit.py`

### Flowchart de l'audit actuel

```text
[DOCX produit]
       |
       v
[export LibreOffice -> PDF]
       |
       +--> [couverture visuelle]
       +--> [texte visible / mots]
       +--> [tables]
       +--> [similarité de page]
       +--> [similarité de zones]
       |
       v
[seuils]
       |
       +--> [réparation IR / raster / réécriture]
       +--> [rapport final]
```

### Ce que l'audit vérifie correctement

- existence de texte visible dans les zones attendues ;
- présence de mots ou caractères ;
- couverture et similarité de page ;
- réexport du DOCX pour observer le rendu réel ;
- certaines tables et zones finales ;
- rapports JSON et diagnostics.

### Ce que l'audit ne garantit pas encore

1. **Rappel et précision des tokens.** Comparer un nombre total de mots proche de la source ne détecte pas une substitution, une répétition ou une permutation.

2. **Orientation et baseline.** Un texte horizontal au mauvais endroit peut compter comme visible. Un texte vertical converti horizontalement peut être compté comme présent.

3. **Typographie.** La police, taille, graisse, italique, interligne et crénage ne sont pas contrôlés de manière complète par zone.

4. **Z-order.** Un texte présent dans le XML mais recouvert par une image peut être compté comme présent alors qu'il est invisible.

5. **Superposition et débordement.** Les scores globaux ne localisent pas toujours la cause et une grande photo peut dominer la métrique.

6. **Editabilité.** L'audit visuel ne distingue pas un paragraphe natif, un texte dans une frame, une image raster et un texte peint dans une capture.

7. **Seuils permissifs.** Les voies liées au rewriter natif et à la couverture peuvent réduire la sévérité au lieu d'exiger une preuve complète.

### Audit recommandé par élément

```text
for source_element in source_page:
    candidates = output_elements_near(source_element.bbox)
    assert candidates != [] or source_element.reason == explicit_unrenderable
    compare token recall / precision / order
    compare polygon IoU and baseline
    compare orientation and font metrics
    compare visible pixels after z-order
    compare editability class
    emit pass / warning / fail with provenance
```

Une grande image ne doit jamais compenser l'absence d'un petit texte critique.

---

## 11. Brainstorming contradictoire : scénarios qui cassent la logique

### 11.1 Scénario A : texte sur bannière photographique

**Hypothèse :** titre natif blanc placé sur image opaque.  
**Risque :** `_looks_embedded_in_visual` le supprime ; l'image conservée ne contient pas ce titre dans les pixels source si le texte était une couche séparée.  
**Test de contradiction :** recouvrement élevé ne prouve pas l'intégration.  
**Décision attendue :** garder le texte au-dessus de l'image, même si la zone est protégée.

### 11.2 Scénario B : image contenant déjà du texte + OCR de cette image

**Hypothèse :** carte raster avec noms de villes ; OCR trouve les noms.  
**Risque :** les noms sont réécrits par-dessus l'image, donc doublés et décalés.  
**Décision attendue :** identifier la provenance image-OCR, classer comme texte intégré, conserver l'image comme source visuelle et ne pas créer un doublon éditable sauf option explicite d'accessibilité.

### 11.3 Scénario C : deux colonnes avec une légende étroite

**Hypothèse :** deux colonnes principales et une petite légende latérale.  
**Risque :** les seuils x et la continuité y placent la légende dans une colonne ou fusionnent deux blocs.  
**Décision attendue :** utiliser les frames, rôles, alignements et largeur de bloc, pas uniquement x0.

### 11.4 Scénario D : liste sans symbole standard

**Hypothèse :** tiret long, carré, Unicode spécial ou puce dessinée en forme.  
**Risque :** marqueur non détecté, texte fusionné comme paragraphe ; ou marqueur traité comme contenu.  
**Décision attendue :** modèle générique de marqueur : glyphes, forme vectorielle, indentation, répétition verticale, alignement du corps.

### 11.5 Scénario E : langue sans casse

**Hypothèse :** CJK ou texte tout en capitales.  
**Risque :** `_regrouper_continuations_par_colonne` et les règles de minuscule échouent.  
**Décision attendue :** segmentation indépendante de la casse, basée sur script, ponctuation, interligne, alignement et frames.

### 11.6 Scénario F : texte vertical réel et texte tourné à 90 degrés

**Hypothèse :** les deux ont une bbox étroite et direction proche.  
**Risque :** même orientation de sortie alors que le sens de lecture ou l'ancrage diffère.  
**Décision attendue :** conserver la matrice/quadrilatère, distinguer rotation de ligne, orientation de glyphes et écriture verticale.

### 11.7 Scénario G : texte sur courbe

**Hypothèse :** texte sur un arc ou un chemin vectoriel.  
**Risque :** textbox tournée globalement, donc ligne droite ; mismatch visuel évident.  
**Décision attendue :** texte segmenté par glyphes/runs positionnés si l'édition est prioritaire, ou fallback local raster si la courbe est trop complexe.

### 11.8 Scénario H : transparence et clipping

**Hypothèse :** texte derrière un masque semi-transparent.  
**Risque :** l'image ou la forme est mise derrière/au-dessus au mauvais ordre.  
**Décision attendue :** conserver l'ordre de peinture et la composition locale ; DOCX peut nécessiter un composite raster de la zone, avec texte source séparé seulement s'il ne détruit pas l'apparence.

### 11.9 Scénario I : police sans ToUnicode

**Hypothèse :** glyphes visuellement corrects mais extraction Unicode vide ou erronée.  
**Risque :** impossible de reconstruire le texte exact ; OCR peut produire des caractères proches mais faux.  
**Décision attendue :** rapporter l'incertitude, ne pas promettre une conformité textuelle, conserver une représentation visuelle et une couche OCR explicitement marquée.

### 11.10 Scénario J : moteur de lecture différent

**Hypothèse :** Word et LibreOffice interprètent différemment une frame VML ou un wrap.  
**Risque :** le fichier validé avec un moteur dérive dans l'autre.  
**Décision attendue :** matrice de tests par lecteur et fallback selon le profil de compatibilité demandé.

---

## 12. Benchmark conceptuel par classes de PDF

| Classe de PDF | Détection | Reconstruction éditable | Fidélité visuelle | Risque dominant |
|---|---:|---:|---:|---|
| Rapport texte natif mono-colonne | Forte | Forte | Forte | métriques de police |
| Brochure à deux colonnes | Forte | Bonne | Bonne | regroupement / z-order |
| Brochure images + légendes | Bonne | Bonne | Bonne | texte sur image / crédits |
| Tableau régulier | Bonne | Bonne | Bonne | inférence de cellules |
| Tableau irrégulier / formulaire | Moyenne | Moyenne | Moyenne | lignes dessinées, cases, champs |
| Scan propre | Moyenne | Moyenne | Moyenne | OCR et ordre de lecture |
| Scan incliné / bruité | Faible à moyenne | Faible à moyenne | Moyenne | orientation et reconnaissance |
| Carte avec labels vectoriels | Moyenne | Faible à moyenne | Bonne | labels intégrés et z-order |
| Diagramme avec connecteurs | Moyenne | Faible | Moyenne | groupes, flèches et ancrages |
| Texte sur chemin | Faible | Faible | Faible | modèle DOCX insuffisant |
| PDF avec masques/transparence | Moyenne | Faible | Moyenne avec raster | ordre de peinture |
| Type3 / encodage incomplet | Faible | Faible | Bonne avec image | Unicode non récupérable |
| Arabe / RTL complexe | Moyenne | Moyenne à faible | Moyenne | shaping, ordre logique |
| CJK / script sans casse | Moyenne | Moyenne | Moyenne | segmentation heuristique |
| Affiche avec texte décoratif | Moyenne | Faible à moyenne | Bonne avec frames | rotation, courbes, outlines |

Ce benchmark montre pourquoi « quel que soit le PDF » doit être remplacé par une promesse graduée par classe, confiance et fallback.

---

## 13. Matrice des constats et actions correctives

| Priorité | Cause | Fichiers en cause | Effet | Action de conception |
|---|---|---|---|---|
| P0 | Absence d'invariant de conservation | `extract/document.py`, `understanding.py`, `native_contract.py`, `word_native_rewriter.py` | éléments silencieusement perdus | registre de provenance et état terminal obligatoire |
| P0 | Deux writers concurrents | `docx_writer.py`, `word_native_rewriter.py`, `package.py` | comportements divergents | contrat commun et backend principal unique |
| P0 | z-order approximé par couches | `word_native_rewriter.py`, `drawing.py`, `docx_writer.py` | texte derrière images / superposition | scene graph avec paint order et test par paire |
| P0 | audit dominé par métriques globales | `final_audit.py` | erreurs locales masquées | audit par élément, zone et couche |
| P1 | fusion sensible à la langue | `native_contract.py`, `document.py`, `word_native_rewriter.py` | paragraphes/listes faux | segmentation script-aware + score de continuité |
| P1 | recouvrement = texte intégré | `word_native_rewriter.py`, `understanding.py` | texte natif supprimé | analyse opacité/provenance/duplication |
| P1 | fit par réduction de police | `docx_writer.py` | taille et métriques fausses | préférer largeur exacte, frame ou warning |
| P1 | bbox rectangle pour orientation complexe | `orientation.py`, `word_native_rewriter.py` | rotation/courbe fausse | quad/polygon/path et fallback explicite |
| P1 | tables de positionnement | `docx_writer.py`, `drawing.py` | faux flux Word | limiter aux composants réellement tabulaires |
| P1 | VML/WPS dépendant du lecteur | `word_native_rewriter.py`, `drawing.py` | vertical absent selon lecteur | profils de compatibilité + fallback local |
| P2 | packaging sans validation comportementale | `package.py` | XML valide mais rendu faux | schema + LO + Word-compatible smoke tests |
| P2 | absence de budget d'erreur par élément | `final_audit.py` | échec global peu explicable | seuils par type, rôle et importance |

---

## 14. Algorithme cible pour une reconstruction réellement généralisable

### 14.1 Étape 1 : scène de page canonique

Construire une scène de page indépendante du renderer :

```text
PageScene {
  page_size
  elements[] {
    id, source_ids[], kind, role
    bbox, quad, polygon, path
    z_order, clip, opacity
    text_spans[], language, script
    style_metrics, orientation
    confidence, duplicate_candidates[]
    render_candidates[]
  }
}
```

### 14.2 Étape 2 : déduplication non destructive

```text
for each candidate pair:
  if same provenance and high text/geometry similarity:
      mark duplicate, keep canonical source
  elif image OCR overlaps native text:
      retain both until z-order/source analysis
  else:
      keep both
```

### 14.3 Étape 3 : segmentation sémantique

La segmentation doit combiner :

- rôle et confiance ;
- script et langue ;
- lignes de base et interligne ;
- indentation et marqueur ;
- continuité des styles ;
- alignement et colonnes ;
- frontières de frames ;
- ponctuation et analyse linguistique quand disponible ;
- pénalité forte pour fusionner deux rôles différents.

### 14.4 Étape 4 : sélection de représentation

```text
if plain horizontal prose and no conflicting overlap:
    native paragraph + runs
elif recognized list:
    native paragraph + numbering
elif semantic table with stable cells:
    native table
elif rotated/position-sensitive text:
    editable anchored frame or segmented positioned runs
elif visual composite cannot be represented:
    local raster fallback + source text metadata
else:
    ambiguous keep-both representation + diagnostic
```

### 14.5 Étape 5 : résolution des contraintes

Résoudre les contraintes dans cet ordre :

1. page, marges et sections ;
2. ordre de peinture et visibilité ;
3. présence de tous les éléments ;
4. bboxes et rotation ;
5. métriques de police ;
6. reflow et éditabilité ;
7. esthétisme secondaire.

La taille de police ne doit pas être modifiée pour masquer un conflit sans émettre un diagnostic.

### 14.6 Étape 6 : vérification en boucle

```text
render DOCX -> PDF
for each source element:
    locate output candidate
    compare geometry, text, orientation, metrics, visibility
if local failures and repair budget remains:
    adjust only affected element/region
    rerender
else:
    finalize with explicit warnings
```

---

## 15. Ce que l'implémentation actuelle garantit réellement

### Garanties raisonnables

- génération d'un DOCX ouvrable pour les chemins testés ;
- conservation des paragraphes/runs pour les zones sûres ;
- images et éléments visuels positionnés dans les cas standard ;
- listes courantes dans les documents déjà observés ;
- texte vertical simple avec le fallback corrigé dans le lecteur testé ;
- diagnostics de débordement et d'éléments manquants dans certains chemins ;
- audit final capable de détecter plusieurs classes d'erreurs visibles.

### Garanties non établies

- conformité à tout PDF ;
- conservation exacte de toutes les polices et métriques ;
- reconstitution sûre de l'ordre de lecture sans ambiguïté ;
- texte courbe ou complexe entièrement éditable ;
- compatibilité identique Word / LibreOffice / WPS ;
- absence de doublon dans tous les mélanges natif/OCR/image ;
- correction automatique de chaque superposition ;
- audit final exhaustif du z-order, de l'orientation et de l'éditabilité.

### Formulation de promesse recommandée

> Le convertisseur reconstruit un DOCX visuellement fidèle et éditable pour les éléments dont la structure est identifiable. Pour les éléments incompatibles avec le modèle DOCX ou ambigus, il choisit un fallback local et produit un diagnostic explicite au lieu de promettre une conformité universelle.

---

## 16. Plan de sécurisation général

### Phase A - Observabilité et conservation

1. Ajouter un registre page/élément de bout en bout.
2. Interdire les suppressions silencieuses ; chaque suppression doit avoir une raison et une source.
3. Sauvegarder les candidats et décisions dans le rapport d'audit.
4. Conserver quad/polygon/orientation et non seulement bbox.

### Phase B - Unification de la logique

1. Définir un `RenderDecision` partagé par `native_contract.py`, `docx_writer.py` et `word_native_rewriter.py`.
2. Déplacer les seuils dans une configuration par profil et par classe de document.
3. Définir un seul calcul de z-order et de régions protégées.
4. Réduire les heuristiques dupliquées de regroupement.

### Phase C - Rendu et compatibilité

1. Prioriser paragraphes/runs natifs quand la sécurité est démontrée.
2. Réserver les tables de positionnement aux objets réellement tabulaires ou aux cas explicitement non reflowables.
3. Définir des profils Word, LibreOffice et WPS pour WPS/VML/ancres.
4. Introduire un fallback local contrôlé, jamais une rasterisation globale silencieuse.

### Phase D - Audit réel

1. Comparer les tokens par élément : rappel, précision, ordre.
2. Comparer les quadrilatères, baselines, angles et dimensions.
3. Détecter la visibilité réelle après z-order.
4. Vérifier font family, taille, style, interligne et spacing.
5. Mesurer l'éditabilité : run, paragraphe, frame, table, image, raster.
6. Produire un score par élément et un verdict par page.

### Phase E - Benchmark de non-régression

Créer un corpus couvrant au minimum :

- texte natif mono-colonne et multi-colonnes ;
- listes avec puces, tirets, symboles dessinés ;
- images avec et sans texte intégré ;
- texte horizontal, vertical, oblique et courbé ;
- tableaux réguliers et formulaires ;
- scans avec rotations ;
- langues avec et sans casse ;
- polices normales, Type3 et polices absentes ;
- transparence, clipping et groupes vectoriels ;
- documents multi-pages avec sections et sauts.

---

## 17. Conclusion finale de l'audit

Le travail réalisé a franchi un cap important : le pipeline produit maintenant une reconstruction convaincante pour la famille de brochures observée, avec une meilleure séparation entre texte natif, frames, images, listes et éléments verticaux.

Mais l'audit de conception montre que la conclusion « plus de mauvaises reconstructions quel que soit le PDF » serait trop forte. Les fonctions actuelles sont efficaces dans leur domaine, mais elles reposent encore sur :

- des seuils géométriques ;
- des regroupements sensibles à la langue ;
- des décisions de suppression par recouvrement ;
- deux moteurs de rendu ;
- une approximation de l'ordre de peinture ;
- un audit final dominé par des métriques globales ;
- des fallback WPS/VML dont le support varie.

La prochaine étape structurante n'est pas d'ajouter encore un seuil isolé. C'est d'installer un **scene graph canonique, traçable et non destructif**, puis de faire dépendre le regroupement, le choix Word-native, le z-order et l'audit du même contrat. Cette évolution préservera les acquis actuels tout en rendant les erreurs localisables, les fallback explicites et la promesse de généralisation mesurable.

**Verdict final :** architecture prometteuse et déjà performante sur les cas courants, mais conformité universelle non garantie tant que les points P0 ne sont pas traités.
