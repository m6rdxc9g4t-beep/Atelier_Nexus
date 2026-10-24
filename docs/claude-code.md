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
  Claude Code ne donne au modèle qu'un outil, `StructuredOutput` (imposé par `--json-schema`) : les consignes
  présentent les outils de Nexus comme des **actions à nommer** dans `tool_calls`, jamais comme des outils à
  appeler. Présentées comme des « outils », elles étaient appelées directement (« No such tool available ») et
  l'agent pouvait abandonner la tâche (constaté avec Claude Code 2.1.310).
- **Sortie** : toujours `--output-format stream-json --verbose`. C'est la seule sortie qui montre le texte que le
  modèle écrit parfois **hors** de l'objet structuré, avant de n'y mettre qu'une phrase : ce texte est ajouté à la
  réponse quand l'objet ne le reprend pas (jamais en double). Ligne `result` finale : même forme que
  `--output-format json`.
- **Conversation** : transmise sur l'entrée standard, sous forme de texte (`## Utilisateur`, `## Assistant`,
  `## Assistant → appel de l'outil …`, `## Résultat de …`) ; résultats d'outils tronqués à 40 000 caractères.
- **Sûreté** : environnement en liste blanche (SUITE.md §5.3 : `HOME`, `USER`, `LOGNAME`, `PATH` avec le dossier de
  l'exécutable en tête, `SHELL`, `LANG`, `LC_*`, `TMPDIR`, `TZ`, `CLAUDE_CONFIG_DIR`, plus
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` ; sous Windows, §9.6 : `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `USERNAME`,
  `APPDATA`, `LOCALAPPDATA`, `SystemRoot`, `SystemDrive`, `windir`, `ComSpec`, `PATHEXT`, `TEMP`, `TMP`, `ProgramData`) :
  jamais `ANTHROPIC_*` (une clé serait facturée à l'usage) ni réglage de Nexus. Sous Windows, `claude.exe` (aussi
  cherché dans `%USERPROFILE%\.local\bin`), ou `claude.cmd` de npm résolu en `node.exe …\cli.js` (sinon refusé) :
  jamais `cmd.exe`. PATH sans entrée relative ni `node_modules/.bin`. Aucun outil de Claude Code (`--tools ""`), pas de MCP
  (`--strict-mcp-config`), pas de commandes (`--disable-slash-commands`), pas de session conservée
  (`--no-session-persistence`), dossier de travail vide et temporaire.
- **Erreurs** : non connecté → « tapez claude dans le Terminal… » ; limite de l'abonnement → erreur transitoire, qui
  permet le **repli vers Ollama** si `LLM_FALLBACK_PROVIDER=ollama` ; délai dépassé → transitoire aussi.
- **État** (`/api/llm/providers`) : `claude auth status` ; modèles proposés : sonnet, opus, haiku.
- **Streaming** : la réponse structurée arrive d'un bloc (pas de texte partiel), tour par tour.

Les agents « 100 % local » (Finance, Comptable, Tuteur) restent sur Ollama : l'abonnement est un service en ligne.

## Vérifier

```bash
cd backend && pytest tests/test_claude_code.py   # faux `claude` lancé en sous-processus
```

Essai réel (20/10/2026, `claude` 2.1, modèle haiku) : l'Assistant appelle `current_datetime` puis répond (2 tours,
10 s) ; le Chef de projet appelle `projets_list_projects` puis deux `projets_dashboard` dans le même tour et rend son
point d'avancement (3 tours, 17 s).
