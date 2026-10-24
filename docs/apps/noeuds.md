# Lecture des nœuds de la suite par Nexus (étape 19)

Nexus lit le contrat `atelier-node/1` ([`noeud-atelier.md`](noeud-atelier.md)) de six
applications (Wiki et Formulaire depuis l'étape 26, Convert depuis l'étape 28) pour les workflows v2 et la carte de la suite. Code : `backend/app/suite/`.

| Application | Manifeste | Actions | Événements |
|---|---|---|---|
| Atelier Viz | `GET {DATA_VIA_BASE_URL}/atelier/manifest` | HTTP, chemins du manifeste (`/api/…`) | `GET {DATA_VIA_BASE_URL}/atelier/events` |
| Atelier Projets | `GET {PROJETS_BASE_URL}/atelier/manifest` | HTTP | `GET {PROJETS_BASE_URL}/atelier/events` |
| Atelier Tab | fichier `{TAB_EXPORTS_DIR}/_atelier/manifest.json`, sinon outil MCP `atelier_manifest` | serveur MCP (`TAB_MCP_COMMAND`) | `_atelier/events.jsonl`, sinon outil MCP `atelier_events` |
| Atelier Wiki | `GET {WIKI_BASE_URL}/atelier/manifest` | HTTP | `GET {WIKI_BASE_URL}/atelier/events` |
| Atelier Formulaire | `GET {FORMULAIRE_BASE_URL}/atelier/manifest` | HTTP | `GET {FORMULAIRE_BASE_URL}/atelier/events` |
| Atelier Convert | `GET {CONVERT_BASE_URL}/atelier/manifest` | HTTP | `GET {CONVERT_BASE_URL}/atelier/events` ([`convert.md`](convert.md)) |

## Statuts

`ok` (manifeste lu), `unreachable` (application arrêtée, délai de 5 s dépassé, adresse non locale,
manifeste illisible), `no_contract` (404 ou fichier absent : version antérieure au contrat, ou
contrat d'une autre version), `not_configured` (variable vide). Cache en mémoire : 60 s pour `ok` et
`no_contract`, 10 s pour une application injoignable. Tab sans `TAB_MCP_COMMAND` : manifeste et
événements lus (fichiers), actions indisponibles (transport `files`).

Wiki et Formulaire servent aussi de connecteurs aux agents (`app/tools/suite_node.py`, [`wiki.md`](wiki.md),
[`formulaire.md`](formulaire.md)) : mêmes actions, mêmes garde-fous.

**Données personnelles dans un workflow.** L'action `formulaire/responses.list` d'un workflow v2
lit les réponses individuelles (répondant, e-mails, textes libres). Un workflow n'appelle aucun
modèle, mais une étape suivante pourrait recopier ces données ailleurs (Wiki, Tab) : chaque
écriture attend la validation de son entrée résolue, à relire en conséquence. Pour un point
partagé, utiliser l'outil `equipe_synthese_formulaires` (agrégats seulement).

## Lecture tolérante, garde-fous stricts

- Champs inconnus ignorés ; une action mal formée (identifiant hors motif, deux transports ou aucun,
  chemin avec `..`, schéma invalide, doublon) est écartée et le reste du manifeste reste utilisable.
- HTTP : bouclage uniquement (`127.0.0.1`, `localhost`, `::1`), redirection = erreur `REDIRECT`,
  réponse ≤ 10 Mo (`RESPONSE_TOO_LARGE`), paramètres `{nom}` du chemin encodés (jamais `.` ni `..`),
  route `GET` → requête (listes répétées), sinon corps JSON.
- Entrée validée contre `input_schema` (JSON Schema 2020-12, bibliothèque `jsonschema`) avant tout
  appel (`INPUT_INVALID`).
- Erreurs relayées : `{detail, code}` de l'application (`NOT_FOUND`, `VALIDATION`,
  `IDEMPOTENCY_KEY_REUSED`…), ou codes Nexus `UNREACHABLE`, `UNKNOWN_ACTION`, `UNAVAILABLE`,
  `FORBIDDEN_HOST`, `MCP_ERROR`.
- Idempotence : `header` → `Idempotency-Key`, `field` → `idempotency_key` dans l'entrée MCP ;
  `Idempotency-Replayed: true` (ou `replayed: true` côté MCP) est signalé dans le résumé.
- Sortie d'une action : `data` = JSON de la réponse (table `atelier-table/1` reconnue), `content` =
  résumé court (« Créer un élément : terminé (id 30000). »).

## Tests

`tests/fake_suite.py` : doubles des trois manifestes et des routes `/api/atelier/*` (Viz :
`datasets.query`, `datasets.list`, `datasets.upsert_rows`, `datasets.delete` ; Projets :
`work_items.list`, `work_items.create`, `work_items.delete` ; Tab : `tables.query`, `rows.add`,
`rows.delete`). Le faux serveur MCP (`tests/fake_tab_mcp.py`) répond aussi à `atelier_manifest`,
`atelier_events` et `query_table`. Ces noms d'actions sont des **hypothèses** de Nexus : les
manifestes réels des applications font foi (le catalogue les lit tels quels).
