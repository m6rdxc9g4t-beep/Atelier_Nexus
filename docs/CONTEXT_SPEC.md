# Atelier Nexus — Spécification de contexte

> Statut : **Étape 20 (déclencheurs de workflows)**. Les sections marquées `À COMPLÉTER` attendent les décisions produit.

## 1. Vision
Hub web permettant d'utiliser des agents IA spécialisés (Data Analyst / Power BI, Dev, …) sur la suite d'applications **Atelier** (dont *Data Via*), avec un routage LLM hybride : API Anthropic (Claude) ou modèle local via Ollama.

## 2. Architecture

```
┌──────────────┐   HTTP/SSE   ┌──────────────────────┐
│  frontend    │ ───────────▶ │  backend (FastAPI)   │
│  Next.js     │              │  ├─ agents/          │
│  Tailwind    │              │  ├─ core/llm/router  │──▶ Anthropic API
│  Shadcn UI   │              │  └─ tools/           │──▶ Ollama (local)
└──────────────┘              └─────┬───────┬────────┘
                                    │       │
                           ┌────────▼─┐  ┌──▼────┐      ┌───────────┐
                           │ Postgres │  │ Redis │      │ Data Via  │
                           │ pgvector │  └───────┘      │ (API)     │
                           └──────────┘                 └───────────┘
```

| Service    | Image / Stack                        | Port hôte | Rôle                                   |
|------------|--------------------------------------|-----------|----------------------------------------|
| frontend   | Next.js (App Router), Node 22        | 3100      | UI : Chat Agent, Studio Dev, Dashboard |
| backend    | FastAPI, Python 3.12                 | 8100      | Orchestration agents, outils, routeur  |
| postgres   | `pgvector/pgvector:pg17`             | 5432      | Données applicatives + embeddings      |
| redis      | `redis:7-alpine`                     | 6379      | Cache, sessions, file de tâches        |
| ollama     | `ollama/ollama`                      | 11435     | LLM locaux (11434 = Ollama natif)      |

## 3. Principes structurants (voir `CLAUDE.md`)
- Agents : héritent de `BaseAgent`, outils déclarés au format commun Anthropic/Ollama.
- LLM : tout appel passe par `LLMRouter` (`backend/app/core/llm/router.py`).
- Data Via : point d'entrée unique `backend/app/tools/data_via.py`, schémas Pydantic stricts.
- Front : composants `src/components/ui/` uniquement ; livrables d'agents → `useArtifactStore` (panneau droit).

