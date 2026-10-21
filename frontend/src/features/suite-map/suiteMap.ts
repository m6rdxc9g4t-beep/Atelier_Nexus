/**
 * Carte de la suite (GET /api/suite/map, GET /api/suite/events) : entrées / sorties de chaque
 * application, flux entre apps, workflows concernés, fil des derniers événements, et
 * correspondance action ↔ étape de workflow. Logique pure, testée dans suiteMap.test.ts.
 */

import { isTriggerApp } from "@/features/workflow-triggers/form";
import type { EditorTarget } from "@/stores/useWorkflowStudioStore";
import type { AtelierEvent, SuiteEventsEntry, SuiteFlow, SuiteMap, SuiteMapAction, SuiteMapApp } from "@/types/api";

export interface AppColumns {
  /** Actions qui modifient l'application (write, destructive) */
  inputs: SuiteMapAction[];
  /** Actions de lecture (sorties), avec leur format */
  outputs: SuiteMapAction[];
}

export function splitActions(app: Pick<SuiteMapApp, "actions">): AppColumns {
  return {
    inputs: app.actions.filter((a) => a.kind !== "read"),
    outputs: app.actions.filter((a) => a.kind === "read"),
  };
}

/** Étape de workflow correspondant à une action du manifeste. */
export const actionUses = (app: string, actionId: string) => `node:${app}/${actionId}`;

export interface TriggerChoice {
  label: string;
  target: EditorTarget;
}

/**
 * « + » sur un événement : nouveau workflow de suite avec un déclencheur événement prérempli, et,
 * si un workflow enregistré a été ouvert, l'ajout du déclencheur à celui-ci. Vide si l'application
 * ne peut pas déclencher de workflow (contrat : viz, projets, tab).
 */
export function triggerChoices(app: string, type: string, last: { id: string; title: string } | null): TriggerChoice[] {
  if (!isTriggerApp(app)) return [];
  const trigger = { app, types: [type] };
  const choices: TriggerChoice[] = [
    { label: "Nouveau workflow déclenché par cet événement", target: { kind: "new", agent: null, trigger } },
  ];
  if (last) choices.push({ label: `Ajouter à « ${last.title} »`, target: { kind: "open", id: last.id, panel: "triggers", trigger } });
  return choices;
}

/** Flux qui partent de / arrivent à une application. */
export function flowsOf(flows: SuiteFlow[], app: string): { outgoing: SuiteFlow[]; incoming: SuiteFlow[] } {
  return { outgoing: flows.filter((f) => f.from === app), incoming: flows.filter((f) => f.to === app) };
}

export const workflowsOf = (map: SuiteMap, app: string) => map.workflows.filter((w) => w.apps.includes(app));

/** Applications des flux, dans l'ordre de la carte puis celles vues seulement dans les flux (Nexus). */
export function flowNodes(map: SuiteMap): string[] {
  const ids = map.apps.map((a) => a.app);
  for (const f of map.flows) for (const id of [f.from, f.to]) if (!ids.includes(id)) ids.push(id);
  return ids;
}

export interface FlowLayout {
  width: number;
  height: number;
  nodes: { id: string; x: number; y: number }[];
  edges: (SuiteFlow & { path: string; labelX: number; labelY: number; key: string })[];
}

/**
 * Schéma des flux : Nexus au centre, les applications en cercle autour, arêtes courbes (les
 * allers-retours entre deux apps ne se superposent pas). Coordonnées en unités SVG.
 */
export function layoutFlows(map: SuiteMap, size = 420): FlowLayout {
  const ids = flowNodes(map);
  const center = size / 2;
  const radius = size / 2 - 60;
  const ring = ids.filter((id) => id !== "nexus");
  const nodes = ids.map((id) => {
    if (id === "nexus" && ring.length !== ids.length) return { id, x: center, y: center };
    const i = ring.indexOf(id);
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(ring.length, 1);
    return { id, x: Math.round(center + radius * Math.cos(angle)), y: Math.round(center + radius * Math.sin(angle)) };
  });
  const at = new Map(nodes.map((n) => [n.id, n]));
  const edges = map.flows.flatMap((flow, i) => {
    const a = at.get(flow.from);
    const b = at.get(flow.to);
    if (!a || !b || a === b) return [];
    // Courbe à droite du sens de parcours : A→B et B→A restent distinctes
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const bend = Math.min(40, len / 4);
    const cx = Math.round(mx + (-dy / len) * bend);
    const cy = Math.round(my + (dx / len) * bend);
    // On s'arrête au bord des pastilles (rayon 22)
    const trim = (p: { x: number; y: number }, toward: { x: number; y: number }) => {
      const vx = toward.x - p.x;
      const vy = toward.y - p.y;
      const l = Math.hypot(vx, vy) || 1;
      return { x: Math.round(p.x + (vx / l) * 24), y: Math.round(p.y + (vy / l) * 24) };
    };
    const start = trim(a, { x: cx, y: cy });
    const end = trim(b, { x: cx, y: cy });
    return [
      {
        ...flow,
        key: `${flow.from}-${flow.to}-${i}`,
        path: `M ${start.x} ${start.y} Q ${cx} ${cy} ${end.x} ${end.y}`,
        labelX: Math.round((start.x + 2 * cx + end.x) / 4),
        labelY: Math.round((start.y + 2 * cy + end.y) / 4),
      },
    ];
  });
  return { width: size, height: size, nodes, edges };
}

export interface FeedEvent extends AtelierEvent {
  app: string;
}

/** Fil « Derniers événements » : toutes les apps fusionnées, les plus récents d'abord. */
export function mergeEvents(entries: SuiteEventsEntry[], limit = 50): FeedEvent[] {
  const all = entries.flatMap((e) => e.events.map((ev) => ({ ...ev, app: e.app })));
  const time = (ev: FeedEvent) => {
    const t = new Date(ev.at).getTime();
    return Number.isFinite(t) ? t : 0;
  };
  return all.sort((a, b) => time(b) - time(a) || b.seq - a.seq).slice(0, limit);
}

/** Applications dont le fil a perdu des événements ou ne répond pas. */
export const feedWarnings = (entries: SuiteEventsEntry[]): { app: string; text: string }[] =>
  entries.flatMap((e) => {
    if (e.gap) return [{ app: e.app, text: "des événements ont été perdus (relisez l'état de l'application)" }];
    if (e.status && e.status !== "ok") return [{ app: e.app, text: e.status }];
    return [];
  });

/** Libellé d'un type d'événement : celui du manifeste, sinon le type technique. */
export function eventLabel(map: SuiteMap | null, app: string, type: string): string {
  return map?.apps.find((a) => a.app === app)?.events.find((e) => e.type === type)?.label ?? type;
}

const TRANSPORT_LABEL = { http: "HTTP", mcp: "MCP", files: "fichiers" } as const;
export const transportLabel = (t: SuiteMapApp["transport"]) => (t ? TRANSPORT_LABEL[t] : "—");
