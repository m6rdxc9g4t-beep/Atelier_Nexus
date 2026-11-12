# Claude par l'abonnement (Claude Code) — Étape 12

Pour qui a un **forfait Claude** (Pro, Max…) sans clé API : Nexus passe par le programme `claude` (Claude Code) de la
machine, en mode non interactif (`claude -p`), comme Atelier Viz et Atelier Savoir. La consommation compte dans les
limites de l'abonnement ; aucune clé n'est nécessaire.

## Mise en route

1. Installer Claude Code (https://claude.com/claude-code).
2. Dans le Terminal : `claude`, puis se connecter avec son compte Claude (une seule fois).
3. Dans Nexus : **Réglages → Accès à Claude** = « Automatique » (défaut) ou « Abonnement Claude (Claude Code) ».
   La vérification affiche « Claude : moteur par défaut, sonnet » quand tout va bien.

| Réglage | Défaut | Rôle |
|---|---|---|
| `CLAUDE_MODE` | `auto` | `auto` : la clé API si elle est renseignée, sinon Claude Code s'il est installé ; `cli` : toujours Claude Code ; `api` : toujours la clé |
| `CLAUDE_CLI_MODEL` | `sonnet` | `sonnet`, `opus` ou `haiku` |
| `CLAUDE_CLI_PATH` | auto | Chemin de `claude` s'il n'est pas trouvé (`~/.local/bin`, Homebrew, `/usr/local/bin`…). Fichier `.env` uniquement. |
| `CLAUDE_CLI_TIMEOUT` | `300` | Délai d'un tour (s) |

## Fonctionnement

Code : `backend/app/core/llm/providers/claude_code_provider.py` (`ClaudeCodeProvider`, nom de provider `anthropic` :
l'interface affiche toujours « Claude »). Choisi par `LLMRouter.from_settings`.

- **Outils** : le mode `-p` n'expose pas d'appels d'outils utilisables par Nexus. Chaque tour renvoie un objet JSON
  validé par schéma (`--json-schema`) : `text` et `tool_calls` (`name` parmi les outils de l'agent, `arguments` en
  JSON). Nexus exécute les outils lui-même — **validations, verrou local et garde-fous inchangés** — puis renvoie les
  résultats au tour suivant. La boucle d'agent (`BaseAgent`) ne voit aucune différence avec l'API.
- **Conversation** : transmise sur l'entrée standard, sous forme de texte (`## Utilisateur`, `## Assistant`,
  `## Assistant → appel de l'outil …`, `## Résultat de …`) ; résultats d'outils tronqués à 40 000 caractères.
- **Sûreté** : environnement en liste blanche (SUITE.md §5.3 : `HOME`, `USER`, `LOGNAME`, `PATH` avec le dossier de
  l'exécutable en tête, `SHELL`, `LANG`, `LC_*`, `TMPDIR`, `TZ`, `CLAUDE_CONFIG_DIR`, plus
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` ; sous Windows, §9.6 : `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `USERNAME`,
  `APPDATA`, `LOCALAPPDATA`, `SystemRoot`, `SystemDrive`, `windir`, `ComSpec`, `PATHEXT`, `TEMP`, `TMP`, `ProgramData`) :
  jamais `ANTHROPIC_*` (une clé serait facturée à l'usage) ni réglage de Nexus. Sous Windows, `claude.exe` (aussi
  cherché dans `%USERPROFILE%\.local\bin`), ou `claude.cmd` de npm résolu en `node.exe …\cli.js` (sinon refusé) :
  jamais `cmd.exe`. PATH sans entrée relative ni `node_modules/.bin`. Rien du compte Claude Code de l'utilisateur
  (`--safe-mode` : ni `CLAUDE.md`, ni mémoire, ni hooks, ni extensions, ni MCP), aucun outil de Claude Code
  (`--tools ""`), pas de MCP (`--strict-mcp-config`), pas de commandes (`--disable-slash-commands`), pas de session
  conservée (`--no-session-persistence`), allers-retours bornés (`--max-turns 2` : la sortie structurée, puis la fin du
  tour), dossier de travail vide et temporaire. Un tour arrêté (bouton « Arrêter ») ou en délai dépassé arrête le
  processus `claude`.
- **Erreurs** : non connecté → « tapez claude dans le Terminal… » ; limite de l'abonnement → erreur transitoire, qui
  permet le **repli vers Ollama** si `LLM_FALLBACK_PROVIDER=ollama` ; délai dépassé → transitoire aussi.
- **État** (`/api/llm/providers`) : `claude auth status`, gardé 60 s en mémoire (SUITE.md §5.3 ; `?refresh=true` le relance, au
  plus toutes les 10 s) ; modèles proposés : sonnet, opus, haiku.
- **Streaming** : la réponse structurée arrive d'un bloc (pas de texte partiel), tour par tour.

Les agents « 100 % local » (Finance, Comptable, Tuteur) restent sur Ollama : l'abonnement est un service en ligne.

## Sur un serveur : le jeton du forfait (`CLAUDE_OAUTH_TOKEN`)

Décision de l'utilisateur : « je veux que Claude forfait cli soit actif car c'est personnel ça sera mon forfait
Claude ». Sur le VPS, il n'y a pas de session `claude` connectée : la même CLI isolée s'authentifie avec le **jeton du
forfait**, celui que `claude setup-token` affiche (`sk-ant-oat01-…`, valable un an). Contrat commun aux applications de
la suite.

1. Sur son ordinateur : `claude setup-token` (Claude Code connecté à son compte Pro ou Max), copier le jeton.
2. Sur le serveur : fournir le jeton au processus de Nexus par la **variable d'environnement** `CLAUDE_OAUTH_TOKEN`
   (Docker Compose : `environment:`), installer le programme `claude` dans l'image, redémarrer Nexus.
3. Réglages → Moteurs d'IA affiche « Claude : … sonnet (forfait, par jeton) ».

| | Sans jeton (inchangé) | Jeton renseigné |
|---|---|---|
| Moteur Claude | `CLAUDE_MODE` : clé API, ou session `claude` de l'ordinateur | **la CLI isolée, toujours** : prioritaire sur `CLAUDE_MODE` et sur `ANTHROPIC_API_KEY` |
| Drapeaux de la CLI | ceux de « Sûreté » ci-dessus | **exactement les mêmes** (un test compare les arguments au caractère près) |
| Environnement de la CLI | liste blanche | liste blanche **+ `CLAUDE_CODE_OAUTH_TOKEN`**, et `HOME` / `CLAUDE_CONFIG_DIR` remplacés par un dossier privé |
| Disponibilité | exécutable + `claude auth status` | exécutable + jeton (`claude auth status` n'est pas lancé : il n'y a pas de session à lire) |
| `access` de `/api/llm/providers` | `api` ou `cli` | `token` |

- **Où va le jeton** : lu **une fois** au démarrage (`main.py` → `app/core/llm/claude_token.py`), puis **retiré de
  l'environnement du processus** : aucun autre sous-processus (serveur MCP de Tab, application ouverte…) n'en hérite.
  Il n'est transmis qu'à la CLI Claude, dans son environnement — jamais en argument. Il n'est pas un réglage : ni lu
  dans le `.env` (fichier réécrit par l'écran Réglages), ni dans `Settings`, ni modifiable ou visible depuis
  l'interface ; il n'apparaît dans aucune réponse d'API, erreur ou journal (masqué dans tout message, comme tout ce qui
  a la forme `sk-ant-…`), et n'est écrit dans aucun fichier. Limite : le noyau garde l'environnement de départ du
  processus (`/proc/<pid>/environ`, `docker inspect`) — c'est le cas de toute variable d'environnement.
- **Dossier privé** : `claude-forfait/` (droits 700) dans le dossier de données de Nexus, celui du `.env` (conteneur du
  kit : `/data/nexus/claude-forfait`) ; `HOME` = ce dossier, `CLAUDE_CONFIG_DIR` = son `.claude`. La CLI n'y trouve
  aucune session, mémoire ni réglage d'utilisateur. Sous Windows, les variables du profil (§9.6) restent celles du
  système : ce mode vise le serveur.
- **`ANTHROPIC_API_KEY`** n'est jamais transmis à la CLI (liste blanche), jeton ou non. Jeton fourni mais programme
  `claude` absent : Claude est « non configuré », avec la raison — **jamais** de repli silencieux sur la clé API
  (facturée à l'usage, contre le choix de l'utilisateur) ; le moteur par défaut devient Ollama.
- **Exécutable** : `CLAUDE_CLI_PATH` (réglage, variable d'environnement ou `.env`), puis la variable `CLAUDE_PATH`, le
  `PATH` (entrées absolues, sans `node_modules/.bin`), `~/.local/bin/claude`, `~/.claude/local/claude`,
  `/opt/homebrew/bin`, `/usr/local/bin`, `~/.npm-global/bin`. Un `claude` installé par npm a besoin de `node` : le
  dossier de l'exécutable, puis `/usr/local/bin`, sont en tête du `PATH` de la CLI.
- **Erreurs** : jeton refusé ou expiré → « refaites claude setup-token… et mettez à jour le jeton du serveur
  (CLAUDE_OAUTH_TOKEN), puis redémarrez Nexus » ; limite du forfait → erreur transitoire qui reprend le message de la
  CLI (repli vers Ollama si `LLM_FALLBACK_PROVIDER=ollama`) ; programme absent → « absent de ce serveur ». La limite
  est reconnue d'abord, et un refus par ses mots (`authentication_error`, `OAuth`, `expired`…) ou par un statut 401
  annoncé comme tel (« API Error: 401 ») : les chiffres « 401 » d'un nombre (conversation trop longue de 240117 jetons,
  heure de remise à zéro du forfait) ne font pas refaire le jeton pour rien.
- **Usage personnel** : le jeton est celui du forfait d'une personne ; ne pas ouvrir ce Nexus à d'autres. Les
  **limites du forfait sont partagées** entre toutes les applications de la suite qui s'en servent (et avec Claude Code
  sur l'ordinateur) : un workflow gourmand ici peut épuiser le quota des autres.
- **Garde-fous inchangés** : agents « 100 % local » verrouillés sur Ollama (la CLI n'est pas lancée), validation de
  chaque action. Nexus n'a pas de mode « Hors ligne » global (à la différence de Viz, Projets ou Convert) : Claude
  n'est utilisé que s'il est configuré et choisi.
- Non vérifié avec la vraie CLI (les tests ne la lancent jamais) : le comportement de `claude -p` dans un dossier de
  configuration vide avec `CLAUDE_CODE_OAUTH_TOKEN` est à contrôler au premier déploiement.

## Vérifier

```bash
cd backend && pytest tests/test_claude_code.py tests/test_claude_token.py   # faux `claude` lancé en sous-processus
```

Essai réel (20/10/2026, `claude` 2.1, modèle haiku) : l'Assistant appelle `current_datetime` puis répond (2 tours,
10 s) ; le Chef de projet appelle `projets_list_projects` puis deux `projets_dashboard` dans le même tour et rend son
point d'avancement (3 tours, 17 s).
