# Référentiel d'identification

Rendu depuis `referentiel.json` (source unique) par `scripts/rendre_referentiel.py`. Ne pas éditer à la main.

**Finalité.** Contrat de l'identification : pour chaque bbox issue de la segmentation, son type (liste fermée), les propriétés de bbox à remplir, et les attributs de ce type. Chaque notion est définie une seule fois.

- Positions : [x, y, largeur, hauteur] en points, origine en haut à gauche, x vers la droite, y vers le bas.
- Champs : Chaque champ est toujours présent ; il vaut null quand la valeur n'est pas établie (jamais devinée).
- Portée : Les propriétés de bbox valent pour toute bbox ; un attribut vaut pour les familles de sa portée. Les lignes, runs et glyphes sont des bbox de granularité plus fine, pas des types. Le texte présent dans une image est porté par des bbox enfants d'origine ocr.
- Priorité : Une visualisation (graphique, diagramme, carte) l'emporte sur image ou vectoriel ; image_generique quand seule la famille image est établie ; inconnu quand même la famille ne l'est pas ; page_numerisee si l'image porte le contenu de la page, arriere_plan sinon ; un objet de la couche d'annotation prend un type annotation, un objet imprimé un type image ; signature pour une marque de signature, ecriture_manuscrite pour tout autre texte manuscrit ; lien est la zone cliquable, url le texte écrit : les deux coexistent.

**95 types, 32 propriétés de bbox, 62 attributs, 3 attributs de document, 3 attributs de page.**

## 1. Types

### Page et sa périphérie (en-tête, pied, numéro, fond, filigrane) (`page`)

| id | type |
|---|---|
| `page` | Page |
| `en_tete` | En-tête de page |
| `pied_de_page` | Pied de page |
| `numero_page` | Numéro de page affiché |
| `arriere_plan` | Arrière-plan de page sans contenu (couleur, image, texture) |
| `filigrane` | Filigrane |
| `bordure_page` | Bordure de page |

### Zones de mise en page (zone de contenu, colonne, cadre, encadré, figure) (`zone`)

| id | type |
|---|---|
| `zone_contenu` | Zone de contenu principal |
| `colonne` | Colonne |
| `cadre_texte` | Cadre ou zone de texte positionnée |
| `encadre` | Encadré, barre latérale |
| `figure` | Figure (illustration et sa légende) |

### Blocs de texte (`texte`)

| id | type |
|---|---|
| `titre_document` | Titre du document |
| `sous_titre` | Sous-titre |
| `intertitre` | Intertitre |
| `paragraphe` | Paragraphe |
| `citation` | Citation en bloc |
| `legende` | Légende de figure, de tableau ou de graphique |
| `resume` | Résumé |
| `note_bas_page` | Note de bas de page |
| `note_fin` | Note de fin |
| `note_marginale` | Note en marge |
| `table_des_matieres` | Table des matières, liste des figures ou des tableaux |
| `entree_sommaire` | Entrée de table des matières |
| `index` | Index |
| `entree_index` | Entrée d'index |
| `glossaire` | Glossaire |
| `entree_glossaire` | Entrée de glossaire |
| `bibliographie` | Bibliographie |
| `entree_bibliographique` | Entrée bibliographique |
| `bloc_code` | Bloc de code |
| `lettrine` | Lettrine |
| `etiquette` | Étiquette, libellé court |
| `metadonnees_visibles` | Métadonnées affichées (auteur, date, référence) |

### Éléments en ligne dans un texte (appel de note, champ calculé, ruby) (`en_ligne`)

| id | type |
|---|---|
| `appel_de_note` | Appel de note |
| `champ_calcule` | Champ calculé (date, numéro de page, renvoi automatique) |
| `ruby` | Annotation interlinéaire CJK (ruby, warichu) |

### Expressions à protéger dans un texte (`expression`)

