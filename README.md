# Atelier Nexus

Hub d'agents IA pour la suite **Atelier** : 17 agents experts (données, tableur, projets, développement, finance, apprentissage, médiathèque, cuisine, marketing, métiers), agents personnalisés créés depuis l'interface et orchestrateur, avec routage LLM hybride Claude ↔ Ollama, validation humaine des actions et données financières traitées 100 % en local.
Spécification : [`docs/CONTEXT_SPEC.md`](docs/CONTEXT_SPEC.md) · Règles de dev : [`CLAUDE.md`](CLAUDE.md) · Agents & routeur LLM : [`docs/llm-router-and-agents.md`](docs/llm-router-and-agents.md) · Connecteur Data Via : [`docs/apps/data-via.md`](docs/apps/data-via.md) · Agents : [`docs/agents.md`](docs/agents.md) · Interface : [`docs/frontend.md`](docs/frontend.md) · Historique : [`docs/conversations.md`](docs/conversations.md) · Connecteurs Tab, Ciné, Savoir, Cuisine : [`docs/apps/`](docs/apps/) · Exemples de la suite : [`docs/exemples-suite.md`](docs/exemples-suite.md)

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

## Installer sur Windows

Windows 10 (21H2+) ou 11, sans droits d'administrateur. **Prérequis** (le script vérifie et donne la commande
`winget` de ce qui manque) : Git (`winget install --id Git.Git -e`), Node.js 22.12+ (`winget install --id OpenJS.NodeJS.LTS -e`),
Python 3.12+ (`winget install --id Python.Python.3.13 -e`) ; WebView2 est déjà là sur Windows 11 (sinon
`winget install --id Microsoft.EdgeWebView2Runtime -e`, ou l'app s'ouvre dans le navigateur). Depuis le dépôt :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1              # menu Démarrer (dossier « Atelier ») + Bureau
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -SansBureau  # sans raccourci sur le Bureau
```

La première mise à jour (environnement Python, `npm ci`, compilation) se fait dans le terminal, puis « Atelier Nexus »
s'ouvre depuis le menu Démarrer, sans console. **Mise à jour : `git pull`, puis rouvrez l'app** (écran « Mise à jour… »).
Relancer la commande répare l'installation ; `-Desinstaller` retire lanceur, raccourcis et enregistrement, jamais les
données (`%APPDATA%\Atelier Nexus\` : `.env`, `nexus.db`). Journaux : `%LOCALAPPDATA%\Atelier Nexus\Logs\`.
Détails : [`docs/desktop.md`](docs/desktop.md#windows).

## Claude avec votre forfait sur un serveur (`CLAUDE_OAUTH_TOKEN`)

Sur un serveur (VPS), il n'y a pas de session `claude` connectée. Pour que le moteur Claude passe quand même par le
**forfait** (Pro, Max) plutôt que par une clé API facturée à l'usage :

1. sur votre ordinateur, `claude setup-token` affiche un jeton `sk-ant-oat01-…` valable un an ;
2. sur le serveur, fournissez-le au backend par la variable d'environnement **`CLAUDE_OAUTH_TOKEN`** et installez le
   programme `claude` (Claude Code) dans l'image (`CLAUDE_CLI_PATH` s'il n'est pas trouvé seul), puis redémarrez.

Jeton renseigné : Claude = la CLI Claude Code isolée (mêmes drapeaux qu'en local : aucun outil, aucun MCP, aucune
session, dossier vide, conversation sur l'entrée standard), **prioritaire** sur `CLAUDE_MODE` et sur
`ANTHROPIC_API_KEY`. Le jeton est lu une fois au démarrage, retiré de l'environnement du processus, transmis à la CLI
seule ; il n'est jamais renvoyé, journalisé ni écrit. La CLI travaille dans un dossier privé, `claude-forfait/`, à côté
du `.env`. Sans cette variable, rien ne change. Agents « 100 % local » : toujours Ollama.

- **Usage personnel** : c'est le forfait d'une personne. Ne partagez pas l'accès à ce Nexus.
- **Limites partagées** : le quota du forfait est commun à toutes les applications de la suite qui l'utilisent, et à
  Claude Code sur votre ordinateur. Limite atteinte : message clair, et repli sur Ollama si `LLM_FALLBACK_PROVIDER=ollama`.
- Jeton expiré ou refusé (au bout d'un an, ou révoqué) : refaites `claude setup-token` et mettez à jour la variable.

Détail et sûreté : [`docs/claude-code.md`](docs/claude-code.md).

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

Charte v2 « Linear » commune à la suite (`Atelier_Deploy/DESIGN.md`, SUITE.md §1.7) : une **structure crème en clair et
bleu nuit en sombre** (7 nov. 2026, comme le portfolio), identique dans toutes les apps, en clair et en sombre, dense et plate (traits de 1 px, pas de halo, pas de grille ni de
lueur de fond). La signature de Nexus, **orange `#c84f00`**, ne sert qu'à l'accent : bouton principal plein, sélection,
focus, liens, et l'icône de l'app.

