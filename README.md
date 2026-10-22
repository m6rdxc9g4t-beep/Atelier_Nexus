# Atelier Nexus

Hub d'agents IA pour la suite **Atelier** : 17 agents experts (données, tableur, projets, développement, finance, apprentissage, médiathèque, cuisine, marketing, métiers), agents personnalisés créés depuis l'interface et orchestrateur, avec routage LLM hybride Claude ↔ Ollama, validation humaine des actions et données financières traitées 100 % en local.
Spécification : [`docs/CONTEXT_SPEC.md`](docs/CONTEXT_SPEC.md) · Règles de dev : [`CLAUDE.md`](CLAUDE.md) · Agents & routeur LLM : [`docs/llm-router-and-agents.md`](docs/llm-router-and-agents.md) · Connecteur Data Via : [`docs/apps/data-via.md`](docs/apps/data-via.md) · Agents : [`docs/agents.md`](docs/agents.md) · Interface : [`docs/frontend.md`](docs/frontend.md) · Historique : [`docs/conversations.md`](docs/conversations.md) · Connecteurs Tab, Ciné, Savoir, Cuisine : [`docs/apps/`](docs/apps/)

## Application de bureau (macOS)

```bash
./scripts/macos/build_app.sh   # « Atelier Nexus.app » dans ~/Applications + raccourci sur le Bureau
```

L'app est un lanceur branché sur ce dépôt : le script ne se lance qu'une fois (ou si le dépôt change de place).
**Après un `git pull`, relancez simplement l'app** : elle se met à jour toute seule (écran « Mise à jour… » : dépendances
si elles ont changé, recompilation de l'interface ; en cas d'échec, ouverture possible avec la version précédente).
Jamais de `git pull` automatique, aucune donnée touchée. Abonnement Claude (via Claude Code, sans clé API —
[`docs/claude-code.md`](docs/claude-code.md)) ou clé Claude, modèles et adresses des apps : roue dentée **Réglages** de l'interface ([`docs/settings.md`](docs/settings.md)). Données dans
`~/Library/Application Support/Atelier Nexus/`. Détails : [`docs/desktop.md`](docs/desktop.md).

## Validation de chaque action

Par défaut (`APPROVAL_MODE=every_step`, Réglages → « Validation des actions » → **Chaque action**), toute action d'un agent
— lecture comprise — et toute étape d'un workflow, même lancé par un horaire ou un événement, attend votre « Autoriser » :
vous voyez à chaque étape ce qui va s'exécuter (et le résultat de l'étape précédente) avant de décider. « Seulement les
écritures » rétablit l'ancien comportement. Détails : [`docs/settings.md`](docs/settings.md), [`docs/agents.md`](docs/agents.md) §3.

## Atelier Cuisine (app en ligne)

Atelier Cuisine apparaît dans le menu **Suite Atelier** (« en ligne », jamais sondé ; l'app Mac s'ouvre si elle est
installée) et sert de connecteur aux agents, **en lecture seule** : agent **Cuisine** (stock et ce qui presse, planning
des repas, liste de courses) et agent **Finance** (budget du mois et tickets, modèle local imposé). Réglages →
« Atelier Cuisine » : adresse du projet Supabase, clé publique (jamais la clé `service_role`), e-mail + mot de passe du
foyer ou jeton de rafraîchissement. Détails : [`docs/apps/cuisine.md`](docs/apps/cuisine.md).

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

## Charte graphique (suite Atelier)

Charte « néon monochrome » commune à la suite : chaque application est **entièrement dans sa couleur signature** — **orange #E8590C** pour Nexus. Fond, barre latérale, cartes, bordures, textes secondaires, halos et grille de fond dérivent tous de cette couleur (mélanges et transparences) ; pas de couleur de structure commune.

- `frontend/src/styles/brand/atelier-brand.css` (+ police Nunito et sa licence OFL) est une **copie exacte** du fichier de marque d'Atelier Projets (`design-system/brand/`) : ne pas l'éditer ici. Il définit les jetons `--atelier-*` (`bg`, `sidebar`, `surface(-2|-3)`, `field`, `text`, `muted`, `ink`, `border(-soft)`, `line`, `signature(-soft|-faint)`, `glow(-strong)`, `focus`, `backdrop`, `chart-1..3`) pour le clair et le sombre.
- `data-atelier-app="nexus"` sur `<html>` (`layout.tsx`) pose la couleur ; les variables Shadcn de `globals.css` sont branchées sur ces jetons, et tous les écrans (en-tête, barre des agents, chat, panneau Artefacts, historique, réglages, éditeur d'agent, menus) reçoivent trait et halo néon par les composants de `src/components/ui/`. Chaque tuile du sélecteur « Suite Atelier » prend la couleur de SON application.
- Choix du thème **Clair / Sombre / Système** (`src/components/theme/`) : dans l'en-tête de l'écran principal, et dans **Réglages › Apparence** (petits écrans). Préférence dans `localStorage` (`atelier-nexus-theme`, défaut Système, qui suit `prefers-color-scheme` ; l'ancienne clé `atelier-nexus:theme` est reprise une fois), appliquée avant le premier affichage par un script inline ; sombre = `.dark` + `data-theme="dark"`, clair = `data-theme="light"`. Bouton principal : plein en clair, contour néon en sombre.
- Application de bureau : la fenêtre s'ouvre sur le fond du kit (`#fbf3f2` clair, `#120c0d` sombre, selon l'apparence de macOS), sans éclair blanc.
- Utilitaires Tailwind : `shadow-glow`, `shadow-glow-strong`, `shadow-signature-glow`, `shadow-focus`, `text-shadow-glow`, `bg-signature-soft`, `bg-signature-faint`, `bg-atelier-surface(-2|-3)`, `text-atelier-ink`, `text-atelier-muted`, `border-atelier-border(-soft)`, `border-atelier-line`, `fill-atelier-chart-1..3`.
- Les couleurs qui portent un sens (`--chart-*` multi-séries, `--destructive`) ne changent pas.

## Workflow Git

Jamais de push direct sur `main` : une branche `feat/…` ou `fix/…` par évolution, PR obligatoire, la CI (`.github/workflows/ci.yml`) doit être verte.
