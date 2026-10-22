# Plan d'implementation et de suivi - conformite visuelle PDF -> DOCX

Objectif: faire du DOCX un reflet visuel du PDF source, element par element,
avec conservation de l'editabilite lorsque Word sait representer la geometrie.

Regle de certification: un document ne peut pas etre declare conforme si une
propriete visuelle n'a pas ete verifiee apres rendu reel du DOCX.

## 1. Contrat visuel canonique

- [x] Ajouter un contrat visuel commun pour texte, image, forme, raster et tableau.
- [x] Conserver bbox, quad, baseline, z-order, orientation, rotation, clipping,
      style, fond, bordure, opacite et provenance.
- [x] Propager ce contrat dans `ir.py` et `scene.py` sans perte lors de
      `scene_from_legacy_document()`.
- [x] Ajouter les etats `detected`, `extracted`, `planned`, `rendered`,
      `verified`, `failed` et `non-representable`.

Fichiers: `pdfexact/ir.py`, `pdfexact/scene.py`,
`pdfexact/analysis/provenance.py`.

Resultat attendu: aucune transformation ne peut supprimer une propriete visuelle
sans trace ni diagnostic.

## 2. Extraction geometrique et orientation

- [x] Conserver bbox de bloc, ligne, span, quad de glyphe et baseline PDF.
- [x] Separer bbox de composition et bbox glyphique.
- [x] Calculer l'angle reel et distinguer horizontal, vertical, oblique et courbe.
- [x] Propager l'orientation et la confiance jusqu'au plan de rendu.
- [x] Ne jamais remplacer une valeur inconnue par une valeur visuelle arbitraire.

Fichiers: `pdfexact/extract/text.py`, `pdfexact/extract/orientation.py`,
`pdfexact/extract/styles.py`.

Resultat attendu: le texte vertical, oblique ou courbe arrive au renderer avec
sa geometrie source.

## 3. Metriques de polices

- [x] Implementer une resolution exacte/equivalente/substituee explicite.
- [x] Conserver les metriques ascender, descender, largeur, kerning et style.
- [x] Interdire les corrections arbitraires de taille.
- [x] Borner et journaliser tout espacement correctif.

Fichiers: `pdfexact/extract/fonts.py`, `pdfexact/fontlib.py`,
`pdfexact/data/alias_polices.json`, `pdfexact/render/drawing.py`.

Resultat attendu: une substitution typographique ne peut plus provoquer une
recomposition silencieuse.

## 4. Comprehension de page et provenance

- [x] Separer detection, classification, protection et rendu.
- [x] Interdire a une zone IA composite de remplacer un objet natif.
- [x] Tracer chaque rejet, fusion, fallback et decision avec sa source.
- [x] Rendre tout element rejete, restaure ou bloquant pour l'audit.

Fichiers: `pdfexact/layout/understanding.py`, `pdfexact/layout/ai.py`,
`pdfexact/extract/document.py`, `pdfexact/analysis/provenance.py`.

Resultat attendu: aucun element extrait ne disparait silencieusement.

## 5. Regroupement semantique non destructif

- [x] Fusionner uniquement selon provenance, frame/colonne, role, orientation,
      style, continuite lexicale et absence de conflit.
- [x] Conserver tous les source_ids, spans, lignes et styles apres fusion.
- [x] Interdire l'elargissement silencieux d'une bbox.
- [x] Effectuer une seule preparation semantique avant le RenderPlan.

Fichiers: `pdfexact/analysis/semantic.py`, `pdfexact/render/reflow.py`.

Resultat attendu: colonnes, titres, listes, legendes et credits restent separes.

## 6. Decisions de rendu universelles

- [x] Distinguer `NATIVE_FLOW`, `NATIVE_LIST`, `NATIVE_TABLE`,
      `LOCKED_NATIVE_PARAGRAPH`, `ROTATED_NATIVE_TEXT`, `CURVED_TEXT`,
      `ANCHORED_IMAGE`, `ANCHORED_SHAPE` et fallback raster.
- [x] Autoriser le flux uniquement si le reflow peut rester compatible.
- [x] Rendre la bbox, l'orientation, le style et le z-order attendus obligatoires.

