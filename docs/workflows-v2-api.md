# Atelier Nexus — Workflows v2 et carte de la suite : contrat d'API (backend ↔ frontend)

Référence pour les deux chantiers parallèles (backend FastAPI, frontend Next.js). Les noms ci-dessous sont **figés** :
le frontend code contre eux avec des doubles, le backend les implémente tels quels. Tout écart doit être signalé, pas improvisé.
Contrat des applications : `docs/apps/noeud-atelier.md` (atelier-node/1 : manifeste, `atelier-table/1`, événements, idempotence).

## 1. Étapes « nœud » et étapes « outil »

Une étape v2 utilise soit un **outil Nexus** existant (`tool:<nom>`, ex. `tool:data_via_query`), soit une **action d'application**
déclarée dans un manifeste (`node:<app>/<action_id>`, ex. `node:projets/work_items.create`, `node:tab/rows.add`).

## 2. Schémas

```ts
type StepUses = string;           // "tool:<nom_outil>" | "node:<app>/<action_id>"

interface Condition {             // l'étape ne s'exécute que si la condition est vraie (sinon "skipped")
  left: string;                   // gabarit, ex. "{{steps.lire.data.total}}"
  op: "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains" | "empty" | "not_empty";
  right?: unknown;                // absent pour empty / not_empty
}

interface WorkflowStepV2 {
  id: string;                     // ^[a-z][a-z0-9_]{0,39}$, unique dans le workflow
  label: string;                  // "" autorisé
  uses: StepUses;
  input: Record<string, unknown>; // valeurs littérales ou gabarits {{…}} (récursif dans objets / listes)
  needs: string[];                // ids des étapes amont (arêtes du graphe) ; DAG obligatoire
  when?: Condition | null;
  on_error: "stop" | "continue";  // défaut "stop"
  position?: { x: number; y: number } | null;  // placement dans l'éditeur, ignoré par le moteur
}

interface WorkflowParam { name: string; label: string; default: string }   // inchangé (v1)

interface WorkflowV2 {
  id: string; version: 2;
  agent: string | null;           // null = workflow de suite (toutes les boîtes configurées)
  title: string; description: string;
  steps: WorkflowStepV2[];        // 30 au plus
  params: WorkflowParam[];        // 10 au plus
  source_conversation_id: string | null;
  run_count: number; last_run_at: string | null; last_status: string | null;
  created_at: string; updated_at: string;
}
```

Les workflows v1 (`version: 1`, étapes `{tool, input, label}` indexées, `agent` obligatoire) restent lisibles et lançables
comme avant. `GET /api/workflows` renvoie les deux ; le champ `version` les distingue.

### Références (gabarits)

| Gabarit | Valeur |
|---|---|
| `{{params.nom}}` (ou `{{nom}}`, forme v1) | paramètre de lancement (texte) |
| `{{steps.<id>.data}}` | sortie structurée de l'étape (JSON) |
| `{{steps.<id>.data.rows[0].titre}}` | chemin : `.champ`, `[n]` |
| `{{steps.<id>.content}}` | texte de l'étape |
| `{{steps.<id>.status}}` | `ok` / `error` / `refused` / `skipped` |
| `{{run.id}}` | identifiant de l'exécution |

- Une valeur qui est **exactement** un gabarit garde le type JSON de la cible (nombre, liste, objet, table) ; un gabarit inclus dans un texte est converti en texte (JSON compact pour objets / listes).
- Une étape ne peut citer que ses **ancêtres** (via `needs`, transitivement). Chemin introuvable à l'exécution → étape en erreur (`code: "REF_NOT_FOUND"`).

## 3. Catalogue des étapes

`GET /api/workflows/catalog?agent=<nom>` (sans `agent` : catalogue de suite)

```ts
interface CatalogEntry {
  uses: string;                   // "tool:…" | "node:app/action"
  source: "tool" | "node";
  app: string | null;             // "viz" | "tab" | "projets" | "cine" | … | null (outil système)
  label: string; description: string;
  kind: "read" | "write" | "destructive";   // outil : requires_approval → "write"
  input_schema: Record<string, unknown>;    // JSON Schema (portable_schema pour un outil)
  output_format: "atelier-table/1" | "json" | "text";
  output_hint: { columns?: { key: string; label: string; type: string }[]; fields?: string[] } | null;
  available: boolean;             // false si l'app n'est pas configurée / ne répond pas
  unavailable_reason: string | null;
}
interface Catalog {
  apps: { app: string; name: string; status: "ok" | "unreachable" | "no_contract" | "not_configured"; color: string }[];
  entries: CatalogEntry[];
}
```

Couleurs (signature, docs/SUITE.md §1.7) : viz `#F2C811`, tab `#21A366`, projets `#94D82D`, nexus `#E8590C`, cine `#E64980`,
savoir `#9B5DE5`, tresorerie `#3B5BDB`, cuisine `#E056E2`, dates `#E03131`, système (null) → couleur nexus.

## 4. Validation

