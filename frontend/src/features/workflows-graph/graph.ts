/**
 * Graphe d'un workflow v2 : étapes ↔ nœuds / arêtes (React Flow), ancêtres, ordre topologique,
 * connexions sans cycle, renommage, mise en page en couches et état d'exécution fusionné sur le
 * graphe. Logique pure (aucun import React), testée dans graph.test.ts.
 */

import type { Edge, Node } from "@xyflow/react";

import type {
  ActionKind,
  CatalogEntry,
  OutputFormat,
  StepPosition,
  StepRunStatus,
  ValidationError,
  WorkflowRun,
  WorkflowStepV2,
} from "@/types/api";

import { appKey, parseUses, usesLabel } from "./catalog";
import { renameStepRefs } from "./refs";

export const STEP_ID = /^[a-z][a-z0-9_]{0,39}$/;
export const MAX_STEPS = 30;
export const MAX_PARAMS = 10;

// ─── Parcours ────────────────────────────────────────────────────

/** Étapes amont de `id`, transitivement (via `needs`), sans `id` lui-même. */
export function ancestors(steps: WorkflowStepV2[], id: string): Set<string> {
  const byId = new Map(steps.map((s) => [s.id, s]));
  const seen = new Set<string>();
  const stack = [...(byId.get(id)?.needs ?? [])];
  while (stack.length) {
    const current = stack.pop()!;
    if (seen.has(current) || current === id) continue;
    seen.add(current);
    stack.push(...(byId.get(current)?.needs ?? []));
  }
  return seen;
}

/** Étapes aval de `id` (celles qui en dépendent, transitivement). */
export function descendants(steps: WorkflowStepV2[], id: string): Set<string> {
  const seen = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const current = stack.pop()!;
    for (const step of steps) {
      if (step.needs.includes(current) && !seen.has(step.id) && step.id !== id) {
        seen.add(step.id);
        stack.push(step.id);
      }
    }
  }
  return seen;
}

/**
 * Ordre d'exécution (Kahn, stable : à égalité, l'ordre de la liste). `needs` vers une étape
 * inconnue : ignoré. null si le graphe a un cycle.
 */
export function topoOrder(steps: WorkflowStepV2[]): string[] | null {
  const ids = new Set(steps.map((s) => s.id));
  const pending = new Map(steps.map((s) => [s.id, new Set(s.needs.filter((n) => ids.has(n) && n !== s.id))]));
  const selfLoop = steps.some((s) => s.needs.includes(s.id));
  const order: string[] = [];
  while (order.length < steps.length) {
    const next = steps.find((s) => !order.includes(s.id) && pending.get(s.id)!.size === 0);
    if (!next) return null;
    order.push(next.id);
    for (const deps of pending.values()) deps.delete(next.id);
  }
  return selfLoop ? null : order;
}

/** Étapes prises dans un cycle (ou qui en dépendent), pour les signaler sur le graphe. */
export function cyclicSteps(steps: WorkflowStepV2[]): string[] {
  const ids = new Set(steps.map((s) => s.id));
  const pending = new Map(steps.map((s) => [s.id, new Set(s.needs.filter((n) => ids.has(n)))]));
  const done = new Set<string>();
  let progress = true;
  while (progress) {
    progress = false;
    for (const step of steps) {
      if (done.has(step.id) || pending.get(step.id)!.size > 0) continue;
      done.add(step.id);
      progress = true;
      for (const deps of pending.values()) deps.delete(step.id);
    }
  }
  return steps.filter((s) => !done.has(s.id)).map((s) => s.id);
}

/** Relier `source` → `target` (target attend source) créerait-il un cycle ? */
export const wouldCreateCycle = (steps: WorkflowStepV2[], source: string, target: string): boolean =>
  source === target || ancestors(steps, source).has(target);

// ─── Modifications ───────────────────────────────────────────────