- `frontend/src/styles/brand/` (`atelier-brand.css`, `atelier-theme.js`, police **Inter** et sa licence) et
  `frontend/src/styles/atelier-ds/` sont des **copies exactes** d'Atelier Projets (`design-system/`) : ne pas les éditer
  ici. Jetons `--atelier-*` (`bg`, `sidebar`, `surface(-2|-3)`, `field`, `text`, `muted`, `faint`, `ink`, `border(-soft)`,
  `line`, `signature(-soft|-faint|-hover)`, `focus`, `warn`, `down`, `chart-1..3`) pour le clair et le sombre.
- `data-atelier-app="nexus"` sur `<html>` (`layout.tsx`) pose l'accent ; `globals.css` branche les variables Shadcn et le
  thème Tailwind (couleurs, police, rayons 5 / 7 / 10 px, texte 13 px sur ordinateur, 14 px sur téléphone) sur ces jetons
  (détail dans [`docs/frontend.md`](docs/frontend.md) §2). Chaque application citée (sélecteur « Suite Atelier », puces,
  nœuds et modèles de workflows, carte) est reconnue à **son icône** carrée dans SA couleur, rien d'autre n'est teinté.
- **Cartes de chiffres** (KPI) : `.atelier-kpi` de la marque commune (carte plate, trait de 1 px, coins de 12 px
  `--atelier-radius-xl`, chiffre en tabulaire), par exemple « À valider » sur l'accueil.
- Coquille à la Linear : barre latérale de 232 px (marque « Atelier Nexus » + icône Lucide `workflow`, navigation, agents,
  état des apps, thème, réglages ; en tiroir sur petit écran), barre haute de 44 px par vue, listes denses.
- **États** : seuls les états anormaux sont en couleur (échec en rouge, validation attendue en ambre) ; une étape réussie
  ou en cours et une app qui répond restent neutres.
- Choix du thème **Système / Clair / Sombre** (`src/components/theme/`) : en bas de la barre latérale, et dans
  **Réglages › Apparence**. Préférence **commune à la suite** (`atelier-theme.js` : cookie `atelier_theme` sur le VPS,
  sinon `localStorage["atelier:theme"]`), appliquée avant le premier affichage ; sombre = `.dark` + `data-theme="dark"`,
  clair = `data-theme="light"`. Les anciennes clés de Nexus sont reprises une fois.
- Application de bureau : la fenêtre s'ouvre sur le fond de la charte (crème `#f8f4ec` en clair, bleu nuit `#0b1220` en sombre, selon
  l'apparence de macOS), sans éclair blanc ; icônes (`scripts/macos/`, `scripts/windows/`, favicon) = l'icône carrée.
- Les couleurs qui portent un sens (`--chart-*` multi-séries, statuts, nature lecture / écriture) ne changent pas ;
  utilisées comme texte, elles passent par les encres lisibles `text-warning-ink`, `text-destructive-ink`.

## Workflow Git

Jamais de push direct sur `main` : une branche `feat/…` ou `fix/…` par évolution, PR obligatoire, la CI (`.github/workflows/ci.yml`) doit être verte.
