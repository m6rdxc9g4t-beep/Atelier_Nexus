# Workflows rejouables — Étape 18

« L'agent explore, le workflow industrialise. » La première fois, un agent trouve le chemin :
il lit le schéma d'un jeu Data Via, lance la bonne agrégation, publie la mesure DAX. Ce chemin
est ensuite enregistré tel quel et relancé **sans modèle** : mêmes outils, même ordre, résultat
immédiat, aucun jeton, rien qui quitte la machine.

## 1. Dans l'interface

1. Sous la dernière réponse d'un agent qui a utilisé des outils avec succès :
   **Enregistrer en workflow**.
2. La fenêtre propose les étapes du tour (les appels réussis, dans l'ordre). On peut retirer
   une étape, modifier ses paramètres (JSON) et remplacer une valeur par `{{nom}}` pour la
   demander à chaque lancement (`"dataset_id": "{{jeu}}"`). Libellé et valeur par défaut de
   chaque paramètre se règlent en dessous.
3. Bouton **Workflows** dans l'en-tête de la conversation : liste des workflows de l'agent,
   **Lancer** (avec les paramètres), modifier, supprimer.
4. Les livrables (aperçus Data Via, DAX, Markdown…) arrivent dans le panneau Artefacts, comme
   ceux de l'agent. Le détail de chaque étape (✓ réussie, ✗ en erreur, refusée, non exécutée)
   s'affiche dans la fenêtre.

Ce qui n'est jamais capturé : un appel en erreur ou refusé, un appel resté en attente de
validation, `delegate_to_agent` (il fait appel à un modèle) et `current_datetime` (rien à en
faire sans modèle). La fenêtre indique ce qui a été écarté et pourquoi.

## 2. Garde-fous

- **Porte de contrôle avant de commencer** : chaque étape est vérifiée (outil disponible pour
  l'agent, paramètres valides pour cet outil). Un problème → rien n'est exécuté.
- **Arrêt à la première erreur ou au premier refus** : les étapes suivantes sont marquées
  « non exécutées » (elles dépendent souvent de la précédente : un commit après la création
  d'une branche). Un refus donne le statut `stopped`.
- **Écritures validées à chaque lancement** : une étape `requires_approval` (créer une tâche
  dans Projets, modifier Tab…) n'est jamais exécutée sans « Autoriser », exactement comme dans
  le chat ; le workflow s'arrête d'abord sur `awaiting_approval` sans rien exécuter.
- **Une validation vaut pour l'action montrée, et elle seule** : chaque action en attente
  porte un jeton calculé à partir du workflow (identifiant et version), du numéro d'étape, de
  l'outil et des valeurs finales. D'autres valeurs de paramètres, une étape déplacée ou un
  workflow modifié entre-temps donnent un autre jeton : la validation est redemandée.
- **Jamais d'outil qui appelle un modèle** : `delegate_to_agent` est refusé à
  l'enregistrement comme au lancement.
- **Contexte partagé** entre les étapes : l'exploration préalable de Data Via (schéma avant
  requête) reste satisfaite, comme pendant le tour d'origine.
- **Aucun modèle** : un workflow d'un agent « 100 % local » (Finance, Tuteur…) ne fait que des
  appels aux applications locales.

## 3. API

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/workflows?agent=` | Liste (les plus récemment modifiés ou lancés d'abord) |
| POST | `/api/workflows/capture` | `{agent, messages}` → `WorkflowDraft` (étapes, écartés, étapes d'écriture). Rien n'est enregistré. 422 si aucun appel réutilisable. |
| POST | `/api/workflows` | `{agent, title, description, steps, params, source_conversation_id}` → 201 |
| GET / PUT / DELETE | `/api/workflows/{id}` | Lecture, modification (titre, description, étapes, paramètres), suppression |
| POST | `/api/workflows/{id}/run` | `{params, approvals}` → `WorkflowRunResult` |

Étape : `{"tool": "data_via_query", "input": {…}, "label": ""}` (30 au plus).
Paramètre : `{"name": "jeu", "label": "Jeu de données", "default": "ventes_2026"}` (10 au plus,
nom `^[a-z][a-z0-9_]{0,39}$`). Un `{{nom}}` cité dans une étape doit être déclaré (422 sinon).
Les paramètres sont substitués comme **texte** ; c'est l'outil qui convertit (« 20 » pour un
champ entier devient 20), et un identifiant « 007 » reste « 007 ».

Outils inconnus de l'agent refusés à l'enregistrement (422) ; un outil dont l'application n'est
pas configurée est accepté et signalé au lancement.

Résultat d'exécution :

```json
{
  "status": "completed | failed | stopped | awaiting_approval",
  "message": "2 étape(s) exécutée(s), 1 livrable(s).",
  "steps": [{"index": 1, "tool": "…", "label": "", "input": {…}, "status": "ok | error | refused | skipped", "content": "…"}],
  "artifacts": [{"kind": "data_preview", "title": "…", "content": "…", "language": null, "metadata": {}}],
  "pending": [{"index": 2, "tool": "projets_create_work_item", "summary": "Créer la TASK « … »", "token": "9f2c…"}]
}
```

`approvals` : jeton reçu dans `pending` → `true` / `false`. Un workflow dont l'agent a été
supprimé répond 409 au lancement.

Base : table `workflows` (migration `0005_workflows`), avec compteur de lancements et dernier
statut. Code : `app/workflows.py` (capture et exécution), `app/schemas/workflows.py`,
`app/db/workflows.py`, `app/api/workflows.py` ; interface dans `frontend/src/features/workflows/`.

## 4. Quand préférer un workflow à un agent

| Situation | Choix |
|---|---|
| Même question chaque semaine sur les mêmes données | Workflow (paramètre : la période) |
| Données inconnues, question nouvelle | Agent |
| Le résultat doit être identique d'une fois sur l'autre | Workflow |
| Il faut interpréter les chiffres, rédiger | Agent, éventuellement après un workflow qui prépare les données |

---

# Workflows v2 multi-applications — Étape 19

Contrat d'API figé avec le frontend : [`workflows-v2-api.md`](workflows-v2-api.md). Contrat des
applications : [`apps/noeud-atelier.md`](apps/noeud-atelier.md) (lecture des nœuds :
[`apps/noeuds.md`](apps/noeuds.md)).

Un workflow v2 est un **graphe** d'étapes. Chaque étape utilise un outil Nexus (`tool:<nom>`) ou
une action déclarée par le manifeste d'une application (`node:<app>/<action_id>`, Viz, Projets,
Tab). Les étapes se citent par gabarits : `{{steps.lire.data.rows[0].titre}}` passe une valeur
d'une application à l'autre, sans modèle.

## 5. Schéma

```json
{
  "version": 2, "agent": null, "title": "Planning Tab → tâches Projets → jeu Viz",
  "params": [{"name": "table", "label": "Table", "default": "tbl_planning_lots"}],
  "steps": [
    {"id": "lire", "uses": "node:tab/tables.query", "input": {"table_id": "{{params.table}}"}, "needs": []},
    {"id": "creer", "uses": "node:projets/work_items.create", "needs": ["lire"],
     "input": {"story_id": 2, "type": "TASK", "title": "{{steps.lire.data.rows[0].task_name}}"}},
    {"id": "publier", "uses": "node:viz/datasets.upsert_rows", "needs": ["lire"],
     "when": {"left": "{{steps.lire.data.total}}", "op": "gt", "right": 0},
     "input": {"name": "lots", "table": "{{steps.lire.data}}"}, "on_error": "continue"}
  ]
}
```

- `agent: null` = **workflow de suite** : toutes les boîtes non internes, seules les configurées
  sont disponibles. Un workflow d'agent n'a que les outils de ses boîtes. Les actions `node:` sont
  ouvertes à tous (elles passent par les garde-fous ci-dessous).
- Gabarits : `{{params.x}}` (ou `{{x}}`, forme v1), `{{steps.<id>.data…}}`, `.content`, `.status`,
  `{{run.id}}`. Un gabarit seul garde le type de sa cible (nombre, table…), inclus dans un texte il
  devient du texte. On ne cite que ses **ancêtres** (`needs`, transitivement). Un paramètre (texte)
  exactement cité dans un champ nombre ou booléen d'une action de nœud est converti (« 20 » → 20).
- `when` (`eq ne gt gte lt lte contains empty not_empty`) : comparaison numérique si les deux côtés
  sont des nombres. Condition fausse → `skipped` ; une étape dont un ancêtre direct est `skipped`
  l'est aussi, sauf si sa condition teste justement ce statut (`{{steps.x.status}}`).

## 6. Garde-fous (mêmes principes qu'en v1)

- **Porte de contrôle** : le graphe est validé (§7) et les entrées vérifiées avec les paramètres
  avant la première étape ; un problème → exécution `failed`, « Rien n'a été exécuté ».
- **Chaque écriture s'arrête** (`write` / `destructive` du manifeste, outil `requires_approval`) sur
  `awaiting_approval` avec son **entrée résolue** (valeurs réelles des étapes précédentes). Jeton :
  `sha256(run_id, step_id, uses, entrée)[:32]` ; la reprise exécute exactement l'entrée montrée. Un
  jeton absent ou périmé laisse l'exécution en attente ; deux reprises simultanées n'exécutent
  qu'une fois (passage atomique `awaiting_approval → running`).
- **Définition figée au lancement** : modifier le workflow pendant une validation ne change pas ce
  qui sera exécuté.
- **Idempotence** : une action `idempotency: header` reçoit `Idempotency-Key: nexus:<run>:<step>`,
  une action `field` le champ `idempotency_key` ; relancer une reprise ne crée pas de doublon.
- **Jamais de modèle** : `delegate_to_agent`, `current_datetime` → `NOT_REPLAYABLE`. Les outils
  `sensitive` sont permis (aucune donnée ne part vers un modèle) ; rien des données des étapes
  n'est journalisé.
- **Nœuds** : adresses de bouclage uniquement, redirections refusées, réponse ≤ 10 Mo, délai
  `APPS_TIMEOUT`, entrée validée contre `input_schema` (JSON Schema 2020-12).
- Erreur : `on_error: stop` → `failed`, la suite `skipped` ; `continue` → on poursuit (une étape qui
  lit la `data` absente échoue en `REF_NOT_FOUND`). Refus → `refused`, exécution `stopped`.
- Sortie conservée : `content` ≤ 4000 caractères, table ≤ 1000 lignes (`truncated: true`), JSON
  ≤ 5 Mo. Une table renvoyée par un nœud devient un artefact `data_preview` ; les outils gardent
  leurs artefacts.
- Le contexte partagé des outils (schémas Data Via consultés) est conservé entre deux reprises.

## 7. Validation

`POST /api/workflows/validate` → `{ok, errors: [{step_id, field, code, message}], order}`. `field` :
nom du champ d'entrée de premier niveau (`dataset_id`), `id`, `needs`, `when`, ou `null` (étape
entière, `uses`). Codes : `DUPLICATE_ID`, `BAD_ID`, `UNKNOWN_USES`, `UNAVAILABLE`, `CYCLE`,
`UNKNOWN_NEED`, `REF_NOT_ANCESTOR`, `UNDECLARED_PARAM`, `INPUT_INVALID`, `TOO_MANY_STEPS`,
`NOT_REPLAYABLE`, et (comme l'éditeur) `NO_STEPS`, `DUPLICATE_PARAM`, `BAD_TEMPLATE`,
`BAD_CONDITION`. Un champ qui contient un gabarit n'est vérifié qu'à l'exécution.

Enregistrer (`POST` / `PUT /api/workflows`, `version: 2`) refuse (422) un graphe cassé ; une
application indisponible, une entrée incomplète ou une condition inachevée sont acceptées
(brouillon) et vérifiées au lancement.

## 8. API v2

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/workflows/catalog?agent=` | Étapes disponibles (outils + actions des manifestes), statut des applications |
| POST | `/api/workflows/validate` | Validation (codes ci-dessus) et ordre d'exécution |
| POST / PUT | `/api/workflows`, `/api/workflows/{id}` | Corps v2 (`version: 2`) ou v1 |
| POST | `/api/workflows/{id}/convert` | v1 → v2 enregistré (ids `s1..sn`, chaîne de `needs`, `{{nom}}` → `{{params.nom}}`) |
| POST | `/api/workflows/{id}/run` | v2 : `WorkflowRun` persistée ; v1 : `WorkflowRunResult` inchangé |
| POST | `/api/workflow-runs/{id}/resume` | `{approvals: {jeton: bool}}` ; 409 si l'exécution n'attend rien |
| GET | `/api/workflow-runs?workflow_id=&limit=`, `/api/workflow-runs/{id}` | Exécutions, récentes d'abord |
| GET | `/api/suite/map`, `/api/suite/events?app=&since=&limit=` | Carte de la suite, événements (§7 du contrat) |

Base : migration `0006_workflow_runs` (table `workflow_runs`, colonne `workflows.version` à 1 par
défaut, `agent` facultatif ; la descente retire les workflows v2). Code : `app/workflows_v2/`
(`templates`, `graph`, `steps`, `validation`, `engine`), `app/suite/` (nœuds),
`app/schemas/workflows_v2.py`, `app/api/workflows.py`, `app/api/suite.py`.

Sortie structurée des outils (`ToolOutput.data`, jamais envoyée au modèle) : `atelier-table/1` pour
`data_via_query`, `data_via_list_datasets`, `tab_list_tables`, `tab_read_table`, `tab_aggregate`,
`projets_list_projects`, `projets_list_work_items`, `projets_timesheet`, `projets_milestones` ;
fiches pour `data_via_describe_dataset`, `projets_work_item`, les écritures Projets (`{id, …}`) et
le pont Tab → Projets (résumé de l'import).