/** Ajoute l'arête `source` → `target` ; refusée (null) si elle existe, vise une étape inconnue ou ferme un cycle. */
export function connect(steps: WorkflowStepV2[], source: string, target: string): WorkflowStepV2[] | null {
  const to = steps.find((s) => s.id === target);
  if (!to || !steps.some((s) => s.id === source)) return null;
  if (to.needs.includes(source) || wouldCreateCycle(steps, source, target)) return null;
  return steps.map((s) => (s.id === target ? { ...s, needs: [...s.needs, source] } : s));
}

export const disconnect = (steps: WorkflowStepV2[], source: string, target: string): WorkflowStepV2[] =>
  steps.map((s) => (s.id === target ? { ...s, needs: s.needs.filter((n) => n !== source) } : s));

/** Retire des étapes et les arêtes qui les citent (les gabarits restent : la validation les signale). */
export function removeSteps(steps: WorkflowStepV2[], ids: Iterable<string>): WorkflowStepV2[] {
  const gone = new Set(ids);
  return steps.filter((s) => !gone.has(s.id)).map((s) => ({ ...s, needs: s.needs.filter((n) => !gone.has(n)) }));
}

/** Renomme une étape : `needs` et gabarits `{{steps.ancien…}}` suivent. */
export function renameStep(steps: WorkflowStepV2[], from: string, to: string): WorkflowStepV2[] {
  if (from === to) return steps;
  return steps.map((s) => ({
    ...s,
    id: s.id === from ? to : s.id,
    needs: s.needs.map((n) => (n === from ? to : n)),
    input: renameStepRefs(s.input, from, to),
    when: s.when ? renameStepRefs(s.when, from, to) : s.when,
  }));
}

