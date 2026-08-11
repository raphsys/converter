# Bibliothèque de polices

Déposez ici les fichiers de police (`.ttf`, `.otf`, `.ttc`) que vos PDF utilisent.
Le dossier est scanné récursivement, et **il a priorité sur les polices installées du
système** : c'est ce qui rend une conversion reproductible d'une machine à l'autre.

## Pourquoi c'est nécessaire

Un PDF n'embarque qu'un *sous-ensemble* de chaque police, réduit aux seuls glyphes
utilisés, et souvent privé de sa table de correspondance caractère → glyphe. Ce
sous-ensemble ne permet ni de mesurer du texte ni de le réafficher.

En revanche, le PDF nomme toujours ses polices. Le convertisseur lit ce nom et cherche la
vraie police correspondante : ici d'abord, puis parmi les polices du système.

Quand la police est trouvée, ses métriques réelles servent à positionner le texte, et le
`.docx` déclare son vrai nom. Quand elle ne l'est pas, le convertisseur retombe sur une
famille approchante et le signale dans son rapport de conversion.

## Savoir quoi déposer

Le rapport de conversion liste les polices non reconnues. Ce sont celles à récupérer.

Trois cas de figure parmi les manques :

- **Police commerciale ou absente du système** — Raleway, Helvetica Neue, une police
  d'entreprise. C'est le cas nominal : déposez le fichier ici.
- **Police ayant un clone métrique déjà installé** — Arial, Times New Roman, Courier.
  Inutile de la déposer : `pdfexact/data/alias_polices.json` la redirige vers son clone
  (Liberation, Nimbus…), dont les chasses sont identiques.
- **Sous-ensemble anonyme** — noms du type `TT2Bo00`, `ABCDEF+F1`. Le PDF ne dit pas de
  quelle police il s'agit ; aucun dossier n'y changera rien.

## Ajouter une équivalence

Si une famille devrait être redirigée vers une autre, éditez
`pdfexact/data/alias_polices.json` plutôt que de dupliquer un fichier de police. Le
format et les conventions de nommage sont documentés dans le fichier lui-même.

## Autres dossiers

L'option `--font-dir` accepte d'autres emplacements, et se répète :

```bash
pdfexact convertir doc.pdf doc.docx --font-dir ~/polices-client --font-dir /opt/fonts
```

Le contenu de ce dossier n'est pas suivi par git, à l'exception de ce fichier : les
polices ont leurs propres licences de redistribution.