| id | type |
|---|---|
| `code_en_ligne` | Code en ligne |
| `url` | URL écrite dans le texte |
| `email` | Adresse e-mail |
| `identifiant` | Identifiant (technique, DOI, ISBN, référence) |
| `grandeur` | Grandeur avec unité, pourcentage, valeur scientifique |
| `date` | Date |
| `acronyme` | Acronyme, abréviation |
| `personne` | Nom de personne |
| `organisation` | Organisation (institution, entreprise, agence) |
| `lieu` | Lieu (pays, ville, région, adresse géographique) |
| `evenement` | Événement nommé |
| `produit` | Produit, logiciel, œuvre nommés |
| `montant` | Montant monétaire |
| `telephone` | Numéro de téléphone |
| `adresse_postale` | Adresse postale |

### Listes (`liste`)

| id | type |
|---|---|
| `liste` | Liste |
| `element_liste` | Élément de liste |
| `marqueur_liste` | Puce ou numéro de liste |

### Tableaux (`tableau`)

| id | type |
|---|---|
| `tableau` | Tableau |
| `ligne_tableau` | Ligne de tableau |
| `cellule` | Cellule |

### Formules (`formule`)

| id | type |
|---|---|
| `formule_bloc` | Formule en bloc (mathématique, chimique, physique, matrice) |
| `formule_en_ligne` | Formule en ligne |
| `numero_formule` | Numéro d'équation |

### Images matricielles (`image`)

| id | type |
|---|---|
| `photo` | Photographie |
| `illustration` | Illustration matricielle qui n'est ni graphique, ni diagramme, ni carte |
| `logo` | Logo |
| `icone` | Icône, pictogramme |
| `page_numerisee` | Image pleine page portant le contenu de la page (scan) |
| `signature` | Signature manuscrite |
| `ecriture_manuscrite` | Écriture manuscrite |
| `sceau` | Sceau ou tampon imprimé |
| `qr_code` | QR code |
| `code_barres` | Code-barres |
| `image_generique` | Image dont la nature n'est pas établie |

### Graphismes vectoriels (`vectoriel`)

| id | type |
|---|---|
| `dessin_vectoriel` | Dessin vectoriel qui n'est ni graphique, ni diagramme, ni carte |
| `forme` | Forme géométrique (rectangle, ellipse, flèche…) |
| `connecteur` | Trait ou connecteur entre éléments |

### Graphiques de données, diagrammes, cartes (quel que soit leur encodage) (`visualisation`)

| id | type |
|---|---|
| `graphique` | Graphique de données |
| `diagramme` | Diagramme, schéma, organigramme |
| `carte` | Carte géographique |

### Décorations (`decoration`)

| id | type |
|---|---|
| `separateur` | Filet, séparateur |
| `bandeau` | Fond coloré, bandeau |
| `ornement` | Ornement |

### Annotations et révisions (couche distincte du contenu imprimé) (`annotation`)

| id | type |
|---|---|
| `commentaire` | Commentaire (note attachée, souvent repliée) |
| `annotation_texte` | Annotation de texte affichée sur la page |
| `annotation_balisage` | Surlignage, soulignement, barré annotés |
| `annotation_graphique` | Annotation dessinée ou tampon annoté |
| `caviardage` | Caviardage |
| `revision` | Révision suivie (insertion, suppression, déplacement) |

### Liens et renvois (`lien`)

| id | type |
|---|---|
| `lien` | Zone cliquable d'un lien hypertexte |
| `renvoi` | Renvoi interne (voir page, voir figure) |

### Champs et contrôles de formulaire (`formulaire`)

| id | type |
|---|---|
| `champ_formulaire` | Champ de formulaire |
| `controle_contenu` | Contrôle de contenu |

### Médias, objets incorporés et pièces jointes (`media`)

| id | type |
|---|---|
| `objet_incorpore` | Objet incorporé (OLE, document) |
| `piece_jointe` | Pièce jointe |
| `media` | Audio, vidéo, 3D |

### Non identifié (`inconnu`)

| id | type |
|---|---|
| `inconnu` | Élément dont même la famille n'est pas établie |

## 2. Propriétés de toute bbox

### identite

| id | propriété | valeurs |
|---|---|---|
| `id` | Identifiant | chaîne |
| `type` | Type identifié | id de types |
| `statut` | Statut de l'identification | identifie | ambigu | non_identifie |
| `confiance` | Confiance | 0..1 |
| `alternatives` | Autres types possibles et leur score | liste [type, score] |
| `granularite` | Granularité de la boîte | page | zone | bloc | ligne | run | glyphe |
| `origine` | Origine du contenu | native | ocr | calcule |
| `references_source` | Références aux objets sources (objet natif, image, police) | liste |

