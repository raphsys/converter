# Suivi borne : IA multilingue CPU

Date d'ouverture : 2026-10-11.

## Mandat Et Limites

Demande explicite : ajouter/installer des modeles IA multilingues dans
`/home/raphael/Mes_Projets/vysi/ai_models`, utilisables sur CPU et raccordes a
la reconnaissance, a la comprehension et a l'extraction. Cibles demandees :
russe/cyrillique, ecritures est-asiatiques et autres ecritures a documenter.
Les trois premieres pages du PDF utilisateur a921 ont du texte PDF cyrillique
verifie par Pascal et preserve sans OCR. Le script observe ne certifie pas a
lui seul la langue russe ni les autres pages du document.

Ce mandat ne reprend pas la refonte universelle, explicitement PAUSED.
Ce worker possede ce nouveau suivi et les artefacts de verification bornee
explicitement autorises ensuite par le parent. Il n'installe aucun modele,
ne modifie aucun code de production/test, ne touche pas l'ancien tracker et
ne lance aucun benchmark global. Les preuves des owners et de l'integration
ci-dessous determinent seules les cases cochees.

## Politique D'Activation Decidee

Decision du parent le 2026-10-11, a distinguer des preuves de verification :

- **OCR multilingue et heuristiques Unicode actifs par defaut.** Les 11 poids
  OCR sont installes ; contrats CPU et six smokes synthetiques independants
  revalides. Qualite documentaire generale et autres ecritures non qualifiees.
- **Comprehension locale CT2/Qwen experimentale uniquement**, pas activee par
  defaut : API `experimental_local=False`, `local_timeout=30` secondes.
- Opt-in CLI explicite : `--experimental-local-text-understanding`, scope Pascal.
  La presence des poids et la configuration du root IA partage ne valent pas
  opt-in et ne doivent pas charger/activer automatiquement le modele local.
- **HTTP explicitement configure prioritaire** sur le provider local. Les options
  de root IA communes ne changent pas cette precedence.
- Qualite semantique insuffisante : aucune qualification semantique ou couverture
  multilingue universelle annoncee. Le parent indique avoir informe l'utilisateur.
- Owners figes, puis GO final borne execute : **330 passed**, zero skip,
  deux warnings ; lot couverture distinct **2 failed**, defaut deja observe.
  Derniere iteration Qwen **6/15 attentes satisfaites**, non qualifiee.
  Aucun opt-in LLM reel, probe CT2 ou ancien diagnostic relance par ce worker.

## Etat Connu

- Ancienne fullsuite : handle outil **9542 termine**, code retour **1** ;
  1047 passed, 2 failed, 1 skipped, 6 warnings, 411.79 s.
- Ancien pytest hote : PID 1024095 pendant cette execution terminee ; ce PID
  historique n'est pas un handle reutilisable ni une preuve de processus actuel.
- Cinq diagnostics e03/Tideman/Katrina/NASA/96a80 : **jamais lances** par ce
  worker, aucun handle associe. Aucun job de ce worker laisse vivant.
- Preuves anciennes conservees :
  `results/refonte_universelle_release_20261011T112019Z/failure_checkpoint.json`.
  Elles ne prouvent ni installation ni prise en charge multilingue.
- Aucun processus tiers inconnu relance, annule ou tue. Aucun nouveau controle
  de processus tiers effectue dans ce mandat documentaire.
- Resultats des nouvelles missions recus a l'ouverture : **aucun**.
  Depuis, attribution des owners et constats d'audit recus du parent, voir
  ci-dessous. Le rapport final de provisioning est maintenant recu et rapproche
  des fichiers locaux : **11 poids OCR installes, hashes conformes**, sondes CPU
  synthetiques conservees. Versions des distributions converter relues sans
  charger les modeles lors de cette reconciliation. Depuis, preuves finales
  Pascal/Hubble recues et integration bornee terminee : six smokes OCR et un
  bitmap PDF revalides, Qwen **9/15 puis 6/15**, comprehension non qualifiee.
  Handle **99619 clos**, aucun job de ce run vivant. Aucun resultat de qualite
  universelle ni de pipeline integral valide. Voir reception finale ci-dessous.

## Missions Et Preuves Attendues

Owners confirmes par le parent le 2026-10-11. Ce tableau ne constitue ni une
nouvelle delegation de ce worker ni une validation des missions attribuees.

| Mission | Owner | Etat | Preuve attendue |
|---|---|---|---|
| OCR routing, options/CLI, script utilisateur et filtres | Pascal | Fige ; raccords et smokes bornes revalides | Deux uncovered-source encore ouverts ; autres ecritures/qualite documentaire non mesurees |
| Provider comprehension CT2 CPU, heuristiques Unicode, jonctions CJK | Hubble | Fige ; contrats/regles revalides, Qwen 9/15 puis 6/15 | Local experimental uniquement ; semantique non qualifiee |
| Provisioning poids vysi, dependance CT2 converter, manifestes/preuves | Lovelace | Rapport final recu ; 11 poids/hashes verifies, preuves CPU synthetiques lues | Accuracy hors scope provisioning ; provenance conversion Qwen toujours inconnue |
| Verification ciblee des raccords | Owners puis ce worker sur GO | Terminee : union 330 passed ; couverture separee 2 failed | Logs/JUnit/SHA et sorties OCR archives sans cumul des lots owners |
| Consolidation documentaire | Ce worker | Reception bornee terminee, limites ouvertes | Ce fichier ; aucune certification universelle |