## 4. Feuille de route
| Étape | Contenu | Statut |
|-------|---------|--------|
| 1 | Arborescence, docker-compose, config de base front/back | ✅ |
| 2 | `LLMRouter` (Anthropic + Ollama) + `BaseAgent` → [`llm-router-and-agents.md`](llm-router-and-agents.md) | ✅ |
| 3 | Connecteur Data Via (API d'Atelier Viz) + schémas Pydantic → [`apps/data-via.md`](apps/data-via.md) | ✅ |
| 4 | UI : chat en streaming + panneau Artefacts (`useArtifactStore`) → [`frontend.md`](frontend.md) | ✅ |
| 5 | Plateforme multi-agents : 13 experts, agents créés depuis l'interface, orchestrateur, validations, verrou local, connecteurs Projets / Trésorerie / GitHub → [`agents.md`](agents.md) | ✅ |
| 6 | Historique : conversations et artefacts enregistrés en base, réouverture, renommage, suppression → [`conversations.md`](conversations.md) | ✅ |
| 7 | Connecteurs Atelier Tab (instantanés DataFlow), Ciné, Savoir ; agents Tableur, Ciné-club, Tuteur (100 % local) → [`apps/tab.md`](apps/tab.md), [`apps/cine.md`](apps/cine.md), [`apps/savoir.md`](apps/savoir.md) | ✅ |
| 8 | Écriture dans Atelier Tab par son serveur MCP (cellules, lignes, colonnes, tables), avec validation → [`apps/tab.md`](apps/tab.md) | ✅ |
| 9 | Application de bureau macOS « Atelier Nexus.app » : fenêtre native, installation de Python au premier lancement, données dans Application Support → [`desktop.md`](desktop.md) | ✅ |
| 10 | Pont Atelier Tab → Atelier Projets : aperçu puis import idempotent d'une table en éléments → [`apps/tab.md`](apps/tab.md) | ✅ |
| 11 | Réglages dans l'interface (clé Claude, modèles, apps, GitHub), rechargement à chaud et vérification → [`settings.md`](settings.md) | ✅ |
| 12 | Claude par l'abonnement (Claude Code, `claude -p`) sans clé API, outils des agents conservés → [`claude-code.md`](claude-code.md) | ✅ |
| 13 | Recherche dans l'historique (titres, messages, artefacts ; un agent ou tous), sans accents ni casse → [`conversations.md`](conversations.md#recherche-étape-13) | ✅ |
| 14 | Atelier Cuisine (app en ligne, Supabase) : menu Suite « en ligne », connecteur en lecture seule (stock, planning, courses ; budget `sensitive`), agent Cuisine → [`apps/cuisine.md`](apps/cuisine.md) | ✅ |
| 15 | Pièces jointes dans les conversations : images, PDF, Word, Excel, CSV, texte, code (trombone, glisser-déposer, capture collée), pour Claude et Ollama → [`attachments.md`](attachments.md) | ✅ |
| 16 | Outils Claude Code du dépôt : sous-agents (relecteur, testeur, bâtisseur de connecteurs), skills (nouvel agent, nouveau connecteur, vérifier), hooks de garde (git, fichiers protégés, formatage) → [`developpement.md`](developpement.md) | ✅ |
| 17 | Évaluations des agents : 22 cas réels, applications simulées ou réelles, contrôles de l'état final (outils, artefacts, validations, chiffres sourcés), juge facultatif, rapport comparé → [`evaluations.md`](evaluations.md) | ✅ |
| 18 | Workflows rejouables : un tour d'agent réussi enregistré (« Enregistrer en workflow »), paramètres `{{nom}}`, relancé sans modèle avec validation des écritures ; migration 0005, version 0.11.0 → [`workflows.md`](workflows.md) | ✅ |
| 19 | Workflows v2 multi-apps : graphe d'étapes outils Nexus et actions des manifestes `atelier-node/1` (Viz, Projets, Tab), gabarits typés entre étapes, exécutions persistées pas à pas avec validation de chaque écriture sur l'entrée résolue, idempotence `nexus:<run>:<step>`, carte et événements de la suite ; migration 0006 → [`workflows.md`](workflows.md#workflows-v2-multi-applications--étape-19), [`apps/noeuds.md`](apps/noeuds.md) | ✅ |
| 20 | Déclencheurs de workflows : horaires (intervalle, quotidien, fuseau `TIMEZONE`, heure d'été / d'hiver, une seule exécution rattrapée) et événements des applications (curseur par app, filtres, `{{event.…}}`, debounce, `gap`), garde-fous de débit, écritures toujours en attente de validation, boîte « À valider » ; tâche de fond dans le `lifespan` ; migration 0007 → [`workflows.md`](workflows.md#déclencheurs--étape-20), [`declencheurs-api.md`](declencheurs-api.md) | ✅ |
| 21 | Validation de chaque action (choix de l'utilisateur) : `APPROVAL_MODE` = `every_step` (défaut) \| `writes_only` dans Réglages ; tout appel d'outil d'agent, toute délégation (sous-agent alors sans outil) et toute étape de workflow v1 / v2, déclencheurs compris, attend « Autoriser » ; cartes « Lecture », résultat de l'étape précédente au-dessus de la validation suivante → [`settings.md`](settings.md), [`agents.md`](agents.md) | ✅ |

## 5. À COMPLÉTER
- Authentification (utilisateurs, SSO éventuel).
- Data Via en écriture (enregistrer une mesure dans le modèle de Viz, actualiser un jeu) : quand, et avec quelle confirmation utilisateur ?
- Ajouter Atelier Nexus au contrat de suite (`docs/SUITE.md` d'Atelier Viz / Tab / Projets) : ports 3100 / 8100, sélecteur de suite.
- Modèle Ollama recommandé en production (défaut actuel : `llama3.1:8b`) et activation ou non du repli automatique (`LLM_FALLBACK_PROVIDER`).
- Port d'Atelier Savoir : le faire passer à 5051 par défaut dans son dépôt (`docs/SUITE.md`), pour ne plus entrer en conflit avec Trésorerie.
- Exposer Projets, Trésorerie et Savoir à un backend Nexus conteneurisé (voir `agents.md` §6).
- Atelier Cuisine en écriture (ajouter à la liste de courses, planifier un repas) : outils avec validation (`requires_approval`).
- Embeddings (pgvector) : recherche dans l'historique et les documents de la suite.
