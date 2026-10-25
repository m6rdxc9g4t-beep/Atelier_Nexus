# Connecteur Atelier Ciné (Étape 7)

Atelier Ciné est une médiathèque personnelle (films, séries) qui indexe des dossiers d'un NAS ou d'un PC.
API Express, sans authentification, sous `/api`.

Code : `backend/app/tools/cine.py`, schémas `backend/app/schemas/cine.py`. Contrat lu dans `atelier_cine`
(`backend/src/routes`, `services/scanner.js`) puis vérifié contre l'application lancée avec sa médiathèque
d'exemple (`npm run sample -w backend`).

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `CINE_BASE_URL` | `http://127.0.0.1:4000/api` | Mode serveur (`npm run dev:api`). App Mac : `http://127.0.0.1:47321/api` (ou le port choisi au lancement si 47321 est pris). |

Ciné écoute sur toutes les interfaces en mode serveur : un backend Nexus en Docker le joint par
`host.docker.internal:4000`.

Identité : `GET /api/health` doit renvoyer `mediaDirsSource` (champ propre à Ciné), sinon l'erreur indique que
le service n'est pas Atelier Ciné.

## Outils

| Boîte | Outil | Rôle |
|---|---|---|
| `cine` | `cine_library` | Catalogue filtré (type, mot du titre, genre, qualité 4K / HDR / 1080p / 720p, années), trié (récents, titre, année), avec la colonne genres |
| `cine` | `cine_title` | Fiche d'un film (qualité, durée, sous-titres, technique) ou d'une série (épisodes par saison, épisodes manquants) |
| `cine` | `cine_library_report` | Erreurs d'analyse, épisodes manquants, doublons probables, films sans année ou sans sous-titres, répartition des qualités |
| `cine` | `cine_ai_summary` | Synopsis, genres et tags proposés par l'Ollama de Ciné (rien n'est enregistré ; jusqu'à 90 s) |
| `cine_write` | `cine_scan` | Relance l'analyse des dossiers et réécrit l'index : **validation**, jusqu'à 10 min |

On n'expose pas la gestion des profils ni le réglage des dossiers (`PUT /api/settings`).

Genres : Ciné n'en renseigne souvent aucun (médiathèque d'exemple : aucun). `cine_library` affiche ceux qu'il connaît
(3 au plus par titre, « ∅ » sinon) ; le filtre `genre` (accents et majuscules ignorés) est **ignoré, et la réponse le
dit**, quand aucun titre n'a de genre, plutôt que de renvoyer une liste vide trompeuse. Quand seuls certains titres en
ont, la réponse compte ceux qui, sans genre renseigné, sont écartés par le filtre (« 5 titre(s) sans genre renseigné
écarté(s) ») : le modèle ne conclut pas qu'aucun autre titre ne convient. Le Ciné-club déduit alors un genre du titre
en le signalant ; `cine_ai_summary` (lent) en propose pour un titre précis.

L'artefact « Médiathèque Atelier Ciné » n'est publié que si la liste dépasse les 50 lignes montrées au modèle.

## Confidentialité

Chaque titre porte le **chemin absolu** de son fichier. Les outils ne transmettent jamais ces chemins au modèle :
seul le nom du fichier (fiche d'un film) ou du dossier racine (erreurs d'analyse) apparaît. Le catalogue lui-même
(titres de films) n'est pas traité comme sensible : l'agent peut tourner sur Claude.

## Agent

**Ciné-club** (`cineclub`, catégorie Maison) : `core`, `cine`, `cine_write`.
