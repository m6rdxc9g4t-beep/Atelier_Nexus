# Réglages depuis l'interface (Étape 11)

La roue dentée de l'en-tête ouvre les **Réglages** : validation des actions, clé Claude, modèles, moteur par défaut et de secours, adresses
des applications Atelier, dossier des instantanés de Tab, accès GitHub. Les changements s'appliquent **tout de suite**
(rechargement à chaud du routeur LLM et des connecteurs), puis une **vérification** affiche l'état de chaque moteur et
de chaque application (« Clé API refusée par Anthropic (401) », « Ollama injoignable », « 3 projet(s) »…).

## API

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/api/settings` | Champs modifiables : libellé, groupe, type, aide, valeur effective, `source` (`fichier`, `environnement`, `défaut`), fichier `.env` utilisé. **Jamais la valeur d'un secret** : `configured` et `hint` (« …abcd »). |
| `PUT` | `/api/settings` | `{"values": {"CLE": "valeur" \| "" \| null}}` ; `""` ou `null` retire la clé du fichier (retour au défaut). 422 `invalid_settings` avec `fields` par clé. |

Code : `backend/app/core/settings_editor.py` (liste blanche, lecture / écriture du `.env`, validation),
`backend/app/api/settings.py` (routes, rechargement), `frontend/src/features/settings/` (fenêtre, brouillon testé).

## Validation des actions (`APPROVAL_MODE`)

Premier groupe des Réglages, en boutons radio :

| Valeur | Libellé | Effet |
|---|---|---|
| `every_step` (**défaut**) | Chaque action (recommandé) | Toute action d'agent (appel d'outil, lecture comprise, délégation) et toute étape de workflow v1 / v2, y compris lancée par un déclencheur, attend « Autoriser » / « Refuser ». |
| `writes_only` | Seulement les écritures | Comportement antérieur : seules les actions `requires_approval` (agents, v1) et les étapes `write` / `destructive` (v2) attendent. |

- C'est un **choix de l'utilisateur** : le défaut `every_step` s'applique aussi aux installations existantes (aucune valeur dans
  le `.env` = `every_step`). Aucune autorisation permanente, aucun « tout autoriser » : chaque action se valide une par une.
- Agents ([`agents.md`](agents.md) §3), délégation (le sous-agent n'a alors aucun outil), workflows ([`workflows.md`](workflows.md)),
  déclencheurs (arrêt à l'étape 1, [`declencheurs-api.md`](declencheurs-api.md) §0).
- Pris en compte à la requête suivante. Une exécution de workflow garde le mode de son lancement, sauf passage à `every_step`
  (le plus strict l'emporte).
- Les évaluations (`scripts.evals`, applications simulées) tournent en `writes_only` pour suivre le raisonnement du modèle.

## Règles

- **Liste blanche** (`FIELDS`) : APPROVAL_MODE, CLAUDE_MODE, CLAUDE_CLI_MODEL, ANTHROPIC_API_KEY, ANTHROPIC_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL,
  LLM_DEFAULT_PROVIDER, LLM_FALLBACK_PROVIDER, DATA_VIA_BASE_URL, PROJETS_BASE_URL, PROJETS_IMPORT_TOKEN,
  TRESORERIE_BASE_URL, CINE_BASE_URL, SAVOIR_BASE_URL, TAB_EXPORTS_DIR, CUISINE_SUPABASE_URL, CUISINE_SUPABASE_ANON_KEY,
  CUISINE_EMAIL, CUISINE_PASSWORD, CUISINE_REFRESH_TOKEN (groupe « Atelier Cuisine »), GITHUB_TOKEN, GITHUB_REPO,
  GITHUB_ALLOWED_REPOS. Tout le reste est refusé — en particulier **`TAB_MCP_COMMAND`** (commande exécutée) et
  `DATABASE_URL`, ainsi que `CLAUDE_CLI_PATH`, qui restent dans le fichier.
- Validation : adresses `http(s)://`, choix fermés, Atelier Cuisine (adresse HTTPS du projet, clé publique seulement :
  `service_role` / `sb_secret_…` refusées, e-mail valide — [`apps/cuisine.md`](apps/cuisine.md)), pas de retour à la ligne (aucune injection d'une autre clé), puis
  contrôle par le modèle `Settings`. Une valeur refusée ne modifie pas le fichier.
- Écriture : commentaires, ordre et autres clés préservés ; clé existante remplacée sur place, nouvelle clé ajoutée sous
  un en-tête dédié ; écriture atomique ; droits **600**.
- Une variable d'environnement du processus l'emporte sur le `.env` : le champ est affiché, verrouillé, avec la raison.
- **Origine contrôlée** : refus (403) d'un appel venant d'une autre origine que l'interface de Nexus (origines CORS
  déclarées ou même origine dans l'application de bureau). Le corps JSON impose de toute façon une requête de contrôle
  CORS aux navigateurs.
- Sans clé Claude ni Claude Code, le moteur par défaut devient Ollama (au lieu d'une erreur à chaque message).

Fichier utilisé : `backend/.env` en développement, `~/Library/Application Support/Atelier Nexus/.env` dans
l'application de bureau.

## Réglages du fichier `.env` seulement

Hors de la liste blanche de l'interface (ils changent le comportement de fond, pas une connexion) :

| Clé | Défaut | Rôle |
|---|---|---|
| `TIMEZONE` | `Europe/Paris` | Fuseau IANA des horaires quotidiens des déclencheurs (heure d'été / d'hiver par `zoneinfo`). Un nom inconnu est refusé au démarrage. |
| `TRIGGERS_ENABLED` | `true` | Tâche de fond des déclencheurs de workflows ; `false` la coupe (les tests la coupent). |
| `TRIGGERS_POLL_SECONDS` | `15` | Intervalle entre deux passages (1 à 3600 s) : lecture des événements, horaires échus, rafales. |

Ces trois valeurs sont lues au démarrage du backend ([`workflows.md`](workflows.md#déclencheurs--étape-20)).
