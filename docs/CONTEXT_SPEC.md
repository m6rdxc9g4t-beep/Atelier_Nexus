# Atelier Nexus — Spécification de contexte

> Statut : **Étape 6 (historique des conversations)**. Les sections marquées `À COMPLÉTER` attendent les décisions produit.

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

## 5. À COMPLÉTER
- Authentification (utilisateurs, SSO éventuel).
- Data Via en écriture (enregistrer une mesure dans le modèle de Viz, actualiser un jeu) : quand, et avec quelle confirmation utilisateur ?
- Ajouter Atelier Nexus au contrat de suite (`docs/SUITE.md` d'Atelier Viz / Tab / Projets) : ports 3100 / 8100, sélecteur de suite.
- Modèle Ollama recommandé en production (défaut actuel : `llama3.1:8b`) et activation ou non du repli automatique (`LLM_FALLBACK_PROVIDER`).
- Connecteurs Atelier Tab, Ciné, Savoir (contrats à lire dans leurs dépôts) et agents associés.
- Exposer Projets et Trésorerie à un backend Nexus conteneurisé (voir `agents.md` §6).
- Embeddings (pgvector) : recherche dans l'historique et les documents de la suite.