## Constats Recus Des Owners

Constats initiaux transmis par le parent depuis les audits Hubble/Lovelace,
non rejoues par ce worker. Le provisioning final et sa reconciliation locale,
recus ensuite, sont distingues dans la section dediee ci-dessous.

| Constat | Evidence recue et portee exacte | Limite / suite attendue |
|---|---|---|
| Qwen CT2 deja present | Hubble rapporte environ 473 MiB et des fichiers tokenizer locaux | Presence preexistante, pas une installation nouvelle ni une inference CPU reussie |
| Provider de comprehension existant au premier audit | Hubble rapportait un raccord HTTP seulement et un provider manquant | Etat initial, pas l'etat des sondes CT2 suivantes ; comprehension toujours a valider |
| Heuristiques de prose | Audit Hubble : heuristiques limitees au latin | Unicode/cyrillique et jonctions CJK a implementer/verifier, non declares acquis |
| Fichiers tokenizer/configuration Qwen | Lovelace rapporte l'identite avec la revision officielle ci-dessous, licence Apache-2.0 | Identite de ces fichiers seulement ; ne certifie pas les poids convertis |
| Poids `model.bin` CT2 | SHA-256 rapporte ci-dessous | Provenance de conversion non certifiee ; pas de declaration de conversion officielle/reproductible |

Revision officielle Qwen rapportee pour les fichiers tokenizer/configuration :
`7ae557604adf67be50417f59c2c2f167def9a775`.

SHA-256 rapporte pour `model.bin` :
`b6d8dda7a5dffe272726b782102f3181c409d049e014e809d80363578be921fc`.

Le nom exact/variant du modele et les chemins n'etaient pas fournis au premier
checkpoint ; le rapport final inventorie maintenant le bundle local et designe
`Qwen/Qwen2.5-0.5B-Instruct` comme origine candidate. Les preuves de comparaison
amont, version/commande de conversion et hashes des poids amont restent absents.
Ne pas extrapoler la licence et l'identite du tokenizer en certification du binaire.
Une future inference reussie prouverait son fonctionnement observe, pas a elle
seule sa provenance de conversion.

## Checkpoint Initial Lovelace : CT2 Et OCR

Historique transmis par le parent le 2026-10-11, non rejoue par ce worker.
Les etats "en preparation" ci-dessous sont remplaces pour le provisioning
par le rapport final suivant, sans effacement de cet historique :

- `ctranslate2 == 4.8.0` rapporte installe dans l'environnement converter avec
  `--no-deps` ; import CPU rapporte reussi, types `int8` et `int8_float32` annonces.
  Ceci n'est pas encore une preuve de chargement de Qwen ni d'inference sur texte.
- `tokenizers == 0.23.1` rapporte inchange. Aucune conclusion sur la coherence de
  toutes les dependances n'est deduite de l'option `--no-deps`.
- Huit modeles de reconnaissance OCR v5 : **telechargements en preparation**,
  pas declares telecharges, installes ou executes.
- Modele OCR V6 small preexistant : Lovelace rapporte sa validation SHA pour le
  support chinois simplifie/traditionnel, japonais et latin. Chemin, valeur de
  SHA et log de validation restent a recevoir ; aucune inference de ces ecritures
  n'est prouvee par ce seul constat d'integrite/capacite.
- Aucun modele, runtime, hash ou resultat d'inference verifie a nouveau ici.
  Cases installation/OCR inference maintenues ouvertes jusqu'aux chemins/logs.

| Identifiant de famille v5 rapporte | Ecriture/cible annoncee | Etat recu | Preuves restantes |
|---|---|---|---|
| `cyrillic` | Cyrillique | En preparation | Poids/chemin/hash/config, chargement et inference CPU |
| `korean` | Coreen/hangul | En preparation | Poids/chemin/hash/config, chargement et inference CPU |
| `arabic` | Arabe | En preparation | Poids/chemin/hash/config, chargement et inference CPU |
| `devanagari` | Devanagari | En preparation | Poids/chemin/hash/config, chargement et inference CPU |
| `th` | Thai | En preparation | Poids/chemin/hash/config, chargement et inference CPU |
| `el` | Grec | En preparation | Poids/chemin/hash/config, chargement et inference CPU |
| `ta` | Tamoul | En preparation | Poids/chemin/hash/config, chargement et inference CPU |
| `te` | Telougou | En preparation | Poids/chemin/hash/config, chargement et inference CPU |

