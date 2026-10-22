# Déclencheurs de workflows — contrat d'API (backend ↔ frontend)

Suite de `docs/workflows-v2-api.md`. Un **déclencheur** lance un workflow v2 tout seul : à heure fixe (**horaire**) ou quand
une application publie un **événement** (contrat `atelier-node/1`, `docs/apps/noeud-atelier.md` §7.3 et §7.7).
Les noms ci-dessous sont **figés** : le frontend code contre eux avec des doubles, le backend les implémente tels quels.

## 0. Règles qui ne se négocient pas

1. **Rien n'est exécuté sans validation humaine**, même lancé par un déclencheur (règle CLAUDE.md §6). En
   `APPROVAL_MODE=every_step` (**défaut**, choix de l'utilisateur), l'exécution s'arrête sur `awaiting_approval` **dès l'étape 1**
   (lectures comprises) et rejoint la boîte **« À valider »** ; chaque étape suivante y revient à son tour. En `writes_only`,
   seules les écritures s'arrêtent et un workflow sans écriture va jusqu'au bout seul. L'interface affiche le rappel selon le
   réglage courant (lu dans `GET /api/settings`, champ `APPROVAL_MODE`).
2. **Jamais d'appel de modèle** (inchangé).
3. **Rien de rattrapé en rafale** : un horaire manqué pendant que Nexus était fermé donne **au plus une** exécution au
   redémarrage (statut de l'occurrence `missed` sinon) ; un trou d'événements (`gap: true`) ne relance rien en masse : le
   curseur repart du `next` rendu et un avertissement est journalisé sur le déclencheur.
4. **Garde-fous de débit** par déclencheur : au plus `max_runs_per_hour` exécutions (défaut 12, 1 à 120) ; au-delà, l'événement
   est compté `throttled` et ignoré. Au plus **une exécution en attente de validation** par déclencheur : tant qu'elle attend,
   les nouveaux déclenchements sont comptés `waiting` et ignorés (on ne remplit pas la boîte de doublons).
5. Les données des événements ne sont jamais journalisées au-delà de ce qui est stocké sur l'exécution (`trigger_event`).

## 1. Schémas

```ts
type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

type Schedule =
  | { kind: "interval"; every_minutes: number }                          // 5 à 1440
  | { kind: "daily"; at: string; days: Weekday[] };                      // "HH:MM" (24 h), days ≥ 1 ; fuseau = settings.timezone

interface EventFilter {           // condition sur l'événement (toutes doivent être vraies)
  path: string;                   // "data.to", "subject.id", "subject.label", "type"
  op: "eq" | "ne" | "in" | "contains" | "gt" | "gte" | "lt" | "lte" | "exists";
  value?: unknown;                // liste pour "in" ; absent pour "exists"
}

interface TriggerBase {
  id: string;                     // attribué par le serveur
  workflow_id: string;
  label: string;                  // "" autorisé
  enabled: boolean;
  params: Record<string, string>; // valeurs des paramètres du workflow ; gabarits {{event.…}} permis (déclencheur événement)
  max_runs_per_hour: number;      // 1 à 120, défaut 12
  created_at: string; updated_at: string;
  state: TriggerState;            // lecture seule
}
interface ScheduleTrigger extends TriggerBase { kind: "schedule"; schedule: Schedule }
interface EventTrigger extends TriggerBase {
  kind: "event";
  app: "viz" | "projets" | "tab";
  types: string[];                // 1 à 10 types d'événements déclarés par le manifeste de l'app
  filters: EventFilter[];         // 0 à 10
  debounce_seconds: number;       // 0 à 3600, défaut 0 : regroupe une rafale en un seul lancement (le dernier événement gagne)
}
type Trigger = ScheduleTrigger | EventTrigger;

interface TriggerState {
  next_fire_at: string | null;    // horaire : prochaine occurrence ; événement : null
  last_fired_at: string | null;
  last_run_id: string | null;
  last_run_status: string | null;
  cursor: number | null;          // événement : dernier seq traité
  counters: { fired: number; throttled: number; waiting: number; filtered: number; missed: number; errors: number };
  last_error: string | null;      // ex. « Atelier Projets injoignable » ; effacé au premier succès
  warning: string | null;         // ex. « Des événements ont été perdus (journal remis à zéro) »
}
```

### Gabarits `{{event.…}}` (déclencheur événement)
Dans `params` uniquement : `{{event.type}}`, `{{event.seq}}`, `{{event.at}}`, `{{event.subject.id}}`, `{{event.subject.label}}`,
`{{event.subject.kind}}`, `{{event.data.<chemin>}}`. Résolus en **texte** (les paramètres sont du texte). Chemin absent → `""`.
Dans les étapes, on continue d'utiliser `{{params.x}}` : le déclencheur alimente les paramètres.

## 2. API

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/workflows/{id}/triggers` | Liste des déclencheurs du workflow |
| POST | `/api/workflows/{id}/triggers` | Crée (corps = `Trigger` sans `id`, `workflow_id`, dates, `state`) → 201 |
| PUT | `/api/triggers/{trigger_id}` | Modifie (même corps) ; remet `state.counters` inchangés, recalcule `next_fire_at` |
| DELETE | `/api/triggers/{trigger_id}` | Supprime → 204 |
| POST | `/api/triggers/{trigger_id}/test` | Lance **une fois maintenant** comme le ferait le déclencheur ; corps facultatif `{event?: AtelierEvent}` (événement d'exemple) → `WorkflowRun` |
| GET | `/api/triggers/events-catalog` | `{ apps: { app, name, color, status, events: { type, label, fields: string[] }[] }[] }` — `fields` = chemins proposés pour les filtres, tirés du `data_schema` du manifeste (`data.to`, `data.project_id`…) plus `subject.id`, `subject.label` |
| GET | `/api/workflow-runs?status=awaiting_approval` | Boîte « À valider » (tous workflows), récents d'abord |
| GET | `/api/workflow-runs/inbox-count` | `{ awaiting_approval: number }` (badge de l'en-tête, interrogé toutes les 20 s) |

Validation (422, `detail` texte français) : workflow v2 seulement ; paramètres inconnus ; `types` non déclarés par le manifeste
(si l'app ne répond pas, accepté avec `state.last_error`) ; horaire invalide ; gabarit `{{event.…}}` hors `params`.
Supprimer un workflow supprime ses déclencheurs.

### Exécutions
`WorkflowRun.trigger` devient `"manual" | "schedule" | "event" | "test"`, plus :
```ts
trigger_id: string | null;
trigger_event: { app: string; seq: number; type: string; at: string; subject: { kind: string; id: string; label: string } } | null;
```
(jamais `data` de l'événement).

## 3. Moteur

- Tâche de fond démarrée dans le `lifespan` (désactivable : `TRIGGERS_ENABLED=false`, coupée dans `conftest`), horloge et
  sommeil **injectables** ; une méthode `tick()` fait un passage complet (les tests l'appellent sans attendre).
- Événements : un passage toutes les `TRIGGERS_POLL_SECONDS` (défaut 15). **Un seul curseur par application**, persisté
  (premier démarrage : curseur = `next` actuel, aucun historique rejoué), puis distribution aux déclencheurs actifs de l'app
  (types + filtres). Un déclencheur créé ne voit que les événements postérieurs à sa création.
- Horaire : `next_fire_at` calculé à l'enregistrement et après chaque occurrence ; fuseau `settings.timezone`
  (défaut `Europe/Paris`), changements d'heure gérés par `zoneinfo`.
- Lancement : même moteur que `POST /api/workflows/{id}/run`, paramètres = défauts du workflow ← `params` du déclencheur
  (gabarits résolus). Exécutions concurrentes d'un même workflow autorisées, mais séquentielles pour un même déclencheur.
- Persistance : migration `0007_workflow_triggers` (`down_revision="0006_workflow_runs"`) — tables `workflow_triggers`,
  `trigger_cursors` (app → seq), colonnes `trigger_id`, `trigger_event` sur `workflow_runs`.

## 4. Interface (repères)

- Éditeur graphe : panneau **Déclencheurs** (liste, ajout horaire / événement, activer / couper, état et compteurs,
  « Tester maintenant » avec un événement d'exemple rempli depuis le catalogue).
- En-tête : bouton **À valider** avec badge (`inbox-count`) → liste des exécutions en attente, carte de validation identique à
  celle de l'éditeur (résumé + entrée résolue, Autoriser / Refuser → `resume`), origine affichée (« Déclenché par
  projets.work_item.status_changed · Écrire la doc »).
- Historique des exécutions : colonne Origine (Manuel, Horaire, Événement, Test).
