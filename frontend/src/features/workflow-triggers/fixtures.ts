/**
 * Doubles du contrat docs/declencheurs-api.md pour les tests (aucun appel réseau).
 * Jamais importé par le code de l'interface.
 */

import type { EventTrigger, EventsCatalog, ScheduleTrigger, TriggerState } from "@/types/api";

export const eventsCatalogFixture: EventsCatalog = {
  apps: [
    {
      app: "projets",
      name: "Atelier Projets",
      color: "#94D82D",
      status: "ok",
      events: [
        {
          type: "projets.work_item.status_changed",
          label: "Statut changé",
          fields: ["data.from", "data.to", "data.project_id", "subject.id", "subject.label"],
        },
        { type: "projets.work_item.created", label: "Élément créé", fields: ["data.project_id", "subject.id", "subject.label"] },
        { type: "projets.milestone.reached", label: "Jalon atteint", fields: ["data.reached_at", "subject.id", "subject.label"] },
      ],
    },
    {
      app: "viz",
      name: "Atelier Viz",
      color: "#F2C811",
      status: "ok",
      events: [
        { type: "viz.dataset.refreshed", label: "Jeu actualisé", fields: ["data.rows", "data.trigger", "subject.id", "subject.label"] },
        { type: "viz.alert.triggered", label: "Alerte déclenchée", fields: ["data.dataset_id", "data.value", "subject.id", "subject.label"] },
      ],
    },
    { app: "tab", name: "Atelier Tab", color: "#21A366", status: "unreachable", events: [] },
  ],
};

export const stateFixture = (overrides: Partial<TriggerState> = {}): TriggerState => ({
  next_fire_at: null,
  last_fired_at: null,
  last_run_id: null,
  last_run_status: null,
  cursor: null,
  counters: { fired: 0, throttled: 0, waiting: 0, filtered: 0, missed: 0, errors: 0 },
  last_error: null,
  warning: null,
  ...overrides,
});

export const scheduleTriggerFixture = (overrides: Partial<ScheduleTrigger> = {}): ScheduleTrigger => ({
  id: "trg_1",
  workflow_id: "wf_1",
  label: "Bilan du matin",
  enabled: true,
  params: { jeu: "ventes" },
  max_runs_per_hour: 12,
  created_at: "2026-10-20T08:00:00Z",
  updated_at: "2026-10-20T08:00:00Z",
  state: stateFixture({ next_fire_at: "2026-10-22T06:00:00Z" }),
  kind: "schedule",
  schedule: { kind: "daily", at: "08:00", days: ["mon", "tue", "wed", "thu", "fri"] },
  ...overrides,
});

export const eventTriggerFixture = (overrides: Partial<EventTrigger> = {}): EventTrigger => ({
  id: "trg_2",
  workflow_id: "wf_1",
  label: "",
  enabled: true,
  params: { tache: "{{event.subject.id}}" },
  max_runs_per_hour: 12,
  created_at: "2026-10-20T08:00:00Z",
  updated_at: "2026-10-20T08:00:00Z",
  state: stateFixture({ cursor: 41 }),
  kind: "event",
  app: "projets",
  types: ["projets.work_item.status_changed"],
  filters: [{ path: "data.to", op: "eq", value: "CLOSED" }],
  debounce_seconds: 0,
  ...overrides,
});
