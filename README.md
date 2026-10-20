# Atelier Nexus

Hub d'agents IA (Data Analyst / Power BI, Dev, …) pour la suite **Atelier**, avec routage LLM hybride Claude ↔ Ollama.
Spécification : [`docs/CONTEXT_SPEC.md`](docs/CONTEXT_SPEC.md) · Règles de dev : [`CLAUDE.md`](CLAUDE.md) · Agents & routeur LLM : [`docs/llm-router-and-agents.md`](docs/llm-router-and-agents.md)

## Démarrage rapide (tout en Docker)

```bash
cp .env.example .env                  # identifiants Postgres + URL publique API
cp backend/.env.example backend/.env  # clés Anthropic, Data Via, GitHub…
docker-compose up -d
docker-compose exec ollama ollama pull llama3.1:8b   # premier lancement uniquement
```

| Service  | URL                                  |
|----------|--------------------------------------|
| Frontend | http://localhost:3000                |
| API      | http://localhost:8000/docs           |
| Ollama   | http://localhost:11434               |

## Développement local (hot reload)

Lancer uniquement l'infrastructure en Docker, puis front et back en local :

```bash
docker-compose up -d postgres redis ollama

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload        # tests : pytest · typage : mypy . · lint : ruff check .

# Frontend
cd frontend
cp .env.example .env.local
npm install
npm run dev                      # lint : npm run lint · types : npm run typecheck
```

## Ajouter un composant Shadcn UI

`components.json` est configuré (style new-york, base neutral, Tailwind v4). Les composants s'installent dans `src/components/ui/` :

```bash
cd frontend && npx shadcn@latest add button card input
```

## Workflow Git

Jamais de push direct sur `main` : une branche `feat/…` ou `fix/…` par évolution, PR obligatoire, la CI (`.github/workflows/ci.yml`) doit être verte.
