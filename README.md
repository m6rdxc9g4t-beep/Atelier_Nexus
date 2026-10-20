# Atelier Nexus

Hub d'agents IA pour la suite **Atelier** : 16 agents experts (données, tableur, projets, développement, finance, apprentissage, médiathèque, marketing, métiers), agents personnalisés créés depuis l'interface et orchestrateur, avec routage LLM hybride Claude ↔ Ollama, validation humaine des actions et données financières traitées 100 % en local.
Spécification : [`docs/CONTEXT_SPEC.md`](docs/CONTEXT_SPEC.md) · Règles de dev : [`CLAUDE.md`](CLAUDE.md) · Agents & routeur LLM : [`docs/llm-router-and-agents.md`](docs/llm-router-and-agents.md) · Connecteur Data Via : [`docs/apps/data-via.md`](docs/apps/data-via.md) · Agents : [`docs/agents.md`](docs/agents.md) · Interface : [`docs/frontend.md`](docs/frontend.md) · Historique : [`docs/conversations.md`](docs/conversations.md) · Connecteurs Tab, Ciné, Savoir : [`docs/apps/`](docs/apps/)

## Ports (cohabitation avec la suite Atelier)

| Service | Adresse | Remarque |
|---|---|---|
| Nexus — interface | http://localhost:3100 | 3000 = API d'Atelier Projets |
| Nexus — API | http://localhost:8100/docs | 8000 = Atelier Viz (Data Via) |
| Ollama (conteneur) | http://localhost:11435 | 11434 reste libre pour un Ollama natif |
| PostgreSQL / Redis | 127.0.0.1:5432 / 6379 | |

## Démarrage rapide (tout en Docker)

```bash
cp .env.example .env                  # identifiants Postgres + URL publique API
cp backend/.env.example backend/.env  # clés Anthropic, Data Via, GitHub…
docker-compose up -d
docker-compose exec ollama ollama pull llama3.1:8b   # premier lancement uniquement
```

Pour que les agents accèdent à **Data Via**, lancer Atelier Viz sur la machine (port 8000) : le conteneur backend
la joint via `host.docker.internal`. État du connecteur : http://localhost:8100/api/data-via/status

## Développement local (hot reload)

Lancer uniquement l'infrastructure en Docker, puis front et back en local :

```bash
docker-compose up -d postgres redis

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8100   # tests : pytest · typage : mypy . · lint : ruff check .

# Frontend
cd frontend
cp .env.example .env.local
npm install
npm run dev                             # http://localhost:3100 · lint : npm run lint · types : npm run typecheck
```

## Ajouter un composant Shadcn UI

`components.json` est configuré (style new-york, base neutral, Tailwind v4). Les composants s'installent dans `src/components/ui/` :

```bash
cd frontend && npx shadcn@latest add button card input
```

## Workflow Git

Jamais de push direct sur `main` : une branche `feat/…` ou `fix/…` par évolution, PR obligatoire, la CI (`.github/workflows/ci.yml`) doit être verte.
