# Polices : bibliothèque embarquée et extensions

Le projet embarque sa propre bibliothèque de polices, dans `pdfexact/fonts/`. C'est ce qui
le rend autonome : un clone du dépôt convertit à l'identique sur n'importe quelle machine,
sans dépendre de ce qui y est installé.

## Les trois niveaux

Indexation du moins au plus prioritaire — le dernier inscrit gagne :

| Emplacement | Contenu | Suivi par git |
|---|---|---|
| Polices du système | ce que `fc-list` déclare | — |
| `pdfexact/fonts/` | **405 polices à licence libre**, livrées avec le projet | oui |
| `fonts/` (ce dossier) | vos ajouts, propres à cette machine | non |
| `--font-dir <chemin>` | dossiers supplémentaires, option répétable | — |

Une police déposée ici l'emporte donc sur celle livrée, qui l'emporte sur celle du système.

## Pourquoi une bibliothèque plutôt que les polices du PDF

Un PDF n'embarque qu'un *sous-ensemble* de chaque police, réduit aux glyphes employés et
souvent privé de sa table de correspondance caractère → glyphe. Ce sous-ensemble ne permet
ni de mesurer du texte ni de le réafficher.

En revanche, le PDF nomme toujours ses polices. Le convertisseur lit ce nom et cherche la
vraie police : ici, puis dans la bibliothèque embarquée, puis sur le système. Trouvée, ses
métriques réelles positionnent le texte au bon endroit. Non trouvée, le convertisseur
retombe sur une famille approchante et le signale dans son rapport.

## Ajouter des polices

Déposez les fichiers `.ttf`, `.otf` ou `.ttc` dans ce dossier — il est scanné
récursivement. Le rapport de conversion liste les polices non reconnues : ce sont
précisément celles à récupérer.

Trois cas parmi les manques, un seul appelle une action :

- **Police absente** (Raleway, Helvetica Neue, une police d'entreprise) : déposez-la ici.
- **Police ayant un clone métrique** (Arial, Times New Roman, Courier) : inutile.
  `pdfexact/data/alias_polices.json` la redirige vers Liberation, Nimbus ou Carlito, dont
  les chasses sont identiques. Pour ajouter une équivalence, éditez ce fichier plutôt que
  de dupliquer un fichier de police.
- **Sous-ensemble anonyme** (`TT2Bo00`, `ABCDEF+F1`) : le PDF ne dit pas de quelle police
  il s'agit. Aucun dossier n'y changera rien.

## Outils

```bash
# Moissonner les polices complètes déjà présentes sur la machine
python scripts/importer_polices.py --destination fonts

# Vérifier ce qui est redistribuable avant d'ajouter à la bibliothèque embarquée
python scripts/auditer_licences.py --dossier pdfexact/fonts
```

## Licences

Seules les polices à licence libre vérifiée sont embarquées dans `pdfexact/fonts/` :
OFL, Apache, MIT, Ubuntu Font License, domaine public. La vérification lit le champ
`fsType` et les mentions de licence de chaque fichier ; une licence non identifiée est
refusée, jamais présumée permissive.

`fonts/local/` reçoit ce que l'audit écarte. Ce dossier n'est pas suivi par git : ces
polices restent utilisables pour vos conversions, mais ne sont pas redistribuées.
