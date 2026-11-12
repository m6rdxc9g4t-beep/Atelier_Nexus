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

/** Le hub : en tête du schéma, jamais dans une colonne d'applications. */
const HUB = "nexus";

/**
 * Échanges de la carte : ceux du hub, plus ceux que les workflows ouvrent. Une application dont le
 * manifeste déclare des actions se pilote par des étapes `node:<app>/<action>` même sans outil
 * Nexus : ses écritures (validées à chaque exécution) et ses lectures passent alors « par workflow ».
 */
export function suiteFlows(map: SuiteMap): SuiteFlow[] {
  const flows = [...map.flows];
  const has = (from: string, to: string) => flows.some((f) => f.from === from && f.to === to);
  for (const app of map.apps) {
    const { inputs, outputs } = splitActions(app);
    if (inputs.length > 0 && !has(HUB, app.app)) flows.push({ from: HUB, to: app.app, label: "Écritures validées", via: "workflow" });
    if (outputs.length > 0 && !has(app.app, HUB)) flows.push({ from: app.app, to: HUB, label: "Lecture", via: "workflow" });
  }
  return flows;
}

/** Identifiant technique d'une action, écrit sous son libellé : une lecture dit aussi son format de sortie. */
export const actionDetail = (action: Pick<SuiteMapAction, "id" | "kind" | "output_format">) =>
  action.kind === "read" && action.output_format ? `${action.id} · ${action.output_format}` : action.id;

type MapTool = SuiteMapApp["nexus_tools"][number];

/**
 * Outils Nexus d'une application, rangés par boîte (dans l'ordre où le hub les donne) : la boîte
 * s'écrit une fois en tête de son groupe plutôt que sur chaque ligne.
 */
export function toolsByBox(tools: MapTool[]): { toolset: string; tools: MapTool[] }[] {
  const groups: { toolset: string; tools: MapTool[] }[] = [];
  for (const tool of tools) {
    const group = groups.find((g) => g.toolset === tool.toolset);
    if (group) group.tools.push(tool);
    else groups.push({ toolset: tool.toolset, tools: [tool] });
  }
  return groups;
}

/** Nom court d'une application sur le schéma (« Atelier Tab » → « Tab »). */
export const shortName = (map: Pick<SuiteMap, "apps">, id: string) =>
  id === HUB ? "Nexus" : (map.apps.find((a) => a.app === id)?.name ?? id).replace(/^Atelier /, "");

// ─── Schéma des flux ─────────────────────────────────────────────

export interface FlowBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FlowNode {
  id: string;
  /** Centre de l'icône (carré de 40) */
  x: number;
  y: number;
  hub: boolean;
  name: string;
  /** Nom : sous l'icône (centré) ou, pour Nexus, à sa droite */
  label: { x: number; y: number; anchor: "middle" | "start" };
  /** Place occupée : l'icône, puis le nom */
  boxes: [FlowBox, FlowBox];
}

export interface FlowLink {
  key: string;
  /** Les deux applications reliées (un seul lien par paire, quel que soit le nombre de flux) */
  a: string;
  b: string;
  /** Flux portés par le lien, dans les deux sens */
  flows: SuiteFlow[];
  path: string;
  /** Pointes : une par sens présent (triangles pleins) */
  heads: string[];
  /** Libellé (échanges entre applications seulement : avec Nexus, les pointes disent le sens) */
  label: { text: string; x: number; y: number; anchor: "end"; box: FlowBox } | null;
  /** Points du tracé, pour vérifier qu'il ne traverse ni icône ni texte */
  points: { x: number; y: number }[];
}

export interface FlowLayout {
  width: number;
  height: number;
  /** Rail de Nexus : les liens avec le hub y arrivent chacun à sa hauteur */
  rail: { x: number; y1: number; y2: number } | null;
  nodes: FlowNode[];
  links: FlowLink[];
}

/** Largeur estimée d'un texte de 12 px (Inter) : majorée, pour réserver sa place sans le mesurer. */
export const textWidth = (text: string, perChar = 6.6) => Math.ceil(text.length * perChar);

export const boxesOverlap = (a: FlowBox, b: FlowBox) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

const TILE = 20; // demi-côté de l'icône
const NAME_H = 16;
const ROW = 68; // pas d'une colonne sans lien vertical
const ROW_LINKED = 104; // pas d'une colonne dont les voisines sont reliées (flèche + libellé entre deux)
const HEAD = 7;

