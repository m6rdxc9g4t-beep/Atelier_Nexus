# Nœud Atelier — copie du contrat commun

Copie de la section 7 de `docs/SUITE.md` (identique dans Atelier_Viz, atelier-tab, Atelier_Projets et Atelier_Convert ; recopiée depuis Atelier_Convert, qui ajoute Convert au §7.1 et au §7.3). Ne pas l'éditer ici : la modifier dans les dépôts de la suite puis recopier.

---

## 7. Nœud Atelier : manifeste, tables et événements (contrat `atelier-node/1`)

Chaque application de la suite est un **nœud** qu'Atelier Nexus peut enchaîner dans un workflow sans connaître son code :
elle **décrit** ce qu'elle sait faire (manifeste), échange des **tables** dans un format unique et publie ses **événements**.
Rien de ce contrat ne fait sortir une donnée de la machine : tout reste en bouclage (`127.0.0.1`, `localhost`, `::1`),
sous les gardes existantes (`local-only`, §5.1). Aucune action du manifeste ne peut passer une application en ligne.

### 7.1 Manifeste

| Application | Où |
|---|---|
| Atelier Viz | `GET http://127.0.0.1:8000/api/atelier/manifest` |
| Atelier Projets | `GET http://127.0.0.1:3000/api/atelier/manifest` |
| Atelier Tab | outil MCP `atelier_manifest` (sans argument, lecture seule) **et** fichier `~/Atelier_Tab/exports/_atelier/manifest.json` réécrit au démarrage de l'app |
| Atelier Convert | `GET http://127.0.0.1:8010/api/atelier/manifest` (`app: "convert"`) |

```json
{
  "contract": "atelier-node/1",
  "app": "viz | projets | tab",
  "name": "Atelier Viz",
  "version": "1.8.0",
  "transport": "http | mcp",
  "actions": [
    {
      "id": "datasets.query",
      "label": "Interroger un jeu de données",
      "description": "Une phrase en français.",
      "kind": "read | write | destructive",
      "http": { "method": "POST", "path": "/api/atelier/query" },
      "mcp_tool": null,
      "input_schema": { "type": "object", "properties": {}, "required": [] },
      "output": { "format": "atelier-table/1 | json", "schema": { } },
      "idempotency": "header | field | natural | none"
    }
  ],
  "events": [
    { "type": "viz.dataset.refreshed", "label": "Jeu actualisé", "data_schema": { "type": "object" } }
  ]
}
```

