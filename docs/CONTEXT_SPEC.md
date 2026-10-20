# Atelier Nexus — Spécification de contexte

> Statut : **squelette initial (Étape 1)**. Les sections marquées `À COMPLÉTER` attendent les décisions produit.

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
| frontend   | Next.js (App Router), Node 22        | 3000      | UI : Chat Agent, Studio Dev, Dashboard |
| backend    | FastAPI, Python 3.12                 | 8000      | Orchestration agents, outils, routeur  |
| postgres   | `pgvector/pgvector:pg17`             | 5432      | Données applicatives + embeddings      |
| redis      | `redis:7-alpine`                     | 6379      | Cache, sessions, file de tâches        |
| ollama     | `ollama/ollama`                      | 11434     | LLM locaux                             |

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
| 3 | Connecteur Data Via + schémas Pydantic | À faire |
| 4 | UI : layout Chat + panneau Artefacts (`useArtifactStore`) | À faire |
| 5 | Agent Data Analyst / Power BI (DAX Generator) | À faire |

## 5. À COMPLÉTER
- Authentification (utilisateurs, SSO éventuel).
- Contrat d'API de Data Via (→ `docs/apps/data-via.md`).
- Modèle Ollama recommandé en production (défaut actuel : `llama3.1:8b`) et activation ou non du repli automatique (`LLM_FALLBACK_PROVIDER`).
- Persistance des conversations : aujourd'hui le client renvoie l'historique à chaque tour (`new_messages`).
- Schéma de base (conversations, artefacts, embeddings).
