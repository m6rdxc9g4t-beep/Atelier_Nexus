# Réglages depuis l'interface (Étape 11)

La roue dentée de l'en-tête ouvre les **Réglages** : clé Claude, modèles, moteur par défaut et de secours, adresses
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

## Règles

- **Liste blanche** (`FIELDS`) : ANTHROPIC_API_KEY, ANTHROPIC_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL,
  LLM_DEFAULT_PROVIDER, LLM_FALLBACK_PROVIDER, DATA_VIA_BASE_URL, PROJETS_BASE_URL, PROJETS_IMPORT_TOKEN,
  TRESORERIE_BASE_URL, CINE_BASE_URL, SAVOIR_BASE_URL, TAB_EXPORTS_DIR, GITHUB_TOKEN, GITHUB_REPO,
  GITHUB_ALLOWED_REPOS. Tout le reste est refusé — en particulier **`TAB_MCP_COMMAND`** (commande exécutée) et
  `DATABASE_URL`, qui restent dans le fichier.
- Validation : adresses `http(s)://`, choix fermés, pas de retour à la ligne (aucune injection d'une autre clé), puis
  contrôle par le modèle `Settings`. Une valeur refusée ne modifie pas le fichier.
- Écriture : commentaires, ordre et autres clés préservés ; clé existante remplacée sur place, nouvelle clé ajoutée sous
  un en-tête dédié ; écriture atomique ; droits **600**.
- Une variable d'environnement du processus l'emporte sur le `.env` : le champ est affiché, verrouillé, avec la raison.
- **Origine contrôlée** : refus (403) d'un appel venant d'une autre origine que l'interface de Nexus (origines CORS
  déclarées ou même origine dans l'application de bureau). Le corps JSON impose de toute façon une requête de contrôle
  CORS aux navigateurs.
- Sans clé Claude, le moteur par défaut devient Ollama (au lieu d'une erreur à chaque message).

Fichier utilisé : `backend/.env` en développement, `~/Library/Application Support/Atelier Nexus/.env` dans
l'application de bureau.