### geometrie

| id | propriété | valeurs |
|---|---|---|
| `page_index` | Page | entier, base 0 |
| `bbox` | Boîte englobante | [x, y, largeur, hauteur] pt |
| `forme_exacte` | Forme exacte si non rectangulaire (quadrilatère, polygone ; rend aussi échelle et cisaillement) | points pt |
| `rotation` | Rotation | degrés |
| `retournement` | Retournement horizontal, vertical | booléens |
| `visibilite` | Visibilité | visible | rogne | invisible | masque |

### disposition

| id | propriété | valeurs |
|---|---|---|
| `ordre_lecture` | Ordre de lecture | entier |
| `ordre_empilement` | Ordre d'empilement | entier |
| `calque` | Calque (contenu optionnel) | nom |
| `zone_page` | Zone de page | en_tete | corps | notes | pied | marge |
| `colonne_index` | Colonne d'appartenance | entier |
| `parent` | Boîte parente (appartenance) | id |
| `enfants` | Boîtes enfants | ids |
| `suite` | Boîte qui continue le même contenu (débordement, page suivante) | id |
| `relations` | Relations typées hors appartenance | legende_de | note_de | etiquette_de | renvoie_a | illustre |
| `ancrage` | Ancrage | en_ligne | flottant |
| `position_relative` | Position relative à | page | marge | colonne | paragraphe | caractere + décalage pt |
| `habillage` | Habillage du texte | carre | serre | haut_bas | derriere | devant | aucun |
| `distance_texte` | Distance au texte | pt (4 côtés) |

### agencement_interne

| id | propriété | valeurs |
|---|---|---|
| `marges_internes` | Marges internes | pt (4 côtés) |
| `colonnes` | Colonnes de la page ou de la zone (nombre, largeurs, gouttières, filet) | entiers + pt + booléen |

### style_interne

| id | propriété | valeurs |
|---|---|---|
| `segments_style` | Segments de style successifs ; chaque segment porte des attributs de caractère, langue comprise | liste [début, fin, attributs] |

### contenu

| id | propriété | valeurs |
|---|---|---|
| `nature_contenu` | Nature du contenu | texte_natif | texte_image | image | vectoriel | mixte | vide |
| `texte` | Texte | chaîne |

## 3. Attributs par type

### caractere

