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
  OLLAMA_NUM_CTX, LLM_DEFAULT_PROVIDER, LLM_FALLBACK_PROVIDER, DATA_VIA_BASE_URL, PROJETS_BASE_URL, PROJETS_IMPORT_TOKEN,
  TRESORERIE_BASE_URL, CINE_BASE_URL, SAVOIR_BASE_URL, CONVERT_BASE_URL, TAB_EXPORTS_DIR, CUISINE_SUPABASE_URL, CUISINE_SUPABASE_ANON_KEY,
  CUISINE_EMAIL, CUISINE_PASSWORD, CUISINE_REFRESH_TOKEN (groupe « Atelier Cuisine »), GITHUB_TOKEN, GITHUB_REPO,
  GITHUB_ALLOWED_REPOS. Tout le reste est refusé — en particulier **`TAB_MCP_COMMAND`** (commande exécutée) et
  `DATABASE_URL`, ainsi que `CLAUDE_CLI_PATH`, qui restent dans le fichier.
- Validation : adresses `http(s)://`, choix fermés, Atelier Cuisine (adresse HTTPS du projet, clé publique seulement :
  `service_role` / `sb_secret_…` refusées, e-mail valide — [`apps/cuisine.md`](apps/cuisine.md)), pas de retour à la ligne (aucune injection d'une autre clé), puis
  contrôle par le modèle `Settings`. Une valeur refusée ne modifie pas le fichier.
- Atelier Convert (`CONVERT_BASE_URL`, défaut `http://127.0.0.1:8010/api`, vide = désactivé) : nœud des workflows de la
  suite, adresse de bouclage seulement (`127.0.0.1`, `localhost`, `::1`) — une autre adresse est enregistrée mais le nœud la
  refuse (« injoignable »). Le délai de ses actions, `CONVERT_TIMEOUT` (120 s, une conversion avec OCR est longue), reste
  dans le fichier. Mêmes variables que l'extension Agent_DatAnalyst ([`extensions.md`](extensions.md)). « Vérifier » relit
  son manifeste (« 6 action(s), 4 événement(s) (nœud atelier-node/1) »).
- Écriture : commentaires, ordre et autres clés préservés ; clé existante remplacée sur place, nouvelle clé ajoutée sous
  un en-tête dédié ; écriture atomique ; droits **600**.
- Une variable d'environnement du processus l'emporte sur le `.env` : le champ est affiché, verrouillé, avec la raison.
- **Origine contrôlée** : refus (403) d'un appel venant d'une autre origine que l'interface de Nexus (origines CORS
  déclarées ou même origine dans l'application de bureau). Le corps JSON impose de toute façon une requête de contrôle
  CORS aux navigateurs.
- Sans clé Claude ni Claude Code, le moteur par défaut devient Ollama (au lieu d'une erreur à chaque message).

Fichier utilisé : `backend/.env` en développement, `~/Library/Application Support/Atelier Nexus/.env` dans
l'application de bureau.

## Fenêtre de contexte d'Ollama (`OLLAMA_NUM_CTX`)

Groupe « Modèles », champ « Mémoire de conversation d'Ollama (jetons) ». Nexus envoie cette valeur à chaque appel
(`options.num_ctx`, `OllamaProvider`). Sans elle, Ollama applique sa fenêtre par défaut (quelques milliers de jetons
sur une machine courante) et **écarte en silence le début de la conversation** : consignes, schémas des outils,
anciens résultats d'outils. Or les agents 100 % locaux (Finance, Comptable, Tuteur) n'ont pas d'autre moteur, et leurs
seules consignes et outils occupent déjà 2 000 à 3 000 jetons.

| Valeur | Effet |
|---|---|
| `8192` (**défaut**) | Consignes, outils et une conversation courante ; environ 1 Go de mémoire pour la fenêtre d'un modèle 8B (`llama3.1:8b`). |
| `16384` | Longues séances (interrogation de 10 cartes et plus, chapitre + cartes existantes) ; environ 2 Go pour un 8B, ordinateur de 16 Go ou plus. |
| `0` (ou `OLLAMA_NUM_CTX=` vide, écrit dans le fichier `.env`) | Rien n'est envoyé : fenêtre du serveur, réglable côté Ollama par `OLLAMA_CONTEXT_LENGTH`. Dans Réglages, un champ **vidé** retire la clé du `.env` et revient donc au défaut, 8192 : saisir `0`. |

Toujours la même valeur d'un appel à l'autre : un changement ferait recharger le modèle par Ollama (quelques
secondes). Une autre application qui appelle le même Ollama avec une autre fenêtre (Ciné, Savoir) provoque aussi un
rechargement, sans autre effet. Valeurs permises : 0, ou de 2 048 à 262 144 (contrôle du modèle `Settings` ; en
dessous, les consignes et les outils d'un agent local ne tiennent plus). La valeur envoyée par Nexus l'emporte sur
`OLLAMA_CONTEXT_LENGTH` du serveur : si vous avez déjà réglé une grande fenêtre côté Ollama, mettez `0` ici.

## Réglages du fichier `.env` seulement

Hors de la liste blanche de l'interface (ils changent le comportement de fond, pas une connexion) :

| Clé | Défaut | Rôle |
|---|---|---|
| `TIMEZONE` | `Europe/Paris` | Fuseau IANA des horaires quotidiens des déclencheurs (heure d'été / d'hiver par `zoneinfo`). Un nom inconnu est refusé au démarrage. |
| `TRIGGERS_ENABLED` | `true` | Tâche de fond des déclencheurs de workflows ; `false` la coupe (les tests la coupent). |
| `TRIGGERS_POLL_SECONDS` | `15` | Intervalle entre deux passages (1 à 3600 s) : lecture des événements, horaires échus, rafales. |

Ces trois valeurs sont lues au démarrage du backend ([`workflows.md`](workflows.md#déclencheurs--étape-20)).