/** Pointe pleine dont le sommet est en (x, y) et qui regarde vers (dx, dy). */
function arrowHead(x: number, y: number, dx: number, dy: number): string {
  const bx = x - dx * HEAD;
  const by = y - dy * HEAD;
  const w = HEAD / 2;
  return `M ${x} ${y} L ${bx - dy * w} ${by + dx * w} L ${bx + dy * w} ${by - dx * w} Z`;
}

/**
 * Ordre de la colonne des applications qui échangent entre elles : les sources d'abord, et une
 * application reliée à la précédente passe devant (le plus de liens possibles entre voisines).
 */
function chainOrder(ids: string[], flows: SuiteFlow[]): string[] {
  const left = [...ids];
  const order: string[] = [];
  const linked = (a: string, b: string) => flows.some((f) => (f.from === a && f.to === b) || (f.from === b && f.to === a));
  while (left.length > 0) {
    const free = left.filter((id) => !flows.some((f) => f.to === id && f.from !== id && left.includes(f.from)));
    const pool = free.length > 0 ? free : left;
    const prev = order.at(-1);
    const next = (prev !== undefined && pool.find((id) => linked(prev, id))) || pool[0]!;
    order.push(next);
    left.splice(left.indexOf(next), 1);
  }
  return order;
}

/**
 * Schéma des flux, à la largeur disponible (texte toujours à 12 px, de 320 à 560 px) : Nexus en
 * tête d'un rail vertical ; à gauche, en colonne, les applications qui échangent entre elles
 * (flèches verticales, libellé à leur gauche ; un lien qui saute une ligne passe par un couloir
 * en marge) ; à droite les autres. Chaque application rejoint le rail à sa hauteur : un seul lien
 * par paire, le sens donné par les pointes (vers Nexus : lecture ; vers l'application : écritures).
 * Les libellés sont posés à la première place libre : jamais sur une icône, un nom ou un autre
 * libellé. Coordonnées en unités SVG (= pixels).
 */
