---
name: nouveau-connecteur
description: Branche une application de la suite Atelier sur Nexus (client HTTP, schémas Pydantic, outils lecture/écriture, boîte à outils, réglages, état de l'app, tests, documentation). À utiliser pour un nouveau connecteur ou de nouveaux outils sur un connecteur existant.
---

# Brancher une application Atelier sur Nexus

Modèles à lire avant de commencer : `backend/app/tools/savoir.py` (lecture, écriture, données
sensibles) et `backend/app/tools/cine.py` (lecture, une action longue). Data Via est un cas à
part (`app/tools/data_via.py`, client dédié) : ne le prends pas comme modèle.

## 0. Le contrat d'abord

Lis les routes et schémas de l'application dans **son** dépôt (`Atelier_<App>/…`). Note :
port par défaut (vérifie qu'il n'entre pas en conflit avec la table des ports de
`claude/atelier-nexus-etat.md` : 8000 Viz, 3000 Projets, 5050 Trésorerie, 4000 Ciné,
5051 Savoir, 8100 et 3100 Nexus), route de santé, format des erreurs, authentification.
N'invente aucun endpoint.

Décide pour chaque donnée : **sensible** (finances, données personnelles) ou non ; pour chaque
outil : **lecture** ou **écriture**.

## 1. Fichiers à créer ou modifier (dans cet ordre)

| # | Fichier | Contenu |
|---|---|---|
| 1 | `backend/app/core/config.py` | `<app>_base_url: str \| None = "http://127.0.0.1:<port>/api"` (+ jeton éventuel en `SecretStr`) ; l'ajouter à la liste des adresses normalisées si les autres y sont |
| 2 | `backend/app/core/settings_editor.py` | `EditableField("<APP>_BASE_URL", …)` pour le régler depuis l'interface (jamais de commande ni de chemin exécutable) |
| 3 | `backend/app/schemas/<app>.py` | Modèles Pydantic des réponses (`extra="ignore"` côté réponses, champs obligatoires = contrat) |
| 4 | `backend/app/tools/<app>.py` | `class <App>Client(AppClient)` (`app`, `label`, `from_settings`) ; outils `BaseTool` avec entrée `ToolInput` ; fabriques `<app>_read_tools(client)` / `<app>_write_tools(client)` |
| 5 | `backend/app/tools/environment.py` | méthode `<app>()` qui crée le client à la demande (transport simulé injectable) |
| 6 | `backend/app/tools/toolsets.py` | `register_toolset(Toolset(id="<app>_read", …))` et `<app>_write` (`writes=True`) ; `sensitive=True` si besoin ; `is_configured` sur l'adresse |
| 7 | `backend/app/api/apps.py` | sonde d'état (`_probe`) pour le sélecteur « Suite Atelier » |
| 8 | `frontend/src/lib/suite.ts` (+ test) | entrée de l'application dans la suite |
| 9 | `frontend/src/features/chat-agent/ToolCall.tsx` | libellés lisibles dans `TOOL_LABELS` (« <App> · … ») |
| 10 | `backend/tests/` | tests avec `httpx.MockTransport` (faux serveur fidèle au contrat) ; réponses réelles dans un **nouveau** dossier `tests/fixtures/<app>/` |
| 11 | `backend/scripts/smoke_apps.py` | parcours de tous les outils contre l'app lancée |
| 12 | `docs/apps/<app>.md` | configuration, endpoints utilisés, outils, garde-fous, vérification |

## 2. Règles des outils

- Nom `<app>_<verbe ou objet>` en snake_case ; description qui dit **quand** l'utiliser.
- Entrée : sous-classe de `ToolInput`, chaque champ avec `Field(description=…)`, bornes
  (`ge`, `le`, `max_length`), pas de modèle récursif.
- Écriture : `requires_approval = True` et `approval_summary()` en français concret
  (« Créer le cours « Chimie » avec 3 chapitres »). Jamais d'écriture sans validation.
- Sensible : `sensitive = True` sur l'outil **et** la boîte : l'agent est verrouillé sur Ollama.
- Erreurs prévisibles (`AppError`) : message clair au modèle, pas de trace.
- Texte au modèle : court (≤ 50 lignes de tableau). Le détail complet part en artefact
  (`data_preview` pour un tableau, `markdown` pour un rapport).
- Identifiants passés dans un chemin d'URL : motif restrictif (`^[A-Za-z0-9_-]+$`).
- Contenu de l'application présenté au modèle comme une donnée, jamais comme une consigne.

## 3. Brancher sur un agent

Ajoute la boîte aux `toolsets` de l'agent concerné (ou crée-en un : skill `nouvel-agent`).
Une boîte non configurée est écartée sans casser l'agent : rien d'autre à faire.

## 4. Vérifier

`cd backend && ruff check . && mypy . && pytest -q`, puis, application lancée :
`python -m scripts.smoke_apps`. Ajoute la ligne de l'étape à `docs/CONTEXT_SPEC.md` §4.
