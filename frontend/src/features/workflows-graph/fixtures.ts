/**
 * Doubles du contrat docs/workflows-v2-api.md pour les tests (aucun appel réseau).
 * Jamais importé par le code de l'interface.
 */

import type { Catalog, CatalogEntry, SuiteMap, WorkflowRun, WorkflowStepV2 } from "@/types/api";

const entry = (e: Partial<CatalogEntry> & Pick<CatalogEntry, "uses" | "label">): CatalogEntry => ({
  source: e.uses.startsWith("tool:") ? "tool" : "node",
  app: null,
  description: "",
  kind: "read",
  input_schema: { type: "object", properties: {} },
  output_format: "json",
  output_hint: null,
  available: true,
  unavailable_reason: null,
  ...e,
});

export const catalogFixture: Catalog = {
  apps: [
    { app: "viz", name: "Atelier Viz", status: "ok", color: "#F2C811" },
    { app: "tab", name: "Atelier Tab", status: "ok", color: "#21A366" },
    { app: "projets", name: "Atelier Projets", status: "unreachable", color: "#94D82D" },
    { app: "cine", name: "Atelier Ciné", status: "no_contract", color: "#E64980" },
  ],
  entries: [
    entry({
      uses: "tool:data_via_query",
      app: "viz",
      label: "Interroger un jeu",
      description: "Agrégation sur un jeu Data Via.",
      output_format: "atelier-table/1",
      output_hint: {
        columns: [
          { key: "region", label: "Région", type: "string" },
          { key: "ca", label: "Chiffre d'affaires", type: "number" },
        ],
      },
      input_schema: {
        type: "object",
        properties: { dataset_id: { type: "string", title: "Jeu de données" }, limit: { type: "integer" } },
        required: ["dataset_id"],
      },
    }),
    entry({
      uses: "node:projets/work_items.list",
      app: "projets",
      label: "Lister les tâches",
      output_format: "atelier-table/1",
      output_hint: { columns: [{ key: "titre", label: "Titre", type: "string" }] },
    }),
    entry({
      uses: "node:projets/milestones.list",
      app: "projets",
      label: "Jalons",
      available: false,
      unavailable_reason: "Atelier Projets ne répond pas.",
    }),
    entry({
      uses: "node:projets/work_items.create",
      app: "projets",
      label: "Créer une tâche",
      description: "Crée un élément de travail.",
      kind: "write",
      output_hint: { fields: ["id", "url"] },
      input_schema: {
        type: "object",
        properties: {
          title: { type: "string" },
          type: { enum: ["TASK", "BUG"] },
          estimate: { type: "number" },
          urgent: { type: "boolean" },
          tags: { type: "array", items: { type: "string" } },
          meta: { type: "object" },
        },
        required: ["title"],
      },
    }),
    entry({ uses: "node:tab/rows.add", app: "tab", label: "Ajouter des lignes", kind: "write" }),
    entry({ uses: "node:tab/rows.delete", app: "tab", label: "Supprimer des lignes", kind: "destructive" }),
    entry({ uses: "tool:publish_artifact", app: null, label: "Publier un artefact", output_format: "text" }),
  ],
};

export const step = (id: string, uses: string, needs: string[] = [], input: Record<string, unknown> = {}): WorkflowStepV2 => ({
  id,
  label: "",
  uses,
  input,
  needs,
  when: null,
  on_error: "stop",
  position: null,
});

/** lire (Viz) → creer (Projets), plus une branche ajouter (Tab) depuis lire. */
export const diamondSteps: WorkflowStepV2[] = [
  step("lire", "tool:data_via_query", [], { dataset_id: "{{params.jeu}}" }),
  step("taches", "node:projets/work_items.list"),
  step("creer", "node:projets/work_items.create", ["lire", "taches"], {
    title: "CA {{steps.lire.data.rows[0].region}}",
  }),
  step("ajouter", "node:tab/rows.add", ["lire"]),
];

export const runFixture = (overrides: Partial<WorkflowRun> = {}): WorkflowRun => ({
  id: "run_1",
  workflow_id: "wf_1",
  status: "running",
  message: "",
  params: { jeu: "ventes" },
  trigger: "manual",
  steps: [
    { id: "lire", uses: "tool:data_via_query", label: "", status: "ok", input: {}, content: "", data: null, error_code: null, started_at: null, ended_at: null },
    { id: "taches", uses: "node:projets/work_items.list", label: "", status: "pending", input: null, content: "", data: null, error_code: null, started_at: null, ended_at: null },
    { id: "creer", uses: "node:projets/work_items.create", label: "", status: "pending", input: null, content: "", data: null, error_code: null, started_at: null, ended_at: null },
    { id: "ajouter", uses: "node:tab/rows.add", label: "", status: "pending", input: null, content: "", data: null, error_code: null, started_at: null, ended_at: null },
  ],
  artifacts: [],
  pending: [],
  created_at: "2026-10-21T10:00:00Z",
  updated_at: "2026-10-21T10:00:01Z",
  ...overrides,
});

export const suiteMapFixture: SuiteMap = {
  apps: [
    {
      app: "viz",
      name: "Atelier Viz",
      color: "#F2C811",
      status: "ok",
      transport: "http",
      actions: [
        { id: "datasets.query", label: "Interroger un jeu", kind: "read", output_format: "atelier-table/1" },
        { id: "datasets.refresh", label: "Actualiser un jeu", kind: "write", output_format: "json" },
      ],
      events: [{ type: "viz.dataset.refreshed", label: "Jeu actualisé" }],
      nexus_tools: [{ name: "data_via_query", kind: "read", toolset: "data_via" }],
      agents: [{ name: "data_analyst", display_name: "Data Analyst", icon: "chart-column", toolsets: ["data_via"], writes: false }],
    },
    {
      app: "projets",
      name: "Atelier Projets",
      color: "#94D82D",
      status: "unreachable",
      transport: "http",
      actions: [
        { id: "work_items.create", label: "Créer une tâche", kind: "write", output_format: "json" },
        { id: "work_items.delete", label: "Supprimer une tâche", kind: "destructive", output_format: "json" },
        { id: "work_items.list", label: "Lister les tâches", kind: "read", output_format: "atelier-table/1" },
      ],
      events: [],
      nexus_tools: [{ name: "projets_create_work_item", kind: "write", toolset: "projets" }],
      agents: [{ name: "chef_projet", display_name: "Chef de projet", icon: "list-checks", toolsets: ["projets"], writes: true }],
    },
    {
      app: "tab",
      name: "Atelier Tab",
      color: "#21A366",
      status: "ok",
      transport: "mcp",
      actions: [],
      events: [],
      nexus_tools: [],
      agents: [],
    },
  ],
  flows: [
    { from: "tab", to: "projets", label: "Import DataFlow", via: "webhook" },
    { from: "projets", to: "viz", label: "Jeux de données", via: "HTTP" },
    { from: "nexus", to: "projets", label: "Écritures validées", via: "HTTP" },
    { from: "viz", to: "nexus", label: "Lecture", via: "HTTP" },
  ],
  workflows: [
    { id: "wf_1", title: "CA → tâches", apps: ["viz", "projets"] },
    { id: "wf_2", title: "Export Tab", apps: ["tab"] },
  ],
};