Fichiers: `pdfexact/analysis/decisions.py`, `pdfexact/render/render_plan.py`.

Resultat attendu: un texte horizontal geometrique n'est plus force dans un flux
Word qui modifierait sa position.

## 7. Rewriter Word-native

- [x] Ne plus elargir les regions de texte a partir d'images ou de voisins.
- [x] Conserver la bbox source pour les paragraphes verrouilles.
- [x] Ne pas simuler les paragraphes naturels par des sauts de ligne artificiels.
- [x] Rendre les textes verticaux et obliques dans un conteneur editable visible.
- [x] Ne jamais produire un cadre vide.
- [x] Verifier clipping, rotation, largeur interne et hauteur interne.

Fichiers: `pdfexact/render/word_native_rewriter.py`,
`pdfexact/render/drawing.py`.

Resultat attendu: texte natif editable et positionne exactement, sans texte
derriere les images ni lignes artificielles inutiles.

## 8. Couches et superposition

- [x] Introduire un ordre de peinture explicite: fond, formes, images, texte,
      annotations, liens.
- [x] Conserver remplissage, bordure, transparence, clipping et rotation.
- [x] Ne plus dependre uniquement de `behindDoc`, de l'ordre XML ou d'un z-index
      approximatif.

Fichiers: `pdfexact/render/drawing.py`, `pdfexact/extract/vector.py`,
`pdfexact/extract/images.py`, `pdfexact/render/word_native_rewriter.py`.

Resultat attendu: superposition identique au PDF source.

## 9. Pages, sections et coordonnees

- [x] Centraliser points PDF -> EMU -> twips.
- [x] Figer dimensions, orientation, marges, ancres et sections.
- [x] Interdire les debordements ou changements de page non audites.

Fichiers: `pdfexact/render/section_layout.py`, `pdfexact/render/package.py`.

Resultat attendu: chaque element reste sur la page source et a la meme position.

## 10. Audit visuel bloquant

- [x] Auditer presence, texte, images, formes, tables et elements en trop.
- [x] Comparer bbox, quad, angle, baseline, largeur, hauteur et centre.
- [x] Comparer police, taille, couleur, fond, bordure, interligne, espacements,
      retraits et marges internes.
- [x] Detecter occlusion, doublon, cadre vide, texte masque et mauvais z-order.
- [x] Comparer les regions source/sortie et non seulement le score global de page.
- [x] Echouer si le rendu DOCX n'est pas disponible ou si une propriete n'est pas
      verifiee.

Fichiers: `pdfexact/final_audit.py`, `pdfexact/report.py`, `pdfexact/cli.py`.

Resultat attendu: un DOCX structurellement valide mais visuellement faux est
declare en echec.

## 11. Boucle de correction apres rendu

- [x] Rendre le DOCX, comparer, produire des erreurs ciblees, corriger, rerendre.
- [x] Journaliser ancienne valeur, nouvelle valeur, cause et scores.
- [x] Limiter les passes par `max_repair_passes`.
- [x] Interdire la certification sans audit final reexecute.

Fichiers: `pdfexact/final_audit.py`, `pdfexact/render/package.py`,
`pdfexact/cli.py`.

Resultat attendu: l'audit corrige les proprietes fautives puis revalide le resultat.

## 12. Tests universels

- [x] Ajouter tests du contrat visuel, geometrie, typographie, z-order,
      orientation, colonnes, listes, fonds, pages et audit fail-closed.
- [x] Tester plusieurs familles de PDF et pas uniquement le corpus courant.

Fichiers: `tests/visual/` et tests unitaires associes.

Resultat attendu: une correction n'est validee que si elle generalise.

## Journal d'implementation

- [x] 1. Contrat visuel canonique
- [x] 2. Extraction geometrique et orientation
- [x] 3. Metriques de polices
- [x] 4. Comprehension et provenance
- [x] 5. Regroupement non destructif
- [x] 6. Decisions universelles
- [x] 7. Rewriter Word-native
- [x] 8. Couches et superposition
- [x] 9. Pages et coordonnees
- [x] 10. Audit visuel bloquant
- [x] 11. Boucle de correction
- [x] 12. Tests universels

Chaque case est cochee seulement apres modification, tests et verification du
critere de resultat associe.