/** Identifiant libre et valide tiré du nom de l'action (« work_items.create » → « create »). */
export function newStepId(steps: WorkflowStepV2[], uses: string): string {
  const { name } = parseUses(uses);
  const last = name.split(/[./]/).filter(Boolean).pop() ?? "etape";
  let base = last
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^[^a-z]+/, "")
    .replace(/_+$/, "")
    .slice(0, 34);
  if (!base) base = "etape";
  const taken = new Set(steps.map((s) => s.id));
  if (!taken.has(base)) return base;
  for (let i = 2; ; i++) {
    const candidate = `${base}_${i}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/**
 * Nouvelle étape (entrée vide, arrêt en cas d'erreur). Libellé vide : le nœud affiche celui du
 * catalogue. `after` : l'étape attend celle-ci.
 */
export function createStep(
  steps: WorkflowStepV2[],
  uses: string,
  position: StepPosition | null,
  after: string | null = null,
): WorkflowStepV2 {
  return {
    id: newStepId(steps, uses),
    label: "",
    uses,
    input: {},
    needs: after && steps.some((s) => s.id === after) ? [after] : [],
    when: null,
    on_error: "stop",
    position,
  };
}

/** Position d'une étape ajoutée par clic : à droite de `after`, sinon après la dernière colonne. */
export function nextPosition(steps: WorkflowStepV2[], after: string | null): StepPosition {
  const anchor = after ? steps.find((s) => s.id === after)?.position : null;
  if (anchor) {
    const x = anchor.x + LAYOUT.columnWidth;
    const below = steps.filter((s) => s.position && Math.abs(s.position.x - x) < LAYOUT.nodeWidth / 2);
    const y = below.length ? Math.max(anchor.y, ...below.map((s) => s.position!.y + LAYOUT.rowHeight)) : anchor.y;
    return { x, y };
  }
  const placed = steps.filter((s) => s.position);
  if (!placed.length) return { x: 0, y: 0 };
  return { x: Math.max(...placed.map((s) => s.position!.x)) + LAYOUT.columnWidth, y: 0 };
}

// ─── Mise en page ────────────────────────────────────────────────

export const LAYOUT = { columnWidth: 300, rowHeight: 130, nodeWidth: 240 } as const;

/**
 * Couches topologiques : chaque étape dans la colonne « plus long chemin depuis une racine »,
 * les colonnes centrées verticalement. Cycle : à la suite, sur une ligne.
 */
export function layoutSteps(steps: WorkflowStepV2[]): Record<string, StepPosition> {
  const order = topoOrder(steps);
  const positions: Record<string, StepPosition> = {};
  if (!order) {
    steps.forEach((s, i) => (positions[s.id] = { x: i * LAYOUT.columnWidth, y: 0 }));
    return positions;
  }
  const byId = new Map(steps.map((s) => [s.id, s]));
  const layer = new Map<string, number>();
  for (const id of order) {
    const needs = byId.get(id)!.needs.filter((n) => layer.has(n));
    layer.set(id, needs.length ? Math.max(...needs.map((n) => layer.get(n)!)) + 1 : 0);
  }
  const columns: string[][] = [];
  for (const id of order) (columns[layer.get(id)!] ??= []).push(id);
  const tallest = Math.max(...columns.map((c) => c.length));
  columns.forEach((column, x) => {
    const offset = ((tallest - column.length) * LAYOUT.rowHeight) / 2;
    column.forEach((id, y) => {
      positions[id] = { x: x * LAYOUT.columnWidth, y: offset + y * LAYOUT.rowHeight };
    });
  });
  return positions;
}

/** Applique la mise en page aux étapes. `onlyMissing` : ne place que celles sans position. */
export function applyLayout(steps: WorkflowStepV2[], onlyMissing = false): WorkflowStepV2[] {
  if (onlyMissing && steps.every((s) => s.position)) return steps;
  const positions = layoutSteps(steps);
  return steps.map((s) => (onlyMissing && s.position ? s : { ...s, position: positions[s.id] ?? null }));
}

// ─── État d'exécution ────────────────────────────────────────────

/** Statut affiché d'une étape : celui du moteur, ou « running » pour celle qui s'exécute. */
export type StepDisplayStatus = StepRunStatus | "running";

export interface StepRunView {
  status: StepDisplayStatus;
  errorCode: string | null;
}

const TERMINAL: StepRunStatus[] = ["ok", "error", "refused", "skipped"];

/**
 * État de chaque étape pendant ou après une exécution. Tant que l'exécution tourne, une étape
 * encore « pending » dont toutes les étapes amont sont terminées est celle en cours.
 */
export function mergeRunState(steps: WorkflowStepV2[], run: WorkflowRun | null): Record<string, StepRunView> {
  if (!run) return {};
  const runs = new Map(run.steps.map((s) => [s.id, s]));
  const views: Record<string, StepRunView> = {};
  for (const step of steps) {
    const sr = runs.get(step.id);
    if (!sr) continue;
    let status: StepDisplayStatus = sr.status;
    if (run.status === "running" && sr.status === "pending") {
      const ready = step.needs.every((n) => {
        const up = runs.get(n);
        return !up || TERMINAL.includes(up.status);
      });
      if (ready) status = "running";
    }
    views[step.id] = { status, errorCode: sr.error_code };
  }
  return views;
}

export const isRunActive = (run: WorkflowRun | null | undefined): boolean => run?.status === "running";

// ─── Nœuds et arêtes React Flow ──────────────────────────────────

export interface StepNodeData extends Record<string, unknown> {
  stepId: string;
  label: string;
  uses: string;
  /** Application (couleur, icône) ; « nexus » pour un outil système */
  app: string;
  appName: string;
  color: string | null;
  kind: ActionKind | null;
  outputFormat: OutputFormat | null;
  /** Étape inconnue du catalogue, ou indisponible (raison) */
  unknown: boolean;
  unavailable: string | null;
  conditional: boolean;
  continueOnError: boolean;
  errors: ValidationError[];
  run: StepRunView | null;
}

export type StepNode = Node<StepNodeData, "step">;

export interface GraphContext {
  catalog: Map<string, CatalogEntry>;
  apps?: Map<string, { name: string; color: string }>;
  errors?: ValidationError[];
  run?: Record<string, StepRunView>;
  /** Étapes sélectionnées sur le graphe */
  selected?: ReadonlySet<string>;
  /** Dimensions mesurées par React Flow (sinon il masque les nœuds le temps de les remesurer) */
  measured?: Record<string, { width: number; height: number }>;
}

export function stepNodeData(step: WorkflowStepV2, ctx: GraphContext): StepNodeData {
  const entry = ctx.catalog.get(step.uses) ?? null;
  const parsed = parseUses(step.uses);
  const app = appKey(entry ? entry.app : parsed.app);
  const meta = ctx.apps?.get(app);
  return {
    stepId: step.id,
    label: step.label || usesLabel(step.uses, entry),
    uses: step.uses,
    app,
    appName: meta?.name ?? (app === "nexus" ? "Nexus" : app),
    color: meta?.color ?? null,
    kind: entry?.kind ?? null,
    outputFormat: entry?.output_format ?? null,
    unknown: !entry,
    unavailable: entry && !entry.available ? (entry.unavailable_reason ?? "indisponible") : null,
    conditional: !!step.when,
    continueOnError: step.on_error === "continue",
    errors: (ctx.errors ?? []).filter((e) => e.step_id === step.id),
    run: ctx.run?.[step.id] ?? null,
  };
}

/** Étapes → nœuds (position enregistrée, sinon mise en page en couches). */
export function stepsToNodes(steps: WorkflowStepV2[], ctx: GraphContext): StepNode[] {
  const fallback = steps.every((s) => s.position) ? {} : layoutSteps(steps);
  return steps.map((step) => {
    const data = stepNodeData(step, ctx);
    const measured = ctx.measured?.[step.id];
    return {
      id: step.id,
      type: "step",
      position: step.position ?? fallback[step.id] ?? { x: 0, y: 0 },
      data,
      selected: ctx.selected?.has(step.id) ?? false,
      ...(measured ? { measured } : {}),
      ariaLabel: `Étape ${data.label} (${step.id})`,
    };
  });
}

export const edgeId = (source: string, target: string) => `${source}->${target}`;

export function stepsToEdges(
  steps: WorkflowStepV2[],
  run?: Record<string, StepRunView>,
  selected?: ReadonlySet<string>,
): Edge[] {
  const ids = new Set(steps.map((s) => s.id));
  return steps.flatMap((step) =>
    step.needs
      .filter((source) => ids.has(source))
      .map((source) => ({
        id: edgeId(source, step.id),
        source,
        target: step.id,
        animated: run?.[step.id]?.status === "running",
        selected: selected?.has(edgeId(source, step.id)) ?? false,
        ariaLabel: `Liaison ${source} vers ${step.id}`,
      })),
  );
}

export const stepsToGraph = (steps: WorkflowStepV2[], ctx: GraphContext) => ({
  nodes: stepsToNodes(steps, ctx),
  edges: stepsToEdges(steps, ctx.run),
});

/**
 * Nœuds / arêtes → étapes : positions des nœuds, `needs` reconstruits depuis les arêtes (dans
 * l'ordre existant, puis les nouvelles). Étapes sans nœud : retirées.
 */
export function graphToSteps(
  steps: WorkflowStepV2[],
  nodes: Pick<Node, "id" | "position">[],
  edges: Pick<Edge, "source" | "target">[],
): WorkflowStepV2[] {
  const positions = new Map(nodes.map((n) => [n.id, n.position]));
  return steps
    .filter((s) => positions.has(s.id))
    .map((step) => {
      const sources = edges.filter((e) => e.target === step.id && positions.has(e.source)).map((e) => e.source);
      const needs = [...step.needs.filter((n) => sources.includes(n)), ...sources.filter((n) => !step.needs.includes(n))];
      const p = positions.get(step.id)!;
      return { ...step, needs: [...new Set(needs)], position: { x: Math.round(p.x), y: Math.round(p.y) } };
    });
}