`POST /api/workflows/validate` corps `{agent, title, description, steps, params, version: 2}` →
`{ ok: boolean, errors: { step_id: string | null, field: string | null, code: string, message: string }[], order: string[] }`
(`order` = ordre d'exécution topologique si `ok`). Codes : `DUPLICATE_ID`, `BAD_ID`, `UNKNOWN_USES`, `UNAVAILABLE`, `CYCLE`,
`UNKNOWN_NEED`, `REF_NOT_ANCESTOR`, `UNDECLARED_PARAM`, `INPUT_INVALID` (champ en `field`), `TOO_MANY_STEPS`, `NOT_REPLAYABLE`.
La validation d'entrée tolère les gabarits : un champ qui contient un gabarit n'est vérifié qu'à l'exécution.

## 5. CRUD (inchangé, étendu)

`GET /api/workflows?agent=` (sans `agent` : tous, v1 et v2) · `POST /api/workflows` (corps v2 avec `version: 2`, ou v1) →
201 · `GET/PUT/DELETE /api/workflows/{id}` · `POST /api/workflows/{id}/convert` (v1 → v2, enregistré, renvoie le v2 :
ids `s1..sn`, chaîne linéaire de `needs`, `{{nom}}` → `{{params.nom}}`).

## 6. Exécutions (persistées)

```ts
type RunStatus = "running" | "awaiting_approval" | "completed" | "failed" | "stopped";
interface StepRun {
  id: string; uses: string; label: string;
  status: "pending" | "ok" | "error" | "refused" | "skipped" | "awaiting_approval";
  input: Record<string, unknown> | null;     // entrée résolue (null tant que non résolue)
  content: string;                            // texte (≤ 4000 caractères)
  data: unknown;                              // sortie structurée (tables tronquées à 1000 lignes, truncated: true)
  error_code: string | null;
  started_at: string | null; ended_at: string | null;
}
interface PendingApproval { step_id: string; uses: string; kind: "read" | "write" | "destructive"; summary: string; token: string; input: Record<string, unknown> }
// kind "read" : seulement en APPROVAL_MODE=every_step (défaut), où chaque étape attend une validation
interface WorkflowRun {
  id: string; workflow_id: string; status: RunStatus; message: string;
  params: Record<string, string>; trigger: "manual";
  steps: StepRun[];               // dans l'ordre d'exécution
  artifacts: Artifact[];          // même forme que le panneau Artefacts
  pending: PendingApproval[];     // au plus une étape à la fois
  created_at: string; updated_at: string;
}
```

- `POST /api/workflows/{id}/run` corps `{params}` → `WorkflowRun` (v2) — pour un v1, réponse v1 inchangée (`WorkflowRunResult`).
- Le moteur avance étape par étape. Selon le réglage `APPROVAL_MODE` (docs/settings.md) :
  - `every_step` (**défaut**, choix de l'utilisateur) : **chaque** étape `tool:` ou `node:`, lectures comprises, **s'arrête** sur
    `awaiting_approval` (`kind: "read"` pour une lecture) avec son entrée **résolue**, donc après l'exécution des étapes précédentes
    (leur résultat est dans `steps[]`) ;
  - `writes_only` : seules les étapes `write`/`destructive` s'arrêtent ; les lectures s'exécutent seules.

  Une étape dont la condition `when` est fausse (ou dont un ancêtre a été sauté) reste `skipped` **sans** validation : rien ne
  s'exécute. Le mode est retenu au lancement ; s'il passe à `every_step` en cours d'exécution, il s'applique aux étapes suivantes.
  Jeton = sha256(run_id, step_id, uses, entrée résolue)[:32] (inchangé).
- `POST /api/workflow-runs/{run_id}/resume` corps `{approvals: {token: boolean}}` → `WorkflowRun` (reprend ; refus → étape `refused`, exécution `stopped`, la suite `skipped`).
- `GET /api/workflow-runs?workflow_id=&limit=` (récents d'abord) · `GET /api/workflow-runs/{run_id}`.
- Erreur d'une étape : `on_error: "stop"` → exécution `failed`, la suite `skipped` ; `"continue"` → on poursuit (les étapes qui la citent échouent en `REF_NOT_FOUND` si elles lisent sa `data`).
- Étape `node:` qui déclare `idempotency` `header`/`field` : clé `nexus:<run_id>:<step_id>`.
- Jamais d'appel de modèle : `delegate_to_agent` et `current_datetime` refusés (`NOT_REPLAYABLE`).

## 7. Carte de la suite

`GET /api/suite/map` →
```ts
interface SuiteMap {
  apps: {
    app: string; name: string; color: string;
    status: "ok" | "unreachable" | "no_contract" | "not_configured";
    transport: "http" | "mcp" | "files" | null;
    actions: { id: string; label: string; kind: "read" | "write" | "destructive"; output_format: string }[];  // du manifeste
    events: { type: string; label: string }[];
    nexus_tools: { name: string; kind: "read" | "write"; toolset: string }[];  // outils Nexus qui touchent l'app
    agents: { name: string; display_name: string; icon: string; toolsets: string[]; writes: boolean }[];
  }[];
  flows: { from: string; to: string; label: string; via: string }[];   // échanges de docs/SUITE.md §4 + ceux de Nexus
  workflows: { id: string; title: string; apps: string[] }[];          // workflows qui touchent chaque app
}
```
`flows` fixes : tab→projets « Import DataFlow » (webhook), tab→viz « Instantanés » (fichiers), projets→viz « Jeux de données » (HTTP),
plus nexus→chaque app atteinte par au moins un outil d'écriture (« Écritures validées ») et chaque app→nexus lue (« Lecture »).

`GET /api/suite/events?app=&since=&limit=` → `{ app: string; events: AtelierEvent[]; next: number; gap?: boolean; status: string }[]`
(une entrée par app ; `since` n'a de sens qu'avec `app`). `AtelierEvent` = format §7.3 du contrat.

## 8. Sortie structurée des outils

`ToolOutput.data` (facultatif) ; les outils de lecture renvoient `atelier-table/1` pour les tables
(`data_via_query`, `tab_read_table`, `tab_aggregate`, `projets_list_work_items`, `projets_timesheet`) et un objet pour les fiches
(`projets_work_item`, créations : `{id, …}`).
