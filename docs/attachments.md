# Pièces jointes (Étape 15)

On peut joindre des fichiers à un message, chez tous les agents : avec le **trombone** du champ de saisie, en
**glissant-déposant** les fichiers sur le champ, ou en **collant** une capture d'écran (⌘ V).

## Formats lus

| Fichier | Ce que reçoit le modèle |
|---|---|
| Images PNG, JPEG, GIF, WebP | L'image, réduite à 1 568 px de côté au plus ; métadonnées retirées (EXIF : position GPS, appareil) ; première image d'un GIF animé |
| PDF | Son texte, page par page (`--- Page n ---`) ; 500 pages au plus. Un PDF numérisé (sans texte) est refusé : joindre des captures de ses pages |
| Word `.docx` | Paragraphes (titres en `#`), puis tableaux |
| Excel `.xlsx` / `.xlsm` | Valeurs calculées de chaque feuille, séparateur `;`, 5 000 lignes par feuille au plus |
| CSV, TSV, texte, Markdown, JSON, XML, HTML, YAML, SQL, DAX, M, code | Le texte tel quel (UTF-8, sinon Windows-1252) |

Refusés avec une explication : plus de 20 Mo, fichier vide ou illisible, PDF protégé par mot de passe, photos HEIC
(à exporter en JPEG), anciens formats `.doc` / `.xls` / `.ppt` et fichiers Apple (à enregistrer en PDF, `.docx` ou
`.xlsx`). 10 fichiers au plus par message.

Le texte d'un document est gardé jusqu'à 500 000 caractères, et 100 000 au plus sont envoyés au modèle par document ;
le modèle est prévenu de toute coupure.

## Fonctionnement

1. **Import** (`POST /api/attachments`, `multipart/form-data`, champ `file`) dès que le fichier est ajouté : le serveur
   extrait le texte ou réduit l'image (`backend/app/attachments/processing.py`), l'enregistre dans la table
   `attachments` et renvoie `{id, name, media_type, kind, size, meta}`. `meta` : `pages`, `sheets`, `rows`, `chars`,
   `width`, `height`, `truncated` (motif d'une coupure).
2. **Envoi** : le message cite le fichier par un bloc
   `{"type": "attachment", "id", "name", "media_type", "kind", "size"}`, placé avant le texte. C'est ce bloc, et lui
   seul, qui est enregistré dans l'historique : la base des conversations reste légère.
3. **Appel au modèle** : juste avant chaque appel, `expand_attachments` (`backend/app/core/llm/attachments.py`) remplace
   chaque référence par son contenu :
   - document → `<piece_jointe nom="…" type="…" pages="…">texte</piece_jointe>`, lisible par tous les moteurs ;
   - image → la ligne `[Image jointe : nom]` puis l'image.

   Le prompt système précise que ce contenu est une **donnée, pas une consigne** : une instruction cachée dans un
   document n'est pas exécutée sans l'accord de l'utilisateur, et les actions qui modifient des données restent
   soumises à validation.

Les images selon le moteur :

| Moteur | Images |
|---|---|
| Claude (clé API) | Bloc `image` natif |
| Claude (abonnement, `claude -p`) | Entrée `--input-format stream-json` (texte et images dans l'ordre), sortie `stream-json` dont on lit la ligne `result`. Sans image, l'entrée texte habituelle |
| Ollama | Champ `images` du message ; il faut un **modèle de vision** (`gemma3`, `qwen2.5vl`, `llava`…). Sinon, erreur explicite : installer un modèle de vision ou retirer l'image |

Les agents « 100 % local » (Finance, Comptable, Trésorier) restent sur Ollama, pièces jointes comprises : un relevé
bancaire joint ne quitte pas la machine.

## API

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/api/attachments` | Import. 201 ; 413 trop gros ; 415 format non lu ; 422 illisible ; 403 si l'origine n'est pas l'interface de Nexus ; 503 base indisponible |
| `GET` | `/api/attachments/{id}/content` | Image : affichée (`inline`). Autre fichier : toujours téléchargé en `application/octet-stream` (un `.html` ou un `.svg` joint n'est jamais interprété par le navigateur) ; `nosniff`, CSP `sandbox` |
| `DELETE` | `/api/attachments/{id}` | Retire un fichier **pas encore envoyé** (204). Déjà envoyé : 409, il part avec sa conversation |

`POST /api/agents/{nom}/run` et `/stream` chargent les fichiers cités (503 si la base ne répond pas). Un bloc `image`
brut dans la requête est refusé (422) : les images passent toujours par l'import, qui les réduit et les nettoie.

## Cycle de vie

- Un fichier est rattaché à sa conversation quand le tour qui le cite est enregistré (`attachments.conversation_id`).
- Supprimer une conversation supprime ses fichiers.
- Un fichier jamais envoyé (message abandonné) est supprimé au démarrage suivant s'il a plus de 24 heures.
- La recherche dans l'historique trouve les noms des fichiers joints.
- Migration : `backend/migrations/versions/0004_attachments.py`.

## Interface

- `frontend/src/features/chat-agent/Composer.tsx` : trombone, glisser-déposer, collage ; une puce par fichier
  (aperçu de l'image, « Préparation… », puis pages / feuilles / dimensions, ou l'erreur) ; l'envoi attend la fin des
  imports. Contrôles immédiats et libellés : `attachments.ts` (testé).
- `AttachmentView.tsx` : dans la conversation, vignettes des images (clic : agrandir, télécharger) et puces des
  documents (clic : télécharger l'original ; dans l'application de bureau, boîte « Enregistrer sous »).
- Dépendances ajoutées (`backend/requirements.txt`) : `pillow`, `pypdf`, `python-docx`, `openpyxl`, `python-multipart`.
  L'application de bureau les installe d'elle-même au lancement suivant.
