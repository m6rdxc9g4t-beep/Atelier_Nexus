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
| `savoir_read` | `savoir_chapter` | Texte d'un chapitre, par extraits (`offset`, `max_chars` ≤ 20 000) |
| `savoir_read` | `savoir_flashcards` | Cartes filtrées par cours, chapitre, statut, type |
| `savoir_read` | `savoir_due_cards` | Séance du jour (`mode` dues ou toutes) |
| `savoir_write` | `savoir_create_course` | Crée un cours : **validation** |
| `savoir_write` | `savoir_add_chapter` | Ajoute un chapitre (texte) : **validation** |
| `savoir_write` | `savoir_add_flashcards` | Enregistre jusqu'à 60 cartes (origine « ia ») : **validation** |
| `savoir_write` | `savoir_record_reviews` | Enregistre les notes d'une interrogation (a_revoir, correct, maitrise) en **une seule validation** |

## Confidentialité

Règle d'Atelier Savoir : « 100 % local par défaut ». Les cours et notes sont des données personnelles : les deux
boîtes sont `sensitive`, l'agent est verrouillé sur Ollama, sans repli vers Claude, et l'orchestrateur ne peut pas
le solliciter s'il tourne sur Claude.

Nexus n'appelle pas `POST /api/chapters/{id}/generate` : selon ses réglages, Savoir peut y utiliser Claude.
L'agent rédige lui-même les cartes avec le modèle local, puis les enregistre.

## Agent

**Tuteur** (`tuteur`, catégorie Apprentissage, 100 % local) : `core`, `savoir_read`, `savoir_write`.
Interrogation une question à la fois, correction, puis enregistrement groupé des notes.
