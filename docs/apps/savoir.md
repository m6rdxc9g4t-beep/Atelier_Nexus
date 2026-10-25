# Connecteur Atelier Savoir (Étape 7)

Atelier Savoir range des cours en chapitres (texte collé ou importé) et en cartes de révision, révisées en
répétition espacée (SM-2 simplifié, trois notes). API Flask + SQLite, sans authentification, sous `/api`.

Code : `backend/app/tools/savoir.py`, schémas `backend/app/schemas/savoir.py`. Contrat lu dans `atelier-savoir`
(`routes/api.py`, `models.py`) puis vérifié contre l'application lancée sur une base de démonstration.

## Configuration et port

Savoir écoute par défaut sur **5050, comme Atelier Trésorerie**. On le lance donc sur 5051 :

```bash
cd atelier-savoir && ATELIER_PORT=5051 python app.py
```

| Variable | Défaut | Rôle |
|---|---|---|
| `SAVOIR_BASE_URL` | `http://127.0.0.1:5051/api` | Vide = connecteur désactivé |

`python desktop.py` prend 5050 s'il est libre, sinon un port au hasard : dans ce cas, renseignez le port réel.
Savoir n'écoute que sur `127.0.0.1` : un backend Nexus en Docker ne le joint pas (lancer le backend sur la machine).

Identité : il n'y a pas de route `/health`. `GET /api/stats` sert de contrôle ; ses clés `new_cards` et
`reviewed_today` sont propres à Savoir. Si Trésorerie répond à la place, l'erreur le dit.

## Données et format

- Dates « AAAA-MM-JJ HH:MM:SS » en UTC sans fuseau : converties en UTC explicite.
- Une carte enregistrée a `card_type` ; une carte proposée (corps de `POST /flashcards`) a `type`.
- Les erreurs 405 et 500 de Flask sont des pages HTML : le client ne lit le JSON que s'il y en a.

## Outils (tous `sensitive` : modèle local imposé)

| Boîte | Outil | Rôle |
|---|---|---|
| `savoir_read` | `savoir_overview` | Compteurs (cours, chapitres, cartes, maîtrisées, à réviser, révisions du jour) et liste des cours |
| `savoir_read` | `savoir_course` | Un cours et ses chapitres |
| `savoir_read` | `savoir_chapter` | Texte d'un chapitre, par extraits (`offset`, `max_chars` : 4 000 par défaut, ≤ 12 000) |
| `savoir_read` | `savoir_flashcards` | Cartes filtrées par cours, chapitre, statut, type : questions seules par défaut (`with_answers` pour les réponses), 30 par défaut, ≤ 100 |
| `savoir_read` | `savoir_due_cards` | Séance du jour (`mode` dues ou toutes), 10 cartes par défaut, ≤ 30 |
| `savoir_write` | `savoir_create_course` | Crée un cours : **validation** |
| `savoir_write` | `savoir_add_chapter` | Ajoute un chapitre : texte (`content`) **ou** fichier joint à la conversation (`file` : .md, .txt, .pdf, envoyé tel quel à Savoir qui en extrait le texte) : **validation** |
| `savoir_write` | `savoir_add_flashcards` | Enregistre jusqu'à 15 cartes par appel (origine « ia ») : **validation** |
| `savoir_write` | `savoir_record_reviews` | Enregistre les notes d'une interrogation (a_revoir, correct, maitrise) en **une seule validation** |

## Modèle local : tailles et validations

Le Tuteur tourne sur Ollama : sorties et entrées restent à la portée d'un petit modèle et de sa fenêtre de contexte
(`OLLAMA_NUM_CTX`, [`settings.md`](../settings.md)).

- Lecture bornée : extraits de chapitre de 4 000 caractères, liste de cartes sans les réponses (les questions
  suffisent pour éviter les doublons), séance de 30 cartes au plus (`savoir_due_cards` donne les réponses, pour
  corriger).
- Écriture par lots : 15 cartes au plus par appel (un appel tronqué donnerait un JSON invalide). Un long document
  n'est jamais recopié par le modèle : l'utilisateur le joint au chat et `savoir_add_chapter` l'importe par son nom
  (`env.conversation_files()` : seulement les fichiers cités par la conversation ; hors conversation, message clair).
  `content` et `file` sont exclusifs ; celui qu'un petit modèle envoie vide (`"content": ""`) compte comme absent.
  Une extension visible autre que .md, .markdown, .txt ou .pdf est refusée dès les paramètres, avant la carte de
  validation ; un nom sans extension est contrôlé une fois le fichier retrouvé, sans rien envoyer à Savoir.
- La carte de validation n'affiche que le résumé : il dit tout ce qui sera écrit. Cartes : chaque question et le début
  de sa réponse (« 1. « Énoncer le second principe » → « L'entropie… » ») ; notes : chaque carte et sa note
  (« #12 → Correct, #15 → À revoir ») ; chapitre : le titre, le cours, la taille et les 200 premiers caractères, ou le
  nom du fichier importé ; cours : titre, matière et début de la description.

## Confidentialité

Règle d'Atelier Savoir : « 100 % local par défaut ». Les cours et notes sont des données personnelles : les deux
boîtes sont `sensitive`, l'agent est verrouillé sur Ollama, sans repli vers Claude, et l'orchestrateur ne peut pas
le solliciter s'il tourne sur Claude.

Nexus n'appelle pas `POST /api/chapters/{id}/generate` : selon ses réglages, Savoir peut y utiliser Claude.
L'agent rédige lui-même les cartes avec le modèle local, puis les enregistre.

## Agent

**Tuteur** (`tuteur`, catégorie Apprentissage, 100 % local) : `core`, `savoir_read`, `savoir_write`.
Interrogation une question à la fois, correction, puis enregistrement groupé des notes.
