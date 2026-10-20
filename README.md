# Atelier Nexus

Hub d'agents IA (Data Analyst / Power BI, Dev, …) pour la suite **Atelier**, avec routage LLM hybride Claude ↔ Ollama.
Spécification : [`docs/CONTEXT_SPEC.md`](docs/CONTEXT_SPEC.md) · Règles de dev : [`CLAUDE.md`](CLAUDE.md)

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

## Charte graphique (suite Atelier)

Charte « néon monochrome » commune à la suite : chaque application est **entièrement dans sa couleur signature** — **orange #E8590C** pour Nexus. Fond, barre latérale, cartes, bordures, textes secondaires, halos et grille de fond dérivent tous de cette couleur (mélanges et transparences) ; pas de couleur de structure commune.

- `frontend/src/styles/brand/atelier-brand.css` (+ police Nunito et sa licence OFL) est une **copie exacte** du fichier de marque d'Atelier Projets (`design-system/brand/`) : ne pas l'éditer ici. Il définit les jetons `--atelier-*` (`bg`, `sidebar`, `surface(-2|-3)`, `field`, `text`, `muted`, `ink`, `border(-soft)`, `line`, `signature(-soft|-faint)`, `glow(-strong)`, `focus`, `backdrop`, `chart-1..3`) pour le clair et le sombre.
- `data-atelier-app="nexus"` sur `<html>` (`layout.tsx`) pose la couleur ; les variables Shadcn de `globals.css` sont branchées sur ces jetons, et les composants Shadcn (`data-slot`) reçoivent trait et halo néon.
- L'app s'affiche en sombre (`.dark` + `data-theme="dark"`) ; le clair est prêt (retirer ces marqueurs). Bouton principal : plein en clair, contour néon en sombre.
- Utilitaires Tailwind : `shadow-glow`, `shadow-glow-strong`, `shadow-signature-glow`, `shadow-focus`, `text-shadow-glow`, `bg-signature-soft`, `bg-signature-faint`, `bg-atelier-surface(-2|-3)`, `text-atelier-ink`, `text-atelier-muted`, `border-atelier-border(-soft)`, `border-atelier-line`, `fill-atelier-chart-1..3`.
- Les couleurs qui portent un sens (`--chart-*` multi-séries, `--destructive`) ne changent pas.

## Workflow Git

Jamais de push direct sur `main` : une branche `feat/…` ou `fix/…` par évolution, PR obligatoire, la CI (`.github/workflows/ci.yml`) doit être verte.