Ces identifiants sont ceux du checkpoint, pas des noms de fichiers deduits ni
une certification de toutes les langues utilisant chaque ecriture. La liste
exacte supportee et les resultats par langue restent a documenter.

Sources officielles indiquees par Lovelace pour le provisioning, sans nouvelle
verification web de ce worker :

- [RapidOCR default_models.yaml, tag v3.9.2](https://github.com/RapidAI/RapidOCR/blob/v3.9.2/python/rapidocr/default_models.yaml).
- [PaddleOCR PP-OCRv5 multi languages](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md).
- Poids annonces : ModelScope `RapidAI/RapidOCR`, version `v3.9.2`.

La reference PaddleOCR utilise `main`, donc ne constitue pas une revision
immuable. Le commit documentaire reste non fourni ; URLs exactes des poids,
correspondances fichier/dictionnaire/hash et preuves de provisioning sont
maintenant disponibles dans le rapport final.

## Provisioning Final Verifie

Preuves lues le 2026-10-11, sans relancer script, test, chargement de modele,
inference ou benchmark :

- Rapport : [model_provisioning_20261011.json](../results/model_provisioning_20261011.json),
  schema `pdfexact.model-provisioning-proof.v1`, SHA-256
  `fa15cd7d4586181bdabc107ddf75792c5a556cc29bb434c7412bdfdecce9ffd8`.
- Catalogue reel :
  `/home/raphael/Mes_Projets/vysi/ai_models/ocr/rapidocr/catalog.json`, schema
  `pdfexact.ocr-models.v1`, identique au bloc `ocr` du rapport, SHA-256
  `36c22b038dd9bc0cddd41dfe019c88dd1acfcfb10382f2797e456b948e7dbc55`.
- Seed : [ocr_models_rapidocr_v3_9_2.json](../scripts/data/ocr_models_rapidocr_v3_9_2.json),
  SHA-256 `a6b94ea6aef50dd8b69c989bdaa7a3c96afa0f88f1e07d2f2b889aeda6d7aa14`.
- Producteur de preuve lu, non execute :
  [provision_multilingual_cpu_models.py](../scripts/provision_multilingual_cpu_models.py),
  SHA-256 `8ad405111c16b10b368e562b928391403bc65450bb7b2ef3035bf86e80799847`.

Reconciliation en lecture seule par JSON structure et SHA-256 des fichiers :
les **11 poids presents sous `ocr/rapidocr/v3.9.2/`** ont exactement les tailles
et hashes du catalogue, du seed et du rapport. Aucune erreur de reconciliation.
Total **100857210 octets (environ 96.2 MiB)**, dont **69107701 octets** pour les
huit telechargements et **31749509 octets** pour les trois copies preexistantes.
Le total 100857210 ne designe donc pas les seuls nouveaux telechargements.

| Fichier dans `v3.9.2/` | Role | Origine conservee | Taille octets |
|---|---|---|---|
| `PP-OCRv6_det_small.onnx` | Detection | Copie hash-verifiee | 9929594 |
| `PP-OCRv6_rec_small.onnx` | Reconnaissance multi | Copie hash-verifiee | 21234383 |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | Classification | Copie hash-verifiee | 585532 |
| `cyrillic_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Cyrl | Telechargement | 8074092 |
| `korean_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Hang | Telechargement | 13488748 |
| `arabic_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Arab | Telechargement | 8023828 |
| `devanagari_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Deva | Telechargement | 7940361 |
| `th_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Thai | Telechargement | 7915294 |
| `el_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Grek | Telechargement | 7832350 |
| `ta_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Taml | Telechargement | 7909926 |
| `te_PP-OCRv5_rec_mobile.onnx` | Reconnaissance Telu | Telechargement | 7923102 |

Le catalogue conserve URLs ModelScope demandees/resolues, references RapidOCR
v3.9.2, licences declarees, langues/scripts explicites, origine copie/download
et SHA-256. Les hashes amont sont ceux du seed fourni par Lovelace : ce worker
les a rapproches des octets locaux, sans verifier de nouveau les serveurs amont.
La note devanagari signale une ambiguite des codes `ang/mah/sck` ; ne pas en
deduire une garantie ISO de couverture de ces langues.

Evidence CPU conservee : **11/11** `CPUExecutionProvider` uniquement, runtime
ONNX Runtime 1.23.2, entree `synthetic-zero-tensor`. Le producteur lu verifie
forme/type des entrees, sorties finies et contrats de sortie avant publication.
Pour les **9 reconnaisseurs**, le rapport conserve source dictionnaire
`onnx.metadata.character`, SHA-256, nombre de caracteres et classes de logits ;
les neuf contrats rapportes sont coherents (`classes = caracteres + 2`, avec
validation via le decodeur RapidOCR dans le producteur).

Ces sondes sont des executions CPU synthetiques, **pas une mesure d'accuracy**,
de direction/ordre, de segmentation ou d'extraction sur un vrai texte. Aucun
score linguistique n'en est derive ; accuracy reste inconnue/non mesuree.

Versions de distributions relues dans `.converter` par metadonnees, sans import
des moteurs : RapidOCR **3.9.2**, ONNX Runtime **1.23.2**, CTranslate2 **4.8.0**,
tokenizers **0.23.1**, conformes au rapport. L'import CT2 CPU et les types
`int8`/`int8_float32` restent ceux rapportes au checkpoint owner. Le parent
rapporte **19 tests provisioning GREEN et pip check OK** ; ce JSON n'inclut pas
leurs commandes/logs/timestamps, ces sous-lots ne sont pas rejoues ici.

Qwen : les **8 fichiers** inventories dans
`/home/raphael/Mes_Projets/vysi/ai_models/semantic_corrector/qwen2_5_0_5b_ct2_int8`
correspondent aussi aux tailles/hashes du rapport. Le statut reste
`local-user-bundle`, `unknown-no-conversion-manifest`,
`official_origin_verified=false`. Aucune provenance de conversion certifiee.

Hubble, checkpoint historique avant l'iteration 1 : deux sondes Qwen reelles,
**zero sortie acceptee**, **14.10 s** a froid et **3.79 s** ensuite, JSON invalide.
Protocole en amelioration ; **comprehension NON validee**. Chemins de logs,
entrees/sorties et attentes independantes restent a recevoir. Accuracy OCR
Pascal en cours, aucun vrai sample valide ni score recu dans ce checkpoint.

## Premiere Preuve Qwen Et Limites

Preuve persistee lue, sans reexecution :
[ct2_multilingual_cpu_20261011T121844Z_iteration1.json](../results/ct2_multilingual_cpu_20261011T121844Z_iteration1.json),
SHA-256 `9ed03fea8553ca853f9f2441a2acec33f94d72927b48c4a68e526630a26b18be`.
Runtime CT2 4.8.0 / tokenizers 0.23.1, CPU `int8`, poids locaux au SHA deja
inventorie, provenance `local-user-bundle-unverified` inchangee.

Le rapport contient **15 cas fixes**, **9 attentes satisfaites** (`matched=true`),
**13 reponses structurellement acceptees** et **2 `invalid-response`**. Une
acceptation de schema ne signifie pas une decision semantique correcte. Le
scope declare est `advisory small fixed probes; no calibrated confidence or
general quality claim` : ces petites sondes ne sont pas un corpus representatif
et ne permettent aucune extrapolation universelle.

| Cas non conforme de l'iteration 1 | Constat conserve |
|---|---|
| `ru-independent-labels` | Partition invalide : couverture/ordre/doublons, sortie rejetee |
| `ru-heading-boundary` | Partition invalide : couverture/ordre/doublons, sortie rejetee |
| `ru-label-group` | `merge-paragraph` au lieu de `preserve-lines`, malgre schema accepte |
| `zh-no-space` | `space` au lieu de `no_space` |
| `ja-no-space` | `space` au lieu de `no_space` |
| `ru-hard-break` | `space` au lieu de `preserve_break` |

Temps total rapporte **71.0135 s**, premiere sonde **14.3273 s**, pic RSS processus
**1286136 KiB**. Ce sont les mesures de ce rapport, pas de nouveaux benchmarks.
Sa politique de timeout est `cooperative-token-callback; load/prefill-not-preemptible` :
la valeur API locale 30 s ne constitue pas, a elle seule, une garantie de deadline
murale dure sur chargement/prefill. Verification ciblee du contrat apres freeze,
pas de test ou de relance effectue ici.

Cette premiere preuve reste conservee. Le checkpoint final Hubble,
[ct2_multilingual_cpu_20261011_checkpoint.md](../results/ct2_multilingual_cpu_20261011_checkpoint.md),
et [iteration2.json](../results/ct2_multilingual_cpu_20261011T122600Z_iteration2.json)
rapportent **6/15 attentes satisfaites**, quatre abstentions et cinq decisions
structurellement acceptees mais fausses ; exit 1, 86.68 s pour les probes.
SHA iteration 2 : `e5a6c5895cf67a1d718736f79ded689ff5abeaece75cde9ffddea6c457061d7b`.
Ces probes ne sont pas relances dans l'integration finale. Les guards Unicode,
CJK, hard break et labels sont revalides par tests bornes, pas par une preuve
de qualite Qwen. **Semantique qualifiee : NON ; multilingue universel : NON.**

## Inventaire Et Installation

- [x] Recevoir et rapprocher l'inventaire reel du perimetre fourni : 11 poids OCR
  et 8 fichiers du bundle Qwen, chemins/tailles/versions/hashes du rapport final.
  Ceci n'est pas l'inventaire exhaustif de tous les autres modeles du repertoire.
- [ ] Identifier les manques par role : detection, reconnaissance OCR, orientation,
  classification/layout et comprehension ; distinguer un modele de reconnaissance
  d'un modele semantique ou d'un simple detecteur de zones.
- [ ] Documenter chaque modele retenu : nom exact, editeur, source officielle,
  revision immuable, licence, langues/scripts annonces et limites connues.
- [ ] Relier la revision officielle et l'identite tokenizer/configuration
  rapportees aux chemins/hashes et preuves de comparaison effectifs ; conserver
  distinct le statut de provenance du `model.bin` CT2 preexistant.
- [ ] Recevoir la provenance de conversion CT2 : poids amont/revision/hashes,
  outil/version, commande, quantification et hash de sortie ; si irreconstituable,
  conserver explicitement le statut non certifie dans le manifeste, sans faux OK.
- [ ] Verifier le support CPU de chaque runtime/format et les dependances reellement
  installees ; ne pas supposer CUDA/GPU disponible ou necessaire.
- [x] Confirmer par metadonnees locales la presence des distributions converter
  CT2 4.8.0 / tokenizers 0.23.1 / ONNX Runtime 1.23.2 / RapidOCR 3.9.2. Import CT2
  CPU et pip check rapportes par l'owner, pas rejoues par ce worker.
- [ ] Recevoir la preuve de disponibilite de CTranslate2 dans l'environnement
  converter reel : version, interpreter/dependances, chargement effectif ; le
  runtime d'un autre projet ne prouve pas ce raccord. Checkpoint 4.8.0/import CPU
  recu ; commande/interpreter/logs de mission a recevoir avant de cocher.
- [ ] Conserver versions runtime, options CPU, threads, precision et cout memoire
  observes ; signaler toute incompatibilite ou acceleration non CPU involontaire.
- [x] Installer les 11 fichiers OCR dans le repertoire versionne demande : trois
  copies, huit telechargements. Presence et hashes recontroles ; publication
  sans remplacement explicite dans le producteur et le catalogue lus.
- [x] Fournir le manifeste OCR chemin relatif au catalogue / taille / SHA-256 /
  role/version, langues/scripts annonces, origines et dictionnaires ONNX integres.
- [x] Recevoir les preuves de provisioning des huit familles OCR v5 et du V6
  small preexistant : rapport final/catalogue/seed concordants, fichiers complets.
- [x] Verifier les tailles/hashes des 11 fichiers OCR contre catalogue et seed ;
  distinguer les huit downloads des trois copies dans l'evidence conservee.
- [x] Recevoir la preuve des 11 chargements/executions CPU OCR sur tenseurs nuls,
  CPU uniquement, depuis les fichiers installes ; pas une preuve d'accuracy.
- [x] Recevoir les neuf contrats dictionnaire ONNX / classes de logits coherents,
  sources et SHA-256 conserves ; pas une preuve de transcription correcte.
- [ ] Prouver l'inference OCR sur vrais samples independants par ecriture et le
  chargement/comportement semantique conforme de Qwen ; sondes invalides ne closent
  pas cette gate et l'installation seule ne valide pas les raccords du pipeline.
- [ ] Documenter les telechargements encore requis a l'execution et le comportement
  hors ligne ; ne pas annoncer l'autonomie locale sans essai correspondant.

## Couverture Des Ecritures

La matrice doit distinguer capacite annoncee et resultat mesure. Installer un
modele dit multilingue ne prouve pas toutes ses langues. Une source synthetique
reste identifiee comme telle ; aucun document n'est relabelle pour remplir un quota.

- [x] Cyrillic/russe : phrase synthetique independante reconnue sur CPU ; source
  et sortie dans les observations finales, ambiguite conservee. Ceci ne couvre
  pas toute la casse/ponctuation, les lettres specifiques ni tous les documents.
- [ ] Completer la couverture russe : lettres specifiques, casse, ponctuation,
  confusions avec le latin, textes courts et scans documentaires representatifs.
- [ ] Autres langues cyrilliques : lister celles couvertes et celles effectivement
  testees, sans assimiler automatiquement leur support a celui du russe.
- [x] Chinois : smokes simplifie/traditionnel distincts revalides sur CPU ; pas
  de conclusion de couverture generale de leurs caracteres/documents.
- [x] Japonais : phrase kanji/hiragana/katakana revalidee ; ambiguite declaree.
- [x] Coreen : phrase hangul revalidee sur CPU par le rec korean v5.
- [ ] Autres ecritures : etablir avec les owners la liste concrete, les priorites
  et les limites ; aucune promesse de couverture universelle implicite.
- [x] Texte mixte borne : cinq lignes RU/ZH simplifie/ZH traditionnel/JA/KO dans
  une image, ordre et texte exacts hors espaces, rec choisi par region sans hint.
- [ ] Completer le mixte dans un meme crop avec latin, cyrillique/CJK, chiffres,
  ponctuation et caracteres combines ; aucune extrapolation des lignes separees.
- [ ] Pour toute ecriture RTL retenue, verifier ordre logique, direction, ponctuation
  et caracteres combines avec une attente independante.
- [ ] Identifier explicitement vertical, courbe, scan incline et pages de faible
  qualite comme capacites a prouver ou limites, pas comme acquis par le label CJK.

Pour chaque ligne mesuree, recevoir : source et hash, page/zone, origine reelle
ou synthetique, texte attendu et sa provenance, sortie brute, modele/runtime,
commande/options, timing CPU, erreurs et criteres effectivement mesures.
Metrique non mesuree = `null`/inconnue, jamais score parfait par defaut.

## Raccord Reconnaissance Et Extraction

- [x] Identifier les points d'entree et fichiers effectivement modifies par les
  owners ; commandes dans leurs checkpoints et 660 empreintes avant/apres finales.
- [x] Raccorder chemins/options a l'API, la CLI et au script utilisateur :
  propagation testee, reconnaisseurs effectivement executes dans les smokes CPU.
- [x] Documenter le choix de modele/langue : detection effective, option explicite,
  incertitude et fallback ; aucune heuristique par nom de PDF ou par cas de test.
- [x] Verifier que le choix CPU arrive jusqu'au runtime utilise en inference.
- [x] Distinguer PDF natif et bitmap : test natif sans OCR et sonde a921 pages
  1-3 preserves ; vrai chemin acquisition d'un PDF bitmap synthetique RU+ZH teste.
  Ce perimetre ne prouve pas toutes les pages/modes ni le contrat Word-native.
- [ ] Conserver Unicode, ordre, repetitions, texte court, caracteres combines et
  ponctuation dans la sortie d'extraction, avec une attente independante.
- [ ] Conserver source/page/zone, quads/baselines/orientation disponibles, scores et
  identite du modele ; signaler explicitement les metadonnees absentes.
- [ ] Prouver que les observations OCR restent couvertes jusqu'a la sortie choisie,
  sans neutraliser les erreurs `uncovered-source` ni affaiblir le garde existant.
- [x] Documenter modele absent, langue non supportee, chargement/inference echoues :
  erreur exploitable ou fallback declare, jamais succes fabrique.

## Raccord Comprehension

- [x] Apres freeze Pascal/Hubble, verifier le defaut `experimental_local=False` :
  poids presents/root IA partage seuls ne declenchent aucun chargement local.
- [x] Apres freeze, verifier l'opt-in API/CLI/script explicite et la precedence du HTTP
  explicite, y compris quand les poids locaux et le flag experimental sont presents.
- [ ] Apres freeze, verifier `local_timeout=30` et sa limite cooperative reelle,
  sans annoncer un timeout dur sur load/prefill ni relancer un handle vivant.
- [x] Recevoir la preuve finale des guards generiques hard break / CJK / labels :
  tests bornes verts et iteration 2 conservee avec ses echecs, sans qualification.
- [x] Recevoir le contrat effectif de comprehension : provider, modele, entree,
  sortie structuree, langues, options CPU, limites et comportement d'echec.
- [ ] Distinguer reconnaissance de caracteres, analyse de layout et comprehension
  semantique ; un OCR correct ou une bbox n'est pas une preuve semantique.
- [ ] Prouver l'appel effectif du provider multilingue par le pipeline concerne.
- [ ] Prouver que le nouveau provider CT2 CPU fonctionne sans le seul raccord
  HTTP existant et sans declaration artificielle d'un provider disponible.
- [ ] Verifier chargement/inference CPU locaux si cette capacite est annoncee ;
  toute dependance reseau/endpoint distant reste declaree.
- [x] Fournir des attentes independantes pour les sorties structurees : ordre,
  lignes/paragraphes ou roles effectivement couverts par le contrat, selon les
  langues cibles. Ne pas deduire leur justesse du modele qui les produit.
- [x] Recevoir les tests cibles des heuristiques Unicode et jonctions CJK,
  incluant espaces/ponctuation et texte mixte ; distinguer ces regles locales
  d'une preuve de comprehension semantique par CT2.
- [x] Documenter provider absent, timeout, sortie invalide et repli geometrique ;
  ne pas qualifier un repli heuristique de comprehension multilingue validee.

## Verification Bornee Et Reception

- [x] Recevoir uniquement les tests/sondes cibles autorises des owners, avec commande
  exacte, timestamps, code retour, skips/warnings et logs non ecrases.
- [ ] Conserver des exemples d'entree/sortie et hashes de sources/modeles/code pour
  chaque capacite declaree verifiee ; noter les echecs et exclusions explicitement.
- [ ] Verifier les raccords dans le chemin reel reconnaissance -> comprehension /
  extraction, sans extrapoler un test unitaire de chargement en preuve de pipeline.
- [x] Etablir un tableau final installe / raccorde / teste CPU / langues verifiees /
  limites / non fait, avec liens vers les preuves de mission.
- [x] Cocher les cases de ce suivi seulement apres reception et lecture des preuves
  correspondantes ; une annonce GREEN sans perimetre n'est pas suffisante.
- [x] Laisser la refonte universelle PAUSED et son ancien suivi intact ; aucun
  benchmark global ni conversion des cinq cas anciens sans nouvelle autorisation.

## Journal De Reception

2026-10-11 : ouverture du suivi documentaire seul. Aucun resultat des nouvelles
missions recu, aucune case cochee. Aucun modele installe ou teste par ce worker.
En attente des checkpoints factuels des owners ; aucune reprise implicite.

2026-10-11, attribution et audits initiaux : Pascal confirme sur OCR routing /
options / CLI / filtres d'acquisition ; Hubble sur provider CT2 CPU / heuristiques
Unicode / jonctions CJK ; Lovelace sur poids vysi / dependance CT2 converter /
manifestes et preuves. Constats Qwen/tokenizer/provider/heuristiques et limite
de provenance `model.bin` consignes ci-dessus avec leur attribution. Aucun
resultat d'installation ou d'inference recu, aucune case cochee. Aucun run, edit
code/test ou changement de l'ancien tracker par ce worker ; refonte PAUSED.

2026-10-11, nouveau checkpoint Lovelace : CT2 4.8.0 installe `--no-deps` et import
CPU reussi rapportes, `int8`/`int8_float32` annonces ; tokenizers 0.23.1 inchange.
Huit OCR v5 en preparation et V6 small preexistant rapporte valide SHA, sources
officielles et portee consignees ci-dessus. Chemins/logs/manifeste et preuves
d'inference toujours attendus ; aucune case installation/OCR inference cochee.
Aucun run ni changement hors de ce suivi documentaire par ce worker.

2026-10-11, reception finale provisioning : rapport/seed/script/catalogue lus,
11 fichiers OCR et 8 fichiers Qwen rapproches par hashes/tailles en lecture seule.
Cases limitees a l'inventaire, aux distributions presentes, au provisioning OCR,
a l'integrite et aux contrats CPU synthetiques cochees ci-dessus. 100857210 octets
au total, dont 69107701 telecharges ; neuf contrats dictionnaire/classes lus.
19 tests GREEN/pip check OK rapportes par le parent, non rejoues. Accuracy OCR
Pascal en cours ; deux sondes Qwen Hubble, zero acceptee, JSON invalide : toutes
les cases qualite/comprehension restent ouvertes. Aucun test/inference relance,
aucun edit hors de ce fichier, aucune reprise de refonte ou ancien diagnostic.

2026-10-11, politique d'activation et preuve Qwen iteration 1 : OCR/Unicode
actifs par defaut selon decision parent ; CT2 local experimental, opt-in API/CLI
seulement, HTTP explicite prioritaire, root IA partage sans auto-activation.
Rapport iteration 1 lu : 9/15 attentes, 13 schemas acceptes, deux rejets ; six
ecarts explicites conserves. Derniere iteration/guards en cours, attendre freeze
Pascal/Hubble pour verification bornee. Aucune case de qualite semantique cochee,
aucune promesse universelle, aucun run ni modification hors de ce suivi.

## Reception Finale Bornee, 2026-10-11

GO parent apres gel des trois owners. Une seule union de **14 fichiers** : les
10 du checkpoint Hubble, `tests/extract/test_multilingual_ocr_routing.py`,
`tests/test_cli_multilingual_ocr.py`, `tests/test_reconstruct_bbox_native_options.py`
et `tests/test_provision_multilingual_cpu_models.py`. Aucun fullsuite, ancien
diagnostic, opt-in LLM reel, probe CT2, nouveau provisioning ou download reel.
Les messages download des tests provisioning concernent leurs fixtures/mocks.

Dossier inedit : `results/ia_multilingue_integration_20261011T125131Z/`.
Commandes exactes et environnement dans
[invocation.json](../results/ia_multilingue_integration_20261011T125131Z/invocation.json)
et [report.json](../results/ia_multilingue_integration_20261011T125131Z/report.json).
Variables imposees : `PDFEXACT_TEST_LOCAL_OCR=1` et
`PDFEXACT_TEXT_UNDERSTANDING_MODEL_ROOT=/tmp/pdfexact-no-local-model`.
Handle outil **99619 clos**, wrapper exit 0 apres attente des deux enfants ;
leurs codes pytest sont distincts et conserves ci-dessous. Aucun handle vivant
de ce run, aucun processus inconnu tue/relance. Les PID 4 et 1006 sont ceux du
namespace de cette execution, pas des PID hote reutilisables.

| Lot effectivement execute | UTC debut / fin | Resultat pytest | Preuves |
|---|---|---|---|
| Union unique | 12:53:14.161183 / 12:55:24.990107 | 330 passed, 0 skipped, 2 warnings, 128.68 s, exit 0 | [log](../results/ia_multilingue_integration_20261011T125131Z/union.log), [JUnit](../results/ia_multilingue_integration_20261011T125131Z/union.xml) |
| Deux node IDs couverture, lot separe | 12:55:30.897884 / 12:56:11.934215 | 2 failed, 0 skipped, 2 warnings, 39.10 s, exit 1 | [log](../results/ia_multilingue_integration_20261011T125131Z/source_coverage.log), [JUnit](../results/ia_multilingue_integration_20261011T125131Z/source_coverage.xml) |

Les timings pytest ne comprennent pas toutes les operations du wrapper/snapshots.
Warnings des deux lots : `pkg_resources` deprecie et ccache absent. Les comptes
330 et 2 sont ceux de ces lots distincts ; **ne pas additionner** les lots owners
255/101/45/43/31/19/7, qui se recouvrent et n'ont pas tous le meme snapshot.

Quatre snapshots (avant/apres chaque lot) : **660 fichiers code/production/test**,
**20 fichiers modele/catalogue**, tous inchanges entre les deux executions.
Onze payloads OCR concordent a chaque snapshot avec leur catalogue. Empreintes
agregees selon la methode documentee dans le runner archive :

- Code : `37c62d6730b8f79e5d1e18dbe4f6d479b396711142d3480bb14db514e12368fe`.
- Modeles/catalogue : `9dc773faf0aead3fadb789bd61ec462f2e74861a9039a72b5697abf5457344a3`.
- Catalogue : `36c22b038dd9bc0cddd41dfe019c88dd1acfcfb10382f2797e456b948e7dbc55`.
- Script utilisateur : `ddd08c2412a769bf3d0f3bd1e8883d393bba3a2ea255af5850816460c69a579f`.
- Ses nouveaux tests : `9292a8a91642776b7f74e769413f465c20c33f766ddd4d802fbba59c091fa552`.

Revue finale script/test : parser langues/alias et racine commune raccordes ;
root OCR et factory transmis, root layout specifique prioritaire, environnement
comprehension specifique preserve sans root explicite ; opt-in seulement avec
bool True, HTTP prioritaire. **P1 de propagation du chemin utilisateur ferme**,
sans pretendre valider ses rendus par les tests de propagation mocks.

Les sept sorties brutes sont extraites du log sans reexecution dans
[ocr_observations.json](../results/ia_multilingue_integration_20261011T125131Z/ocr_observations.json).
Les six comparaisons independantes conservent ordre de lignes et texte exacts
hors espaces. Sources PIL/phrases attendues synthetiques, pas un corpus reel.

| Smoke CPU | Secondes observees | Rec choisi | Ambiguite |
|---|---:|---|---|
| Russe | 7.2869 | cyrillic v5 | oui |
| Chinois simplifie | 5.0818 | v6 | non |
| Chinois traditionnel | 5.1437 | v6 | non |
| Japonais | 5.1132 | v6 | oui |
| Coreen | 5.0349 | korean v5 | non |
| Cinq lignes mixtes | 5.2292 | Cyrl/v6/v6/v6/Hang par region | RU oui |

Zero warning de modele dans les six sorties. Scores inter-modeles non calibres,
ambiguite non effacee. PDF bitmap synthetique sans texte natif : acquisition
reelle **4.0839 s**, Cyrl=24/Hani=10, inventaire de 11 observations ; pas une
validation DOCX/control PDF. CER, WER, pixel, fonts et accuracy generale non
mesures restent `null`, aucune certification implicite par le nombre de tests.

Les deux echecs separes ont les memes noms, assertions et six source IDs que
la fullsuite historique de 11:20 (1047 passed/2 failed). Voir
[coverage_comparison.json](../results/ia_multilingue_integration_20261011T125131Z/coverage_comparison.json).
Defaut deja observe avant la tranche multilingue, cause profonde non etablie.
Pas de xfail, bypass de garde ou source retiree pour obtenir un vert artificiel.

| Capacite | Etat de reception | Limites restantes |
|---|---|---|
| Poids OCR locaux et contrats CPU/dictionnaires | Complete dans le perimetre 11 fichiers/9 rec | Pas de qualification de toutes les langues annoncees |
| OCR automatique et options API/CLI/script | Raccordes et testes dans le perimetre borne | Auto best effort ; autres cas documentaires/meme crop a prouver |
| Preservation native a921 | Partielle : pages 1-3, SHA non latin preserve, zero OCR selon preuve Pascal | Pas de contrat natif/rendu ni autres pages valides |
| Unicode/CJK et guards deterministes | Tests bornes verts | Pas une qualification semantique du LLM |
| CT2/Qwen local | Experimental seulement, qualite NON qualifiee | 6/15 dernieres attentes ; provenance conversion inconnue |
| Couverture OCR jusqu'au package Word-native | NON validee | Deux uncovered-source persistants ; garde conserve |
| Refonte universelle / ancien corpus | PAUSED, non repris | Aucun gate global ou phase coche par ce suivi |

Restent ouverts : qualite arabe/Deva/Thai/grec/tamoul/telougou, autres langues
cyrilliques, RTL/vertical/courbe/incline, textes courts et vrais scans difficiles,
metadonnees/ordre/espaces exhaustifs, source coverage finale et qualite semantique.
Les observations de revue hors raccord script restent sans correction ni nouveau
run : branche conditionnelle `textes_visuels` avant affectation et partage du
flag langue RapidOCR/Tesseract dans la CLI. Aucun nouveau P1 de propagation
observe dans l'integration finale. Ancien tracker intact, objectif global PAUSED.
