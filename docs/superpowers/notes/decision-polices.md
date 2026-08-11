# Décision : embarquement des polices

**Verdict : `EMBARQUEMENT_RETENU = False`.**

La conversion utilise les polices système, avec correction de largeur par espacement.
C'est le mode de repli prévu par la spec §8, et il devient le comportement unique.

## Mesure

Sonde `scripts/probe_pymupdf.py` exécutée sur trois PDF réels, publics et techniques —
une licence, un article scientifique, une classification médicale. 19 polices relevées.
Pour chacune : extraction via `doc.extract_font(xref)`, puis lecture du cmap par
fontTools.

| Type de police | Encodage | Exemple | Octets | cmap |
|---|---|---|---|---|
| TrueType | WinAnsiEncoding | `FAWIGL+Raleway-Medium` | 8352 | **407 entrées** |
| TrueType | WinAnsiEncoding | `FAWIGL+Raleway-Bold` | 13496 | **407 entrées** |
| TrueType | WinAnsiEncoding | `FAWIGL+Raleway-Thin` | 8198 | **409 entrées** |
| TrueType | MacRomanEncoding | `AAAAAB+HelveticaNeue-Bold` | 9952 | **0 entrée** |
| TrueType | MacRomanEncoding | `AAAAAC+HelveticaNeue` | 14156 | **0 entrée** |
| Type0 (CID) | Identity-H | `FAWIGL+Raleway-Medium` | 10700 | **table absente** |
| Type0 (CID) | Identity-H | `NVCIQX+Raleway-Bold` | 8568 | **table absente** |
| Type1 (`pfa`) | — | `BZVLCX+NimbusSanL-Regu` | 9726 | **illisible par fontTools** |
| Type1 (`pfa`) | — | `JCVQDE+URWPalladioL-Roma` | 26175 | **illisible par fontTools** |
| base-14 | — | `Times-Roman` | 0 | non embarquée |

Un seul des quatre cas embarquables fonctionne directement : TrueType avec un encodage
simple. Les trois autres échouent, chacun pour une raison distincte :

- **MacRomanEncoding** : la police est un sous-ensemble dont le cmap a été retiré. Le
  mappage code → glyphe vit dans le dictionnaire de police du PDF, pas dans le fichier.
- **Type0 / Identity-H** : par construction, ces polices CID n'ont pas de table cmap. Le
  code du caractère *est* l'identifiant de glyphe, et la correspondance vers Unicode passe
  par le `ToUnicode` du PDF. C'est le cas dominant des PDF modernes.
- **Type1 / `pfa`** : format non-sfnt, que fontTools ne peut pas ouvrir sans conversion
  préalable vers OTF.

## Pourquoi ça tranche

La spec §8 annonçait le risque : « les polices embarquées dans un PDF sont presque
toujours des sous-ensembles, dont la table cmap est absente ou arbitraire ». La mesure le
confirme, et précise l'ampleur : ce n'est pas un cas limite, c'est le cas courant.

La mitigation prévue — reconstruire le cmap depuis le `ToUnicode` — reste techniquement
possible, mais elle représente un chantier à elle seule : trois chemins de code distincts
(sfnt sans cmap, CID, Type1), chacun avec ses pièges, pour un gain qui ne porte que sur la
forme exacte des glyphes. La mise en page, elle, est déjà exacte sans embarquement grâce à
la correction de largeur.

C'est un mauvais rapport risque/valeur en début de projet. Décision : on livre le mode
police système, et l'embarquement redevient un chantier candidat une fois la chaîne
complète mesurée.

## Ce qui reste en place

`pdfexact/render/fonts_embed.py` fournit `obfusquer_police()` et `nouveau_guid()`,
testés (8 tests). C'est de l'infrastructure **non branchée** : rien ne l'appelle
aujourd'hui. Elle est conservée parce qu'elle encode la partie non évidente du problème —
l'obfuscation `.odttf` attendue par Word — et rend le chantier de suivi mécanique.

**Non validé** : l'algorithme d'obfuscation n'a pas été confronté à un `.docx` produit par
Word avec polices embarquées. Les tests prouvent l'involution et la dérivation de clé, pas
la conformité à Word. Cette validation appartient au chantier d'embarquement, pas à
maintenant.

## Conséquence sur la spec

`--no-embed-fonts` (spec §7) n'est pas implémentée : un drapeau qui ne commute rien serait
pire que pas de drapeau. Elle apparaîtra avec l'embarquement. Voir la section « Écart
assumé avec la spec » du plan d'implémentation.
