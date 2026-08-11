# Décision : reconnaissance des polices

**Approche retenue : reconnaître la police exacte nommée par le PDF, dans une
bibliothèque locale indexée.** Le `.docx` la référence par son nom ; `--embed-fonts`
l'embarquera.

Une première version de cette note concluait « pas d'embarquement, substitution vers
Arial ». Ce cadrage était faux et est abandonné : il traitait le sous-ensemble embarqué
dans le PDF comme la seule source possible, alors que le PDF fournit surtout un *nom*.

## Le raisonnement

Un PDF embarque des sous-ensembles de police : réduits aux glyphes employés, souvent
privés de leur table `cmap`. Mesure sur 19 polices de trois PDF réels :

| Type | Encodage | cmap |
|---|---|---|
| TrueType | WinAnsiEncoding | 407-409 entrées |
| TrueType | MacRomanEncoding | 0 entrée |
| Type0 (CID) | Identity-H | table absente |
| Type1 (`pfa`) | — | illisible par fontTools |

Trois cas sur quatre sont inexploitables — dont Type0/Identity-H, dominant dans les PDF
modernes. Conclusion correcte : **le sous-ensemble du PDF n'est pas une source de
métriques**. Conclusion erronée qu'on en avait tirée : « donc on substitue à l'aveugle ».

Le PDF donne aussi le nom PostScript de chaque police (`AAAAAB+HelveticaNeue-Bold`).
Ce nom suffit à retrouver la police complète sur le disque — laquelle a un cmap valide et
les bonnes chasses. C'est cette police qui fait autorité.

Substituer à l'aveugle fausse les largeurs, donc oblige la correction d'espacement à
rattraper un écart grossier. Reconnaître la police rend cette correction fine.

## Mise en œuvre

`pdfexact/fontlib.py` construit un index et le résout en cascade :

1. nom PostScript exact, préfixe de sous-ensemble retiré
2. famille + style
3. **équivalence métrique** via `pdfexact/data/alias_polices.json`
4. famille seule, en Regular
5. échec → substitution signalée dans le rapport

Sources indexées, par priorité croissante : polices système via `fc-list` (qui expose
déjà le nom PostScript, donc sans ouvrir les fichiers), puis les dossiers — `fonts/` du
projet et tout `--font-dir`. Un dossier l'emporte toujours sur le système, ce qui rend une
conversion reproductible d'un poste à l'autre.

## Mesure de reconnaissance

Sur les mêmes trois PDF, 53 polices distinctes, avec 139 polices système indexées et un
dossier `fonts/` vide :

| Étape | Reconnues |
|---|---|
| Nom PostScript et famille seuls | 4 / 53 |
| **+ table d'équivalences métriques** | **28 / 53** |

Les 25 manques restants se répartissent en trois catégories, et une seule appelle une
action :

- **Polices absentes** (5 — Raleway et ses graisses) : à déposer dans `fonts/`. C'est le
  cas nominal que la bibliothèque est faite pour traiter.
- **Computer Modern en corps 6 à 9** (12) : seul le corps 10 est installé. Les rediriger
  vers cmr10 fausserait les chasses — les tailles optiques de CM ne sont pas homothétiques.
  Laissés en repli délibérément.
- **Sous-ensembles anonymes** (8 — `TT2Bo00`, `TT79o00`) : le PDF ne dit pas de quelle
  police il s'agit. Aucun dossier n'y changera rien ; seul le repli s'applique.

## Embarquement

Redevenu possible, et pour la bonne raison : on embarquerait la police **de la
bibliothèque**, complète et pourvue d'un cmap, jamais le sous-ensemble cassé du PDF.

`pdfexact/render/fonts_embed.py` fournit l'obfuscation `.odttf` attendue par Word,
testée (8 tests). Non branché pour l'instant : le comportement par défaut est le
référencement par nom, `--embed-fonts` viendra l'activer.

**Non validé** : l'algorithme d'obfuscation n'a pas été confronté à un `.docx` produit par
Word. Les tests prouvent l'involution et la dérivation de clé, pas la conformité. Cette
validation appartient au chantier `--embed-fonts`.
