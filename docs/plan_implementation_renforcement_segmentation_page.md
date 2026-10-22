## Niveau 0 — Invariants intouchables

  Fonction nouvelle :

  - valider_partition_page(page)
    Vérifie avant écriture :
      - aucune image ne couvre seule la page ;
      - chaque zone est classée texte, formule, image, tableau, logo, schéma ou
        fond ;

      - aucune zone OCR n’est perdue ;
      - aucun texte protégé n’est converti en faux texte.

  Cette fonction ne corrigera pas silencieusement : elle signalera précisément
  la page et la zone fautive.

  ## Niveau 1 — Propositions de zones

  ### detecter_layout_ia

  Conserver PaddleX comme détection initiale.

  Ajouter :

  - détection des zones trop grandes ;
  - découpage automatique des scanned-page, figure et image ;
  - conservation de la confiance IA ;
  - nouvelle analyse des zones à faible confiance.

  L’IA ne décidera plus seule qu’une page entière est une image finale.

  ### _role

  Normaliser les rôles :

  - text
  - formula
  - table
  - caption
  - logo
  - figure
  - background
  - unknown

  unknown sera traité comme une zone à analyser, jamais comme une page bitmap.

  ### _normaliser_detections

  Ajouter :

  - suppression des doublons ;
  - fusion des zones presque identiques ;
  - découpage des zones imbriquées ;
  - correction des coordonnées ;
  - conservation des zones partiellement chevauchantes si elles représentent des
    composants différents.

  ## Niveau 2 — Segmentation fine

  Nouvelle logique dans layout/segmentation.py :

  ### proposer_zones_segmentation

  Entrées :

  - image de page ;
  - zones IA ;
  - objets PDF ;
  - lignes OCR ;
  - formes vectorielles.

  Sortie :

  - propositions de composants indépendants.

  Sources utilisées ensemble :

  1. blocs PDF ;
  2. zones PaddleX ;
  3. lignes RapidOCR ;
  4. contours OpenCV ;
  5. espaces blancs ;
  6. lignes horizontales/verticales ;
  7. changements de couleur ou de texture.

  ### segmenter_zone_recursive

  Pour chaque zone trop grande :

  1. chercher des séparations naturelles ;
  2. découper selon les lignes OCR ;
  3. découper selon les colonnes ;
  4. découper selon les contours ;
  5. découper selon les espaces blancs ;
  6. si aucune séparation fiable n’existe, utiliser des tuiles géométriques.

  La tuile est donc le dernier recours, pas la première méthode.

  ### valider_partition

  Vérifier :

  - couverture complète ;
  - absence de trous ;
  - absence de chevauchements incohérents ;
  - aucune zone finale de taille page ;
  - coordonnées compatibles avec la page.

  ## Niveau 3 — Compréhension sémantique

  ### comprendre_page

  Ne plus produire uniquement « page native » ou « page image ».

  Produire une liste d’éléments :

  texte traduisible
  formule
  symbole
  tableau
  légende
  logo
  schéma
  image
  fond
  inconnu

  Chaque élément contiendra :

  - bbox ;
  - type ;
  - confiance ;
  - source de détection ;
  - stratégie de sortie.

  ### _decision_zone_ia

  Décision combinée :

  - rôle IA ;
  - présence de lignes OCR ;
  - densité de caractères ;
  - ratio symboles/lettres ;
  - structure géométrique ;
  - présence de traits de tableau ;
  - position dans une colonne ;
  - contraste et couleur.

  Règle importante : une zone contenant du texte OCR ne pourra pas être classée
  directement comme image protégée sans justification.

  ### _zones_visuelles_protegees

  Retourner uniquement :

  - formules ;
  - symboles ;
  - logos ;
  - schémas ;
  - tableaux non reconstructibles.

  Les zones avec texte lisible resteront OCRisables.

  ### _zones_visuelles_bloquantes

  Ne plus bloquer l’OCR parce qu’une image est grande.

  Une image grande devient :

  fond graphique + zones de texte à inpaint + zones protégées

  ## Niveau 4 — Planification

  ### planifier_regions

  Construire un plan exhaustif :

  - toutes les zones de texte ;
  - toutes les zones protégées ;
  - toutes les images ;
  - tous les fonds ;
  - aucune zone oubliée.

  Priorité :

  1. zones PDF natives fiables ;
  2. zones OCR ;
  3. zones IA ;
  4. segmentation géométrique de secours.

  ### zones_protegees_du_plan

  Ne conserver que les éléments réellement non traduisibles.

  Une formule détectée dans un paragraphe ne doit pas supprimer tout le
  paragraphe : seule sa sous-zone est protégée.

  ### zones_ocr_du_plan

  Inclure :

  - texte natif ;
  - texte scanné ;
  - texte dans une image ;
  - titres ;
  - légendes ;
  - tableaux textuels reconstructibles.

  ### filtrer_elements_selon_plan

  Filtrer au niveau ligne/span, jamais au niveau page ou bloc complet.

  ## Niveau 5 — Images

  ### extraire_images_rasterisees

  Déjà renforcée avec :

  - segmentation en tuiles ;
  - segmentation dans tous les modes ;
  - détection par couverture et dimensions.

  À renforcer :

  - associer chaque tuile à son composant ;
  - empêcher qu’une tuile masque un texte ;
  - conserver les zones graphiques non textuelles.

  ### extraire_images_inline_rasterisees

  Déjà renforcée avec la couverture cumulée.

  À renforcer :

  - reconnaître qu’une image inline contient plusieurs composants ;
  - supprimer les doublons avec les images XRef ;
  - ne jamais recréer une page entière depuis un bloc inline.

  ### bboxes_segmentees

  Conserver comme filet de sécurité.

  La grille ne doit être utilisée que lorsque :

  - aucune segmentation sémantique fiable n’est disponible ;
  - ou qu’une zone reste ambiguë.

  ## Niveau 6 — OCR

  ### extraire_rapidocr

  Pour une page scannée :

  1. OCR global pour ne perdre aucun texte ;
  2. OCR régional pour les zones ambiguës ;
  3. fusion des résultats ;
  4. suppression des doublons ;
  5. conservation des coordonnées originales.

  ### _choisir_lignes_word_native

  Ne plus éliminer les titres courts ou les lignes isolées uniquement parce
  qu’il y en a peu.

  Une ligne est rejetée uniquement si elle est :

  - clairement formule ;
  - clairement symbole ;
  - clairement faux positif ;
  - située dans une zone protégée confirmée.

  ### _ligne_formule_a_rasteriser

  Utiliser plusieurs indices :

  - proportion de symboles ;
  - présence de fractions ;
  - exposants/indices ;
  - alignement mathématique ;
  - caractères OCR incohérents ;
  - police symbolique ;
  - faible densité de mots naturels.

  ### _zones_glyphes_symboles_non_reconnus

  Protéger seulement le glyphe ou le symbole concerné, pas toute sa ligne ni
  toute la page.

  ### _grouper_lignes_word_native

  Regrouper selon :

  - colonne ;
  - distance verticale ;
  - alignement gauche ;
  - largeur ;
  - taille et style ;
  - continuité linguistique ;
  - séparation par titre, formule ou légende.

  ## Niveau 7 — Inpainting

  ### rasteriser_region_sans_texte

  Appliquer le nettoyage à chaque composant segmenté.

  ### nettoyer_images_fond_texte_positionne

  Déjà corrigée pour les lignes traversant deux tuiles.

  À renforcer :

  - marge adaptative selon taille de police ;
  - nettoyage par span lorsque la ligne contient plusieurs éléments ;
  - vérification que le texte Word ne se superpose plus au texte bitmap.

  ### _zones_texte_natif

  Retourner les bboxes de chaque span PDF, pas uniquement celles des lignes
  globales.

  ### _inpaint_regions

  Utiliser :

  - inpainting OpenCV ;
  - remplissage local pour fonds simples ;
  - texture locale pour fonds complexes ;
  - interpolation adaptée aux lignes fines.

  ## Niveau 8 — Word

  ### _page_absolue_xml

  Avant génération XML :

  - refuser toute image couvrant une page ;
  - refuser tout texte bitmap non protégé ;
  - vérifier l’ordre fond → image → formule → texte.

  ### zone_texte_xml

  Créer une zone Word éditable avec :

  - position ;
  - largeur ;
  - hauteur ;
  - police ;
  - taille ;
  - couleur ;
  - alignement ;
  - rotation si nécessaire.

  ### zone_paragraphe_xml

  Regrouper les lignes réellement appartenantes au même paragraphe, sans
  fusionner deux colonnes ou deux blocs séparés.

  ### image_xml

  Écrire séparément :

  - chaque tuile de fond ;
  - chaque formule ;
  - chaque symbole ;
  - chaque schéma ;
  - chaque logo.

  ## Niveau 9 — Contrat final

  ### inspecter_docx_word_native

  Ajouter les contrôles :

  - images couvrant une page ;
  - texte uniquement dans les images ;
  - textboxes non éditables ;
  - ancres incohérentes ;
  - chevauchements texte/image.

  ### corriger_document_word_native

  Ne convertir que les textboxes de texte en paragraphes Word.

  Ne jamais convertir une formule ou une image protégée en texte approximatif.

  ## Niveau 10 — Audit

  ### certifier_et_reparer

  L’audit devra échouer si :

  - une page bitmap unique existe ;
  - du texte traduisible manque ;
  - une zone est non classée ;
  - une image masque du texte Word ;
  - les zones protégées ne sont pas séparées.

  ### _auditer_texte

  Comparer :

  - mots source ;
  - mots OCR ;
  - mots Word éditables ;
  - texte restant dans les images.

  ### _auditer_similarite_zones_finales

  Comparer séparément :

  - fonds ;
  - paragraphes ;
  - formules ;
  - schémas ;
  - tableaux ;
  - légendes.

  ## Modèles CPU

  Je ne ferai pas dépendre toute la solution d’un modèle YOLO ou RCNN.

  Ordre prévu :

  1. objets PDF natifs ;
  2. règles géométriques ;
  3. OpenCV pour contours, lignes et espaces ;
  4. modèle de layout existant ;
  5. RapidOCR ;
  6. modèle complémentaire uniquement pour les zones ambiguës.

  YOLO/RCNN pourront fournir des propositions de régions, mais ils ne résolvent
  pas seuls le texte, l’ordre de lecture, les paragraphes et les formules.

  Le principe central restera :

  les modèles proposent, les règles fusionnent et vérifient, l’audit bloque
  toute sortie incorrecte.

