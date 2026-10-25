# Lecture des nœuds de la suite par Nexus (étape 19)

Nexus lit le contrat `atelier-node/1` ([`noeud-atelier.md`](noeud-atelier.md)) de quatre
applications pour les workflows v2, les déclencheurs et la carte de la suite. Code :
`backend/app/suite/` (registre des nœuds HTTP : `HTTP_NODES` dans `app/suite/apps.py`).

| Application | Manifeste | Actions | Événements |
|---|---|---|---|
| Atelier Viz | `GET {DATA_VIA_BASE_URL}/atelier/manifest` | HTTP, chemins du manifeste (`/api/…`) | `GET {DATA_VIA_BASE_URL}/atelier/events` |
| Atelier Projets | `GET {PROJETS_BASE_URL}/atelier/manifest` | HTTP | `GET {PROJETS_BASE_URL}/atelier/events` |
| Atelier Tab | fichier `{TAB_EXPORTS_DIR}/_atelier/manifest.json`, sinon outil MCP `atelier_manifest` | serveur MCP (`TAB_MCP_COMMAND`) | `_atelier/events.jsonl`, sinon outil MCP `atelier_events` |
| Atelier Convert | `GET {CONVERT_BASE_URL}/atelier/manifest` | HTTP (chemins `/api/…`), délai des actions `CONVERT_TIMEOUT` (120 s : une conversion avec OCR est longue) | `GET {CONVERT_BASE_URL}/atelier/events` (délai `APPS_TIMEOUT`) |

Atelier Convert (API sur `127.0.0.1:8010`, défaut `CONVERT_BASE_URL=http://127.0.0.1:8010/api`)
publie 6 actions : `conversions.list`, `conversions.table` (`atelier-table/1`),
`conversions.convert_file` (fichier en base64 : à éviter dans un workflow, le contenu serait
conservé dans l'historique des exécutions), `tab.projects`, `conversions.send_to_tab` (crée
toujours une nouvelle table dans le dossier de données de Tab, `Idempotency-Key`) et
`conversions.delete` (destructive) ; 4 événements `convert.conversion.created|updated|sent_to_tab|
deleted` (sujet : la conversion, `subject.id` = ses 12 caractères hexadécimaux). Le cœur de Nexus
n'enregistre aucune boîte à outils `convert` : celles de l'extension Agent_DatAnalyst (`convert`,
`convert_write`) restent les siennes, avec la même variable `CONVERT_BASE_URL`. En Docker,
l'adresse `host.docker.internal` n'est pas une adresse de bouclage : Convert apparaît injoignable,
comme Viz et Projets.

`GET /api/apps/status` (Réglages → Vérifier) lit le manifeste de Convert sans le cache
(`state(app, fresh=True)`) : « 6 action(s), 4 événement(s) (nœud atelier-node/1) ».

## Statuts

`ok` (manifeste lu), `unreachable` (application arrêtée, délai de 5 s dépassé, adresse non locale,
manifeste illisible), `no_contract` (404 ou fichier absent : version antérieure au contrat, ou
contrat d'une autre version), `not_configured` (variable vide). Cache en mémoire : 60 s pour `ok` et
`no_contract`, 10 s pour une application injoignable ; la clé du cache comprend l'adresse : un
changement dans les Réglages relit le manifeste à la requête suivante. Tab sans
`TAB_MCP_COMMAND` : manifeste et événements lus (fichiers), actions indisponibles (transport
`files`).

## Lecture tolérante, garde-fous stricts

- Champs inconnus ignorés ; une action mal formée (identifiant hors motif, deux transports ou aucun,
  chemin avec `..`, schéma invalide, doublon) est écartée et le reste du manifeste reste utilisable.
- HTTP : bouclage uniquement (`127.0.0.1`, `localhost`, `::1`), redirection = erreur `REDIRECT`,
  réponse ≤ 10 Mo (`RESPONSE_TOO_LARGE`), paramètres `{nom}` du chemin encodés (jamais `.` ni `..`),
  route `GET` → requête (listes répétées), sinon corps JSON.
- Entrée validée contre `input_schema` (JSON Schema 2020-12, bibliothèque `jsonschema`) avant tout
  appel (`INPUT_INVALID`). Un `$ref` introuvable (ou vers une adresse extérieure, jamais lue) est
  une erreur d'entrée lisible, jamais une exception : l'action est refusée sans requête.
- Erreurs relayées : `{detail, code}` de l'application (`NOT_FOUND`, `VALIDATION`,
  `IDEMPOTENCY_KEY_REUSED`…), ou codes Nexus `UNREACHABLE`, `UNKNOWN_ACTION`, `UNAVAILABLE`,
  `FORBIDDEN_HOST`, `MCP_ERROR`.
- Idempotence : `header` → `Idempotency-Key`, `field` → `idempotency_key` dans l'entrée MCP ;
  `Idempotency-Replayed: true` (ou `replayed: true` côté MCP) est signalé dans le résumé.
- Sortie d'une action : `data` = JSON de la réponse (table `atelier-table/1` reconnue), `content` =
  résumé court (« Créer un élément : terminé (id 30000). »).

## Tests

`tests/fake_suite.py` : doubles des manifestes et des routes `/api/atelier/*` (Viz :
`datasets.query`, `datasets.list`, `datasets.upsert_rows`, `datasets.delete` ; Projets :
`work_items.list`, `work_items.create`, `work_items.delete` ; Tab : `tables.query`, `rows.add`,
`rows.delete`). Le faux serveur MCP (`tests/fake_tab_mcp.py`) répond aussi à `atelier_manifest`,
`atelier_events` et `query_table`. Pour Viz, Projets et Tab, ces noms d'actions sont des
**hypothèses** qui exercent le moteur : les manifestes réels font foi (le catalogue les lit tels
quels).

Manifestes **réels** enregistrés une fois (jamais retouchés : `tests/fixtures/` est protégé) :
`tests/fixtures/convert/manifest.json` (`build_manifest()` dans le venv d'Atelier_Convert, 0.1.0),
`tests/fixtures/viz/manifest.json` (Atelier Viz 0.1.0), `tests/fixtures/projets/manifest.json`
(`buildManifest()` du backend compilé d'Atelier Projets, 0.1.0) et
`tests/fixtures/tab/manifest.json` (`_atelier/manifest.json` écrit par Atelier Tab 0.6.0).
`FakeConvertNode` répond aux routes du manifeste réel de Convert ; la bibliothèque de modèles de
workflows est validée contre les quatre (`tests/test_workflow_library.py`). Chaque nœud HTTP a son
transport simulé dans `Suite.env` (clé `convert` partagée avec le client de l'extension) : sans lui,
`states()` joindrait la vraie application locale.