| id | attribut | valeurs | familles |
|---|---|---|---|
| `police` | Police (famille, nom PostScript, fichier incorporé, classe serif / sans / mono / symbole) | chaînes + classe | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `taille` | Corps | pt | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `graisse` | Graisse | 100..900 | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `italique` | Italique, oblique | booléen | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `chasse` | Chasse (étroit, large) | % | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `couleur` | Couleur du texte | couleur | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `couleur_contour` | Couleur de contour du texte | couleur | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `soulignement` | Soulignement | aucun | simple | double | pointille… + couleur | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `barre` | Barré | aucun | simple | double | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `capitales` | Capitales, petites capitales | aucune | capitales | petites_capitales | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `position_verticale` | Exposant, indice, décalage vertical | normal | exposant | indice + décalage pt | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `espacement_lettres` | Espacement des lettres | pt | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `espacement_mots` | Espacement des mots | pt | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `echelle_horizontale` | Échelle horizontale | % | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `mode_rendu` | Mode de rendu | plein | contour | plein_contour | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `surlignage` | Surlignage | couleur | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `effets_texte` | Effets de texte (ombre, relief, gravure, marque d'emphase) | liste | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `casse` | Casse et casse à préserver | majuscules | minuscules | titre | phrase | mixte + booléen | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `langue` | Langue | BCP 47 | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `ecriture` | Système d'écriture | ISO 15924 | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |
| `sens_ecriture` | Sens d'écriture | ltr | rtl | ttb | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire |

### paragraphe

| id | attribut | valeurs | familles |
|---|---|---|---|
| `alignement` | Alignement horizontal | gauche | centre | droite | justifie | page, zone, texte, liste, tableau, annotation, formulaire |
| `alignement_vertical` | Alignement vertical | haut | centre | bas | page, zone, texte, liste, tableau, annotation, formulaire |
| `retraits` | Retraits gauche, droit, première ligne (négatif = suspendu) | pt | page, zone, texte, liste, tableau, annotation, formulaire |
| `espace_avant` | Espace avant | pt | page, zone, texte, liste, tableau, annotation, formulaire |
| `espace_apres` | Espace après | pt | page, zone, texte, liste, tableau, annotation, formulaire |
| `interligne` | Interligne | valeur + exact | au_moins | multiple | page, zone, texte, liste, tableau, annotation, formulaire |
| `taquets` | Taquets de tabulation | liste [position pt, type, points de conduite] | page, zone, texte, liste, tableau, annotation, formulaire |
| `niveau_hierarchique` | Niveau hiérarchique (intertitre, élément de liste, entrée de sommaire) | entier | texte, liste |
| `lignes_lettrine` | Lignes occupées (type lettrine seulement) | entier | texte |

### liste

| id | attribut | valeurs | familles |
|---|---|---|---|
| `format_marqueur` | Format du marqueur | puce | decimal | lettre | romain | image | liste |
| `texte_marqueur` | Texte du marqueur | chaîne | liste |

### numerotation

| id | attribut | valeurs | familles |
|---|---|---|---|
| `valeur_numero` | Valeur d'un numéro (marqueur, légende, équation, page) | entier ou chaîne | liste, texte, formule, page |

### tableau

| id | attribut | valeurs | familles |
|---|---|---|---|
| `dimensions_tableau` | Nombre de lignes et de colonnes | entiers | tableau |
| `largeurs_colonnes` | Largeurs de colonnes | pt | tableau |
| `hauteurs_lignes` | Hauteurs de lignes | pt + exact | au_moins | tableau |
| `position_cellule` | Ligne et colonne de la cellule | entiers | tableau |
| `fusion` | Fusion de cellules (colonnes, lignes) | entiers | tableau |
| `entete` | Cellule ou ligne d'en-tête (portée, répétée) | aucun | ligne | colonne + booléen | tableau |
| `espacement_cellules` | Espacement entre cellules | pt | tableau |

### aspect

| id | attribut | valeurs | familles |
|---|---|---|---|
| `remplissage` | Remplissage (couleur, dégradé, motif, image) | couleur / dégradé / référence | page, zone, texte, liste, tableau, formule, image, vectoriel, visualisation, decoration, annotation, lien, formulaire, media |
| `contour` | Contour ou bordure par côté (couleur, épaisseur, tirets, extrémités, jointures) | couleur + pt + motif | page, zone, texte, liste, tableau, formule, image, vectoriel, visualisation, decoration, annotation, lien, formulaire, media |
| `coins` | Rayon des coins | pt | page, zone, texte, liste, tableau, formule, image, vectoriel, visualisation, decoration, annotation, lien, formulaire, media |
| `opacite` | Opacité | 0..1 | page, zone, texte, liste, tableau, formule, image, vectoriel, visualisation, decoration, annotation, lien, formulaire, media |
| `effets` | Ombre, lueur, reflet, 3D | liste | page, zone, texte, liste, tableau, formule, image, vectoriel, visualisation, decoration, annotation, lien, formulaire, media |

### image

| id | attribut | valeurs | familles |
|---|---|---|---|
| `dimensions_pixels` | Dimensions en pixels | px | image |
| `transparence_image` | Transparence de l'image (canal alpha, masque) | aucune | alpha | masque | image |
| `recadrage` | Recadrage | % (4 côtés) | image |
| `texte_alternatif` | Texte alternatif | chaîne | image, vectoriel, visualisation, formule, media |

### forme

| id | attribut | valeurs | familles |
|---|---|---|---|
| `geometrie` | Géométrie (forme prédéfinie ou chemin, règle de remplissage) | nom | chemin | vectoriel, decoration, page |
| `pointes_fleche` | Pointes de flèche (début, fin) | énumération | vectoriel, visualisation |
| `connexions` | Éléments reliés par le connecteur | ids | vectoriel, visualisation |

### visualisation

| id | attribut | valeurs | familles |
|---|---|---|---|
| `structure_graphique` | Type de graphique, séries, axes, légende | type + données | visualisation |

### contenu_specifique

| id | attribut | valeurs | familles |
|---|---|---|---|
| `source_formule` | Source de la formule | latex | mathml + chaîne | formule |
| `langage_code` | Langage du code | nom | texte, expression |
| `texte_ruby` | Texte de l'annotation ruby | chaîne | en_ligne |
| `sous_type` | Sous-type (annotation, révision, champ de formulaire, champ calculé) | énumération selon le type | annotation, formulaire, en_ligne |
| `cible` | Cible (URI, page, élément, note) | chaîne / id | lien, annotation, en_ligne |
| `auteur_date` | Auteur et date d'une annotation ou d'une révision | chaîne + date | annotation |
| `nom_champ` | Nom du champ | chaîne | formulaire |
| `valeur_champ` | Valeur, valeur par défaut, options du champ | selon sous-type | formulaire |

### traduction

| id | attribut | valeurs | familles |
|---|---|---|---|
| `traduisible` | Traduisible, et raison sinon | oui | non | partiel + raison | page, zone, texte, en_ligne, expression, liste, tableau, formule, visualisation, annotation, lien, formulaire, image, vectoriel, media |

## 4. Attributs du document

| id | attribut | valeurs |
|---|---|---|
| `langue_declaree` | Langue déclarée | BCP 47 |
| `metadonnees` | Titre, auteur, sujet, mots-clés, dates, producteur | chaînes / dates |
| `plan` | Plan et signets | arbre [titre, niveau, cible] |

## 5. Attributs de la page

| id | attribut | valeurs |
|---|---|---|
| `libelle_page` | Libellé de page (numérotation logique : i, ii, 1…) | chaîne |
| `taille_page` | Taille visible | largeur, hauteur pt |
| `rotation_page` | Rotation | 0 | 90 | 180 | 270 |

## Annexe : notions écartées lors de la fusion

| notion | raison |
|---|---|
| `semantic_role` | doublon, fusionné dans `type` |
| `structure_node_kind` | doublon, fusionné dans `type` |
| `frame_type` | doublon, fusionné dans `type` |
| `role_semantique` | doublon, fusionné dans `type` |
| `object_type` | doublon, fusionné dans `type` |
| `font_family` | doublon, fusionné dans `police` |
| `font_postscript_name` | doublon, fusionné dans `police` |
| `embedded_font_path` | doublon, fusionné dans `police` |
| `classe_police` | doublon, fusionné dans `police` |
| `font_flags` | doublon, fusionné dans `police` |
| `cle_police_normalisee` | recalculable à partir des autres champs |
| `size_pt` | doublon, fusionné dans `taille` |
| `bold` | doublon, fusionné dans `graisse` |
| `italic` | doublon, fusionné dans `italique` |
| `color_rgb` | doublon, fusionné dans `couleur` |
| `fill_color` | doublon, fusionné dans `couleur` |
| `stroke_color` | doublon, fusionné dans `couleur_contour` |
| `opacite_texte` | doublon, fusionné dans `opacite` |
| `superscript` | doublon, fusionné dans `position_verticale` |
| `subscript` | doublon, fusionné dans `position_verticale` |
| `text_rise` | doublon, fusionné dans `position_verticale` |
| `indice_exposant` | doublon, fusionné dans `position_verticale` |
| `small_caps` | doublon, fusionné dans `capitales` |
| `all_caps` | doublon, fusionné dans `capitales` |
| `profil_casse` | doublon, fusionné dans `casse` |
| `marque_emphase` | doublon, fusionné dans `effets_texte` |
| `direction` | doublon, fusionné dans `sens_ecriture` |
| `mode_ecriture` | doublon, fusionné dans `sens_ecriture` |
| `sens_flux` | doublon, fusionné dans `sens_ecriture` |
| `orientation_texte_cellule` | doublon, fusionné dans `sens_ecriture` |
| `masque` | doublon, fusionné dans `visibilite` |
| `texte_invisible` | doublon, fusionné dans `visibilite` |
| `retrait_suspendu` | doublon, fusionné dans `retraits` |
| `retrait_premiere_ligne` | doublon, fusionné dans `retraits` |
| `heading_level` | doublon, fusionné dans `niveau_hierarchique` |
| `list_level` | doublon, fusionné dans `niveau_hierarchique` |
| `type_liste` | doublon, fusionné dans `format_marqueur` |
| `valeur_depart` | doublon, fusionné dans `valeur_numero` |
| `valeur_marqueur` | doublon, fusionné dans `valeur_numero` |
| `bordure` | doublon, fusionné dans `contour` |
| `trait` | doublon, fusionné dans `contour` |
| `bordure_paragraphe` | doublon, fusionné dans `contour` |
| `couleur_fond` | doublon, fusionné dans `remplissage` |
| `degrade` | doublon, fusionné dans `remplissage` |
| `motif` | doublon, fusionné dans `remplissage` |
| `trame_paragraphe` | doublon, fusionné dans `remplissage` |
| `ombre` | doublon, fusionné dans `effets` |
| `mask` | doublon, fusionné dans `transparence_image` |
| `alpha` | doublon, fusionné dans `transparence_image` |
| `chemin` | doublon, fusionné dans `geometrie` |
| `regle_remplissage` | doublon, fusionné dans `geometrie` |
| `quad` | doublon, fusionné dans `forme_exacte` |
| `polygone` | doublon, fusionné dans `forme_exacte` |
| `matrice_transformation` | doublon, fusionné dans `forme_exacte` |
| `xref` | doublon, fusionné dans `references_source` |
| `source_ids` | doublon, fusionné dans `references_source` |
| `reading_order_index` | doublon, fusionné dans `ordre_lecture` |
| `z_index` | doublon, fusionné dans `ordre_empilement` |
| `render_order_index` | doublon, fusionné dans `ordre_empilement` |
| `couloir` | doublon, fusionné dans `zone_page` |
| `continuation` | doublon, fusionné dans `suite` |
| `caption_for` | doublon, fusionné dans `relations` |
| `appartenance` | doublon, fusionné dans `parent` |
| `padding` | doublon, fusionné dans `marges_internes` |
| `marges_cellule` | doublon, fusionné dans `marges_internes` |
| `colonnes_internes` | doublon, fusionné dans `colonnes` |
| `colonnes_page` | doublon, fusionné dans `colonnes` |
| `alignement_lignes` | doublon, fusionné dans `alignement` |
| `interligne_mesure` | doublon, fusionné dans `interligne` |
| `translatable` | doublon, fusionné dans `traduisible` |
| `translation_eligibility` | doublon, fusionné dans `traduisible` |
| `segments_langue` | doublon, fusionné dans `segments_style` |
| `signet` | doublon, fusionné dans `plan` |
| `ligne_texte` | doublon, fusionné dans `granularite` |
| `run` | doublon, fusionné dans `granularite` |
| `glyphe` | doublon, fusionné dans `granularite` |
| `niveau` | doublon, fusionné dans `granularite` |
| `etiquette_detecteur` | doublon, fusionné dans `alternatives` |
| `sous_type_annotation` | doublon, fusionné dans `sous_type` |
| `sous_type_champ` | doublon, fusionné dans `sous_type` |
| `contenu_annotation` | doublon, fusionné dans `auteur_date` |
| `region_corps` | doublon, fusionné dans `zone_contenu` |
| `region_contenu` | doublon, fusionné dans `zone_contenu` |
| `barre_laterale` | doublon, fusionné dans `encadre` |
| `titre_tableau` | doublon, fusionné dans `legende` |
| `cellule_entete` | doublon, fusionné dans `entete` |
| `champ_texte` | doublon, fusionné dans `champ_formulaire` |
| `case_a_cocher` | doublon, fusionné dans `champ_formulaire` |
| `matrice` | doublon, fusionné dans `formule_bloc` |
| `formule_chimique` | doublon, fusionné dans `formule_bloc` |
| `annotation_tampon` | doublon, fusionné dans `annotation_graphique` |
| `warichu` | doublon, fusionné dans `ruby` |
| `mise_en_evidence` | style ou caractère, pas un type de bbox |
| `citation_en_ligne` | style ou caractère, pas un type de bbox |
| `tabulation` | style ou caractère, pas un type de bbox |
| `saut` | style ou caractère, pas un type de bbox |
| `symbole` | style ou caractère, pas un type de bbox |
| `mot` | hors du périmètre de l'identification |
| `phrase` | hors du périmètre de l'identification |
| `segment_traduisible` | recalculable à partir des autres champs |
| `segment_non_traduisible` | recalculable à partir des autres champs |
| `texte_dans_image` | recalculable à partir des autres champs |
| `contient_texte` | recalculable à partir des autres champs |
| `chapitre` | recalculable à partir des autres champs |
| `section` | recalculable à partir des autres champs |
| `orientation_page` | recalculable à partir des autres champs |
| `format_probable` | recalculable à partir des autres champs |
| `zones_page` | recalculable à partir des autres champs |
| `marges` | recalculable à partir des autres champs |
| `nature_page` | recalculable à partir des autres champs |
| `grille_lignes` | recalculable à partir des autres champs |
| `rapport_aspect` | recalculable à partir des autres champs |
| `resolution` | recalculable à partir des autres champs |
| `voisins` | recalculable à partir des autres champs |
| `chevauchements` | recalculable à partir des autres champs |
| `style_dominant` | recalculable à partir des autres champs |
| `comptages_texte` | recalculable à partir des autres champs |
| `categorie_unicode` | recalculable à partir des autres champs |
| `homogeneite_style` | recalculable à partir des autres champs |
| `couleurs_presentes` | recalculable à partir des autres champs |
| `nb_lignes` | recalculable à partir des autres champs |
| `cesure` | recalculable à partir des autres champs |
| `profil_document` | recalculable à partir des autres champs |
| `qualite_extraction` | recalculable à partir des autres champs |
| `nombre_pages` | recalculable à partir des autres champs |
| `langues_detectees` | recalculable à partir des autres champs |
| `polices_document` | recalculable à partir des autres champs |
| `orientation_exif` | détail propre à un format de fichier |
| `style_nomme` | détail propre à un format de fichier |
| `crenage` | détail propre à un format de fichier |
| `ligatures` | détail propre à un format de fichier |
| `profondeur_bits` | détail propre à un format de fichier |
| `interpolation` | détail propre à un format de fichier |
| `grille_document` | détail propre à un format de fichier |
| `disposition_tableau` | détail propre à un format de fichier |
| `style_tableau` | détail propre à un format de fichier |
| `format_image` | détail propre à un format de fichier |
| `espace_couleur` | détail propre à un format de fichier |
| `mode_fusion` | détail propre à un format de fichier |
| `boites_page` | détail propre à un format de fichier |
| `groupe` | doublon, fusionné dans `enfants` |
| `contraintes_reconstruction` | décision de la reconstruction, pas de l'identification |
| `politique_rendu` | décision de la reconstruction, pas de l'identification |
| `politique_protection` | décision de la reconstruction, pas de l'identification |
| `rendu_obligatoire` | décision de la reconstruction, pas de l'identification |
| `preserver_visuel` | décision de la reconstruction, pas de l'identification |
| `objet_rendu` | décision de la reconstruction, pas de l'identification |
| `debordement` | décision de la reconstruction, pas de l'identification |
| `enchainement` | décision de la reconstruction, pas de l'identification |
| `region_preservee` | décision de la reconstruction, pas de l'identification |
| `sous_regions_conservees` | décision de la reconstruction, pas de l'identification |
| `sous_regions_traduisibles` | décision de la reconstruction, pas de l'identification |
| `fond_a_ignorer` | décision de la reconstruction, pas de l'identification |
| `source_fichier` | hors du périmètre de l'identification |
| `propriete_technique_pdf` | hors du périmètre de l'identification |
| `image_page_rendue` | hors du périmètre de l'identification |
| `dpi_page` | hors du périmètre de l'identification |
| `espace_blanc` | hors du périmètre de l'identification |
| `zone_decoupe` | hors du périmètre de l'identification |
| `domaine` | hors du périmètre de l'identification |