export function layoutFlows(map: SuiteMap, available = 480): FlowLayout {
  const flows = suiteFlows(map).filter((f) => f.from !== f.to);
  const ids = flowNodes({ ...map, flows });
  const hasHub = ids.includes(HUB) && flows.some((f) => f.from === HUB || f.to === HUB);
  const apps = ids.filter((id) => id !== HUB || !hasHub);
  const between = flows.filter((f) => apps.includes(f.from) && apps.includes(f.to));
  const chained = apps.filter((id) => between.some((f) => f.from === id || f.to === id));
  // Sans échange entre applications : deux colonnes égales autour du rail
  const leftIds = chained.length > 0 ? chainOrder(chained, between) : apps.slice(0, Math.ceil(apps.length / 2));
  const rightIds = apps.filter((id) => !leftIds.includes(id));

  // Un lien par paire d'applications
  const pairs = new Map<string, { a: string; b: string; flows: SuiteFlow[] }>();
  for (const f of flows) {
    const [a, b] = f.from === HUB || (f.to !== HUB && ids.indexOf(f.from) > ids.indexOf(f.to)) ? [f.to, f.from] : [f.from, f.to];
    const key = `${a}~${b}`;
    const pair = pairs.get(key) ?? { a, b, flows: [] };
    pair.flows.push(f);
    pairs.set(key, pair);
  }
  const appPairs = [...pairs.values()].filter((p) => p.b !== HUB || !hasHub);
  const labelOf = (p: { flows: SuiteFlow[] }) => [...new Set(p.flows.map((f) => f.label))].join(" · ");
  const row = (id: string) => leftIds.indexOf(id);
  const skips = appPairs.filter((p) => Math.abs(row(p.a) - row(p.b)) > 1).sort((p, q) => Math.abs(row(p.a) - row(p.b)) - Math.abs(row(q.a) - row(q.b)));

  // Couloirs des liens qui sautent des lignes : les plus courts à l'intérieur, jamais deux sur la même portée
  const lanes: { top: number; bottom: number }[][] = [];
  const laneOf = new Map<(typeof skips)[number], number>();
  for (const p of skips) {
    const top = Math.min(row(p.a), row(p.b));
    const bottom = Math.max(row(p.a), row(p.b));
    let lane = lanes.findIndex((spans) => spans.every((s) => bottom < s.top || top > s.bottom));
    if (lane < 0) lane = lanes.push([]) - 1;
    lanes[lane]!.push({ top, bottom });
    laneOf.set(p, lane);
  }

  // Largeurs : la marge de gauche loge couloirs et libellés ; le reste va aux liens avec le rail
  const lanesWidth = lanes.length > 0 ? 6 + 10 * lanes.length : 0;
  const labelWidth = Math.max(0, ...appPairs.map((p) => textWidth(labelOf(p))));
  const nameHalf = (id: string) => Math.ceil(textWidth(shortName(map, id), 7) / 2);
  const overhang = (list: string[]) => Math.max(TILE, ...list.map(nameHalf)) + 2;
  const xLeft = Math.max(overhang(leftIds), appPairs.length > 0 ? lanesWidth + labelWidth + (skips.length > 0 ? 32 : 14) : 0);
  const columns = (reach: number) => {
    const xRail = xLeft + TILE + reach;
    const xRight = hasHub ? xRail + reach + TILE : xRail + TILE;
    const hubEdge = hasHub ? xRail + TILE + 8 + textWidth("Nexus", 7) + 4 : 0;
    const edge = rightIds.length > 0 ? xRight + overhang(rightIds) : xLeft + overhang(leftIds);
    return { xRail, xRight, width: Math.max(edge, hubEdge) };
  };
  // De 320 à 560 px : la place en plus allonge les liens avec le rail, puis reste en marge
  const room = Math.round(Math.min(Math.max(available, 320), 560));
  const stretch = Math.max(0, Math.min(72, Math.floor((room - columns(34).width) / 2)));
  const { xRail, xRight, width } = columns(34 + stretch);

  // Hauteurs
  const top = 12;
  const first = hasHub ? top + 2 * TILE + 36 + TILE : top + TILE;
  const leftStep = appPairs.some((p) => Math.abs(row(p.a) - row(p.b)) === 1) ? ROW_LINKED : ROW;
  const yLeft = (i: number) => first + i * leftStep;
  const yRight = (i: number) => first + i * ROW;

  const node = (id: string, x: number, y: number): FlowNode => {
    const name = shortName(map, id);
    const half = nameHalf(id);
    return {
      id,
      x,
      y,
      hub: false,
      name,
      label: { x, y: y + TILE + 15, anchor: "middle" },
      boxes: [
        { x: x - TILE, y: y - TILE, width: 2 * TILE, height: 2 * TILE },
        { x: x - half, y: y + TILE + 3, width: 2 * half, height: NAME_H },
      ],
    };
  };
  const nodes: FlowNode[] = [
    ...leftIds.map((id, i) => node(id, xLeft, yLeft(i))),
    ...rightIds.map((id, i) => node(id, xRight, yRight(i))),
  ];
  if (hasHub) {
    const y = top + TILE;
    nodes.unshift({
      id: HUB,
      x: xRail,
      y,
      hub: true,
      name: "Nexus",
      label: { x: xRail + TILE + 8, y: y + 4, anchor: "start" },
      boxes: [
        { x: xRail - TILE, y: y - TILE, width: 2 * TILE, height: 2 * TILE },
        { x: xRail + TILE + 8, y: y - 8, width: textWidth("Nexus", 7), height: NAME_H },
      ],
    });
  }
  const at = new Map(nodes.map((n) => [n.id, n]));
  const links: FlowLink[] = [];
  const goes = (p: { flows: SuiteFlow[] }, from: string) => p.flows.some((f) => f.from === from);

  // Liens avec Nexus : horizontaux, de l'icône au rail
  let railEnd = 0;
  if (hasHub) {
    for (const p of pairs.values()) {
      if (p.b !== HUB) continue;
      const n = at.get(p.a);
      if (!n) continue;
      const side = n.x < xRail ? 1 : -1; // du nœud vers le rail
      const x1 = n.x + side * (TILE + 4);
      const x2 = xRail - side * 4;
      const heads: string[] = [];
      if (goes(p, p.a)) heads.push(arrowHead(x2, n.y, side, 0));
      if (goes(p, HUB)) heads.push(arrowHead(x1, n.y, -side, 0));
      railEnd = Math.max(railEnd, n.y);
      links.push({
        key: `${p.a}~${HUB}`,
        a: p.a,
        b: HUB,
        flows: p.flows,
        path: `M ${x1} ${n.y} H ${x2}`,
        heads,
        label: null,
        points: [0, 0.25, 0.5, 0.75, 1].map((t) => ({ x: x1 + (x2 - x1) * t, y: n.y })),
      });
    }
  }

  // Échanges entre applications : flèche verticale entre voisines, couloir en marge sinon
  const obstacles: FlowBox[] = nodes.flatMap((n) => n.boxes);
  const placed: FlowBox[] = [];
  const inside = (b: FlowBox) => b.x >= 0 && b.y >= 0 && b.x + b.width <= width;
  const place = (text: string, candidates: { right: number; middle: number }[]): FlowLink["label"] => {
    const w = textWidth(text);
    const boxes = candidates.map((c) => ({ ...c, box: { x: c.right - w, y: c.middle - NAME_H / 2, width: w, height: NAME_H } }));
    const free = boxes.find((c) => inside(c.box) && ![...obstacles, ...placed].some((o) => boxesOverlap(c.box, o))) ?? boxes[0]!;
    placed.push(free.box);
    return { text, x: free.right, y: free.middle + 4, anchor: "end", box: free.box };
  };
  const ports = new Map<string, number>();
  const port = (id: string) => {
    const used = ports.get(id) ?? 0;
    ports.set(id, used + 1);
    return [0, -10, 10, -5, 5][used % 5]!;
  };
  for (const p of appPairs) {
    const a = at.get(p.a);
    const b = at.get(p.b);
    if (!a || !b) continue;
    const [up, down] = a.y <= b.y ? [a, b] : [b, a];
    const heads: string[] = [];
    if (Math.abs(row(p.a) - row(p.b)) === 1) {
      const y1 = up.y + TILE + NAME_H + 6;
      const y2 = down.y - TILE - 4;
      if (goes(p, up.id)) heads.push(arrowHead(up.x, y2, 0, 1));
      if (goes(p, down.id)) heads.push(arrowHead(up.x, y1, 0, -1));
      const middle = (y1 + y2) / 2;
      links.push({
        key: `${p.a}~${p.b}`,
        ...p,
        path: `M ${up.x} ${y1} V ${y2}`,
        heads,
        label: place(labelOf(p), [{ right: up.x - 10, middle }]),
        points: [0, 0.5, 1].map((t) => ({ x: up.x, y: y1 + (y2 - y1) * t })),
      });
      continue;
    }
    const lane = 8 + 10 * (lanes.length - 1 - (laneOf.get(p) ?? 0));
    const x = up.x - TILE - 4;
    const y1 = up.y + port(up.id);
    const y2 = down.y + port(down.id);
    if (goes(p, up.id)) heads.push(arrowHead(x, y2, 1, 0));
    if (goes(p, down.id)) heads.push(arrowHead(x, y1, 1, 0));
    const r = 6;
    links.push({
      key: `${p.a}~${p.b}`,
      ...p,
      path: `M ${x} ${y1} H ${lane + r} Q ${lane} ${y1} ${lane} ${y1 + r} V ${y2 - r} Q ${lane} ${y2} ${lane + r} ${y2} H ${x}`,
      heads,
      // Au-dessus du départ, sinon sous l'arrivée, puis les deux autres côtés
      label: place(labelOf(p), [
        { right: x - 4, middle: y1 - 11 },
        { right: x - 4, middle: y2 + 11 },
        { right: x - 4, middle: y2 - 11 },
        { right: x - 4, middle: y1 + 11 },
      ]),
      points: [
        ...[0, 0.5, 1].map((t) => ({ x: x + (lane - x) * t, y: y1 })),
        ...[0.25, 0.5, 0.75].map((t) => ({ x: lane, y: y1 + (y2 - y1) * t })),
        ...[0, 0.5, 1].map((t) => ({ x: x + (lane - x) * t, y: y2 })),
      ],
    });
  }

  const bottom = Math.max(...nodes.map((n) => n.boxes[1].y + n.boxes[1].height), ...nodes.map((n) => n.y + TILE));
  return {
    width,
    height: bottom + 10,
    rail: hasHub ? { x: xRail, y1: top + 2 * TILE + 4, y2: railEnd } : null,
    nodes,
    links,
  };
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