- `id` : `<domaine>.<verbe>` en minuscules (`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$`), **stable** d'une version à l'autre ; un renommage = nouvelle action, l'ancienne reste listée tant qu'elle répond.
- Exactement un des deux : `http` (Viz, Projets ; `path` avec paramètres `{nom}` pris dans l'entrée) ou `mcp_tool` (Tab).
- `kind` : `read` (aucun effet), `write` (crée ou modifie), `destructive` (supprime ou écrase). Nexus demande une validation humaine pour `write` et `destructive`, à chaque exécution.
- `input_schema` / `output.schema` : JSON Schema (draft 2020-12), propriétés en `snake_case` ; pour une action HTTP, les propriétés citées dans `path` vont dans le chemin, celles d'une route `GET` dans la requête, les autres dans le corps JSON.
- `idempotency` : `header` (en-tête `Idempotency-Key` accepté, §7.4), `field` (champ `idempotency_key` dans l'entrée), `natural` (rejouer donne le même état, ex. `PUT`), `none`.
- Le manifeste ne liste que des actions **utiles à un workflow** ; il n'a pas à couvrir toute l'API. Il ne contient jamais de secret ni de donnée utilisateur.

### 7.2 Table d'échange `atelier-table/1`

Format unique des tables qui passent d'une étape à l'autre (même forme que les jeux `GET /api/exports/datasets/:name` de Projets, §4.3) :

```json
{
  "format": "atelier-table/1",
  "name": "work-items",
  "label": "Éléments de travail",
  "columns": [ { "key": "heures_estimees", "label": "Heures estimées", "type": "number" } ],
  "rows": [ { "heures_estimees": 4 } ],
  "total": 1,
  "truncated": false
}
```

- `type ∈ "string" | "number" | "date" | "datetime" | "boolean"` ; dates `AAAA-MM-JJ`, horodatages ISO 8601 avec fuseau ; valeur absente = `null`.
- `key` : `snake_case` sans accent, unique dans la table ; `label` en français avec accents.
- `truncated: true` quand `rows` ne contient pas tout (`total` = nombre complet si connu, sinon `null`).
- Une enveloppe DataFlow v2.1.0 (§4) se convertit en `atelier-table/1` comme Viz l'aplatit déjà (§4.2) : `_ligne` et `_id` en tête, puis une colonne par entrée de `columns_schema`, valeur `computed`.

### 7.3 Événements

**Viz et Projets** : `GET /api/atelier/events?since=<seq>&limit=<n>` (`limit` ≤ 500, 100 par défaut ; `types=a,b` facultatif).

```json
{
  "events": [
    {
      "seq": 42,
      "type": "projets.work_item.status_changed",
      "at": "2026-10-21T21:30:00+02:00",
      "subject": { "kind": "work_item", "id": "123", "label": "Écrire la doc" },
      "data": { "from": "OPEN", "to": "IN_PROGRESS", "project_id": "1" }
    }
  ],
  "next": 42,
  "oldest": 1
}
```

- `seq` : entier strictement croissant, jamais réutilisé (persisté, survit au redémarrage). `since` exclusif ; sans `since`, les plus récents. `next` = dernier `seq` rendu (ou `since` s'il n'y a rien).
- Rétention : au moins les 1 000 derniers événements ou 30 jours. Si `since < oldest - 1`, la réponse porte `"gap": true` (des événements ont été perdus) : le consommateur relit l'état.
- `data` ne contient que des identifiants, des libellés, des statuts et des nombres agrégés — jamais de lignes de données ni de secret.

**Tab** (pas d'API HTTP) : l'app de bureau et le serveur MCP tiennent, dans `~/Atelier_Tab/exports/_atelier/` :
- `index.json` : `{ "contract": "atelier-node/1", "tables": [ { "table_id", "name", "project", "workspace", "revision", "rows", "updated_at" } ] }` ;
  `revision` est un entier qui augmente à chaque changement réel du contenu de l'instantané (même règle que la réécriture, §4.2) ;
- `events.jsonl` : une ligne JSON par événement, au format ci-dessus (`seq` croissant, mêmes champs), 1 000 lignes au plus (les plus anciennes sont retirées) ;
- même outil MCP `atelier_events` `{ since, limit }` → même réponse que la route HTTP.
Écritures atomiques. Les fichiers du sous-dossier ne sont jamais des enveloppes DataFlow : les lecteurs d'instantanés (Viz, Nexus) ne lisent que `exports/*.json`.

**Types d'événements**

| Application | Type | `subject.kind` | `data` |
|---|---|---|---|
| Viz | `viz.dataset.created` | `dataset` | `name`, `rows`, `origin` |
| Viz | `viz.dataset.refreshed` | `dataset` | `rows`, `trigger` (`manual` / `schedule`) |
| Viz | `viz.dataset.refresh_failed` | `dataset` | `trigger`, `message` |
| Viz | `viz.dataset.deleted` | `dataset` | — |
| Viz | `viz.alert.triggered` | `alert` | `dataset_id`, `value`, `comparison`, `threshold` (+ `dimension`, `values` pour « pour chaque ») |
| Viz | `viz.report.saved` | `report` | `pages` |
| Projets | `projets.work_item.created` | `work_item` | `project_id`, `story_id`, `type`, `status` |
| Projets | `projets.work_item.updated` | `work_item` | `project_id`, `fields` (noms des champs changés) |
| Projets | `projets.work_item.status_changed` | `work_item` | `project_id`, `from`, `to` |
| Projets | `projets.work_item.deleted` | `work_item` | `project_id` |
| Projets | `projets.time_entry.created` | `work_item` | `project_id`, `hours`, `spent_on` |
| Projets | `projets.milestone.reached` | `milestone` | `project_id`, `date` |
| Projets | `projets.import.completed` | `project` | `source`, `created`, `updated`, `skipped` |
| Tab | `tab.table.changed` | `table` | `revision`, `rows`, `project` |
| Tab | `tab.table.deleted` | `table` | — |
| Convert | `convert.conversion.created` | `conversion` | `name`, `format`, `rows`, `columns`, `statement`, `origin` (`interface` / `workflow` / `ai`) |
| Convert | `convert.conversion.updated` | `conversion` | `rows`, `columns`, `reason` (`options` / `columns` / `ai` / `rename`) |
| Convert | `convert.conversion.sent_to_tab` | `conversion` | `table_id`, `table_name`, `project_id`, `rows` |
| Convert | `convert.conversion.deleted` | `conversion` | — |

Actions de Convert : `conversions.list`, `conversions.table` (`atelier-table/1`), `conversions.convert_file`
(fichier en base64, jamais un chemin ; `Idempotency-Key`), `tab.projects`, `conversions.send_to_tab` (`Idempotency-Key`),
`conversions.delete` (`destructive`).

Un changement de statut émet `status_changed` **et** `updated`. Un import émet un seul `import.completed` (pas un événement par ligne).

### 7.4 Idempotence des écritures

Un workflow relancé ne doit pas créer de doublons. Toute action `write` du manifeste qui **crée** quelque chose accepte une clé :
- HTTP : en-tête `Idempotency-Key` (1 à 200 caractères), même règle que l'import Tab (§4.1) : même clé + même corps → même réponse avec `Idempotency-Replayed: true` ; même clé + autre corps → 409 ; rétention 30 jours au moins ;
- MCP (Tab) : champ `idempotency_key` dans l'entrée de l'outil, même règle (la réponse rejouée est identique).
Nexus construit la clé à partir de l'identifiant d'exécution du workflow et de l'étape (`nexus:<run>:<step>`).

### 7.5 Erreurs

Une action en échec répond (HTTP) par un statut ≥ 400 et `{ "detail": "message en français", "code": "CODE_MACHINE" }`.
Codes communs : `NOT_FOUND`, `VALIDATION`, `CONFLICT`, `IDEMPOTENCY_KEY_REUSED`, `OFFLINE` (action qui exige le mode en ligne), `FORBIDDEN_HOST`, `FORBIDDEN_ORIGIN`.
Les routes existantes peuvent garder leur forme ; seules les routes `/api/atelier/*` et les actions ajoutées par ce contrat la suivent.

### 7.6 Vérification

Chaque application teste : la forme du manifeste (contrat, unicité et motif des `id`, un seul transport par action, schémas valides),
l'émission de chaque type d'événement qu'elle déclare, la persistance de `seq`, et l'idempotence de chaque action qui la déclare.
Nexus garde une copie de cette section (`docs/apps/noeud-atelier.md`) et teste sa lecture des trois manifestes avec des doubles.

### 7.7 Précisions (retours des trois implémentations)

Ces règles complètent §7.1 à §7.5 ; Viz, Projets, Tab et Nexus les appliquent déjà.

**Manifeste**
- `http.path` est un chemin absolu depuis la racine de l'app (`/api/atelier/query`, `/api/datasets/{dataset_id}`) ; une action peut désigner une route existante hors `/api/atelier/` : elle garde alors ses formes d'entrée, de sortie et d'erreur (ex. `imports.atelier_tab`, corps DataFlow et réponse en camelCase).
- Une action de lecture déclare `idempotency: "natural"` ou `"none"` (indifférent pour un workflow).
- Toute action `write` qui **crée** (une ligne, une table, une colonne, un élément, un jeu) déclare `header` ou `field`.

**Table `atelier-table/1`**
- `name` = identifiant technique de la table (id de table Tab, nom du jeu Projets, nom normalisé du jeu Viz) ; `label` = nom affiché.
- Un lecteur ignore les champs qu'il ne connaît pas (aucun champ ajouté ne casse un consommateur).

**Événements**
- `next` : dernier `seq` rendu ; sinon `since` s'il est fourni ; sinon le dernier `seq` connu (0 si le journal n'a jamais rien contenu).
- `oldest` : plus ancien `seq` encore conservé ; journal vide → dernier `seq` connu + 1.
- `gap: true` si `since < oldest - 1` (événements retirés) **ou** `since >` dernier `seq` connu (journal remis à zéro ou remplacé). Sinon `gap` vaut `false` ou est absent.
- `types=a,b` est accepté partout (HTTP et outil MCP `atelier_events`).
- `data` peut porter des champs en plus de ceux du tableau §7.3 ; les identifiants y sont toujours des **chaînes**. Ajouts en usage :
  `viz.dataset.created` : `origin ∈ file | <type de connexion> | atelier-table`, plus `format` et `key` (upsert) ;
  `viz.dataset.refresh_failed` : `status` (`error`, `skipped`, `interrupted`) ;
  `projets.import.completed` : `unchanged` (et `subject.id` = id du projet cible, `""` si aucun) ;
  `projets.time_entry.created` : `time_entry_id` ; `projets.milestone.reached` : `reached_at` ;
  `tab.table.changed` : `project` = **nom** du projet Tab (Tab n'a pas d'identifiant de projet partagé).
- Un événement émis en rafale peut être regroupé (au plus un toutes les 5 s pour un même `subject`) : c'est le cas de `viz.report.saved` (le Studio enregistre en continu).
- Tab : `index.json` → `rows` = lignes de données (lignes de total exclues), `updated_at` ISO 8601 avec fuseau, tables triées par `table_id`.

**Idempotence**
- L'empreinte couvre la route (méthode + chemin) ou l'outil, **et** le corps canonique (ordre des clés indifférent) : même clé sur une autre route ou un autre outil → `IDEMPOTENCY_KEY_REUSED`.
- Le rejeu rend le même statut HTTP et le même corps que la première réponse (ex. 201 à la création, 200 à la mise à jour d'un upsert).

**Erreurs**
- Codes communs ajoutés : `FORBIDDEN` (403 générique), `METHOD_NOT_ALLOWED` (405).
- MCP (Tab) : un outil en échec renvoie `isError: true`, `structuredContent: {detail, code}` et le texte du message terminé par `[CODE]`.
