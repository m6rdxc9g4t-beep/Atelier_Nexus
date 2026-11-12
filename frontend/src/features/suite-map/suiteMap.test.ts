import { describe, expect, it, vi } from "vitest";

import { suiteMapFixture } from "@/features/workflows-graph/fixtures";
import type { SuiteEventsEntry, SuiteMap, SuiteMapApp } from "@/types/api";

import {
  actionDetail,
  actionUses,
  boxesOverlap,
  eventLabel,
  feedWarnings,
  flowNodes,
  flowsOf,
  focusQuietly,
  layoutFlows,
  mergeEvents,
  splitActions,
  suiteFlows,
  textWidth,
  toolsByBox,
  transportLabel,
  triggerChoices,
  unreadNodes,
  workflowsOf,
} from "./suiteMap";

const projets = suiteMapFixture.apps[1]!;

describe("entrées et sorties d'une application", () => {
  it("sépare écritures (entrées) et lectures (sorties)", () => {
    const { inputs, outputs } = splitActions(projets);
    expect(inputs.map((a) => a.id)).toEqual(["work_items.create", "work_items.delete"]);
    expect(outputs.map((a) => [a.id, a.output_format])).toEqual([["work_items.list", "atelier-table/1"]]);
    expect(actionUses("projets", "work_items.create")).toBe("node:projets/work_items.create");
    expect(transportLabel("mcp")).toBe("MCP");
    expect(transportLabel(null)).toBe("—");
  });

  it("retrouve flux et workflows d'une application", () => {
    const { incoming, outgoing } = flowsOf(suiteMapFixture.flows, "projets");
    expect(incoming.map((f) => f.from)).toEqual(["tab", "nexus"]);
    expect(outgoing.map((f) => f.to)).toEqual(["viz"]);
    expect(workflowsOf(suiteMapFixture, "projets").map((w) => w.id)).toEqual(["wf_1"]);
    expect(workflowsOf(suiteMapFixture, "cine")).toEqual([]);
  });
});

describe("précision écrite dans une ligne de fiche (plus de bulle flottante)", () => {
  it("donne l'identifiant d'une action, et le format de sortie d'une lecture", () => {
    const { inputs, outputs } = splitActions(projets);
    expect(actionDetail(inputs[0]!)).toBe("work_items.create");
    expect(actionDetail(outputs[0]!)).toBe("work_items.list · atelier-table/1");
    expect(actionDetail({ id: "x.read", kind: "read", output_format: "" })).toBe("x.read");
  });

  it("range les outils Nexus par boîte, dans l'ordre du hub", () => {
    const tool = (name: string, toolset: string, kind: "read" | "write" = "read") => ({ name, toolset, kind });
    const groups = toolsByBox([
      tool("projets_list_projects", "projets_read"),
      tool("projets_create_story", "projets_write", "write"),
      tool("projets_dashboard", "projets_read"),
    ]);
    expect(groups.map((g) => [g.toolset, g.tools.map((t) => t.name)])).toEqual([
      ["projets_read", ["projets_list_projects", "projets_dashboard"]],
      ["projets_write", ["projets_create_story"]],
    ]);
    expect(toolsByBox([])).toEqual([]);
  });
});

/** La suite telle que le hub la décrit (GET /api/suite/map) : 11 applications, 17 échanges. */
const realSuite = (reachable = true): SuiteMap => {
  const app = (id: string, name: string, node = false): SuiteMapApp => ({
    app: id,
    name,
    color: "#996c00",
    status: node && reachable ? "ok" : "unreachable",
    transport: node ? "http" : null,
    // Manifeste lu : au moins une lecture et une écriture par application-nœud
    actions:
      node && reachable
        ? [
            { id: `${id}.list`, label: "Lister", kind: "read", output_format: "json" },
            { id: `${id}.create`, label: "Créer", kind: "write", output_format: "json" },
          ]
        : [],
    events: [],
    nexus_tools: [],
    agents: [],
  });
  const flow = (from: string, to: string, label: string, via: string) => ({ from, to, label, via });
  const hub = (id: string, via: string, writes = true) => [
    ...(writes ? [flow("nexus", id, "Écritures validées", id === "tab" ? "MCP" : via)] : []),
    flow(id, "nexus", "Lecture", via),
  ];
  return {
    apps: [
      app("viz", "Atelier Viz", true),
      app("tab", "Atelier Tab", true),
      app("projets", "Atelier Projets", true),
      app("convert", "Atelier Convert", true),
      app("wiki", "Atelier Wiki", true),
      app("formulaire", "Atelier Formulaire", true),
      app("cine", "Atelier Ciné"),
      app("cuisine", "Atelier Cuisine"),
      app("github", "GitHub"),
      app("savoir", "Atelier Savoir"),
      app("tresorerie", "Atelier Trésorerie"),
    ],
    flows: [
      flow("tab", "projets", "Import DataFlow", "webhook"),
      flow("tab", "viz", "Instantanés", "fichiers"),
      flow("projets", "viz", "Jeux de données", "HTTP"),
      flow("convert", "tab", "Nouvelle table", "fichiers"),
      ...hub("viz", "HTTP", false),
      ...hub("tab", "fichiers"),
      ...hub("projets", "HTTP"),
      ...hub("cine", "HTTP"),
      ...hub("cuisine", "Supabase", false),
      ...hub("github", "HTTP"),
      ...hub("savoir", "HTTP"),
      ...hub("tresorerie", "HTTP", false),
    ],
    workflows: [],
  };
};

/** Largeurs utiles du schéma : téléphone de 390 px (340 dans la figure), tablette, ordinateur. */
const WIDTHS = [320, 340, 420, 480, 560];

describe("échanges de la carte", () => {
  it("ajoute ce que les workflows ouvrent vers une application-nœud sans outil Nexus", () => {
    const map = realSuite();
    expect(map.flows).toHaveLength(17);
    const added = suiteFlows(map).slice(17);
    expect(added.map((f) => `${f.from}>${f.to} ${f.label} (${f.via})`)).toEqual([
      "nexus>viz Écritures validées (workflow)",
      "nexus>convert Écritures validées (workflow)",
      "convert>nexus Lecture (workflow)",
      "nexus>wiki Écritures validées (workflow)",
      "wiki>nexus Lecture (workflow)",
      "nexus>formulaire Écritures validées (workflow)",
      "formulaire>nexus Lecture (workflow)",
    ]);
  });

  it("n'invente rien pour une application dont le manifeste n'est pas lu", () => {
    const map = realSuite(false);
    expect(suiteFlows(map)).toEqual(map.flows);
    // Et ne double jamais un échange déjà déclaré par le hub
    const pairs = suiteFlows(realSuite()).map((f) => `${f.from}>${f.to}`);
    expect(new Set(pairs).size).toBe(pairs.length);
  });

  it("nomme les applications-nœuds dont aucun échange avec Nexus n'est lu", () => {
    // Suite arrêtée : Viz, Tab et Projets gardent leurs outils Nexus ; Convert, Wiki et Formulaire n'ont que leur manifeste
    expect(unreadNodes(realSuite(false))).toEqual([
      { app: "convert", reason: "injoignable" },
      { app: "wiki", reason: "injoignable" },
      { app: "formulaire", reason: "injoignable" },
    ]);
    // Manifestes lus : tout est relié par ses actions
    expect(unreadNodes(realSuite())).toEqual([]);
    // Une application sans transport (Ciné, GitHub…) n'est pas un nœud du hub : jamais reliée d'office
    const lone: SuiteMap = { ...realSuite(false), flows: [] };
    expect(unreadNodes(lone).map((n) => n.app)).toEqual(["viz", "tab", "projets", "convert", "wiki", "formulaire"]);
    // Joignable mais manifeste vide, non configurée, sans contrat : la raison suit l'état
    const states: SuiteMap = {
      ...lone,
      apps: lone.apps.map((a) => ({ ...a, status: a.app === "viz" ? "ok" : a.app === "tab" ? "not_configured" : a.app === "projets" ? "no_contract" : a.status })),
    };
    expect(unreadNodes(states).slice(0, 3).map((n) => n.reason)).toEqual(["aucune action déclarée", "non configurée", "sans contrat"]);
  });
});

describe("schéma des flux", () => {
  it("place Nexus en tête de son rail, les applications reliées entre elles à gauche, les autres à droite", () => {
    expect(flowNodes(suiteMapFixture)).toEqual(["viz", "projets", "tab", "nexus"]);
    const layout = layoutFlows(realSuite(), 480);
    const node = (id: string) => layout.nodes.find((n) => n.id === id)!;
    const nexus = node("nexus");
    expect(nexus.hub).toBe(true);
    expect(layout.rail).toMatchObject({ x: nexus.x });
    expect(layout.rail!.y1).toBeGreaterThan(nexus.y);
    // Chaîne des données, sources d'abord : Convert → Tab → Projets → Viz
    const left = layout.nodes.filter((n) => n.x < nexus.x).sort((a, b) => a.y - b.y);
    expect(left.map((n) => n.id)).toEqual(["convert", "tab", "projets", "viz"]);
    const right = layout.nodes.filter((n) => n.x > nexus.x).sort((a, b) => a.y - b.y);
    expect(right.map((n) => n.id)).toEqual(["wiki", "formulaire", "cine", "cuisine", "github", "savoir", "tresorerie"]);
    expect(node("tab").name).toBe("Tab");
    expect(node("github").name).toBe("GitHub");
  });

  it("ne trace qu'un lien par paire d'applications, le sens donné par les pointes", () => {
    const layout = layoutFlows(realSuite(), 480);
    const keys = layout.links.map((l) => [l.a, l.b].sort().join("~"));
    expect(new Set(keys).size).toBe(keys.length);
    expect(layout.links).toHaveLength(4 + 11);
    const link = (a: string, b: string) => layout.links.find((l) => l.a === a && l.b === b)!;
    // Lecture et écritures validées : un trait, deux pointes, pas de libellé (la légende le dit)
    expect(link("tab", "nexus")).toMatchObject({ label: null });
    expect(link("tab", "nexus").flows.map((f) => f.label).sort()).toEqual(["Lecture", "Écritures validées"]);
    expect(link("tab", "nexus").heads).toHaveLength(2);
    // Lecture seule : une pointe, vers Nexus
    expect(link("cuisine", "nexus").heads).toHaveLength(1);
    expect(link("cuisine", "nexus").heads[0]).toContain(`M ${layout.rail!.x + 4} `);
    // Entre applications : un libellé par lien
    expect(layout.links.filter((l) => l.label).map((l) => l.label!.text).sort()).toEqual([
      "Import DataFlow",
      "Instantanés",
      "Jeux de données",
      "Nouvelle table",
    ]);
  });

  it("relie au rail, par un trait sans pointe, un nœud du hub dont le manifeste n'est pas lu", () => {
    const layout = layoutFlows(realSuite(false), 480);
    const link = (a: string) => layout.links.find((l) => l.a === a && l.b === "nexus");
    for (const app of ["convert", "wiki", "formulaire"]) {
      expect(link(app), app).toMatchObject({ unread: true, heads: [], flows: [], label: null });
      const node = layout.nodes.find((n) => n.id === app)!;
      // Du bord de l'icône au rail, à la hauteur de l'application
      expect(link(app)!.path).toBe(`M ${node.x + Math.sign(layout.rail!.x - node.x) * 24} ${node.y} H ${layout.rail!.x - Math.sign(layout.rail!.x - node.x) * 4}`);
    }
    // Lus par les outils Nexus : pointes, jamais « non lu »
    expect(link("viz")).toMatchObject({ unread: false });
    expect(link("viz")!.heads).toHaveLength(1);
    // Hors du hub (Ciné sans outil ni transport) : aucun lien inventé
    const cine = { ...realSuite(false), flows: realSuite(false).flows.filter((f) => f.from !== "cine" && f.to !== "cine") };
    expect(layoutFlows(cine, 480).links.some((l) => l.a === "cine")).toBe(false);
    // Manifestes lus : plus aucun trait sans pointe
    expect(layoutFlows(realSuite(), 480).links.filter((l) => l.unread)).toEqual([]);
    expect(layout.links.filter((l) => l.unread)).toHaveLength(3);
    expect(layout.links).toHaveLength(4 + 11);
  });

  it("garde Nexus et son rail quand aucun échange n'est lu (suite arrêtée, aucun outil)", () => {
    const layout = layoutFlows({ ...realSuite(false), flows: [] }, 340);
    expect(layout.nodes[0]).toMatchObject({ id: "nexus", hub: true });
    expect(layout.rail).not.toBeNull();
    expect(layout.links.map((l) => l.a).sort()).toEqual(["convert", "formulaire", "projets", "tab", "viz", "wiki"]);
    expect(layout.links.every((l) => l.unread && l.heads.length === 0)).toBe(true);
    expect(layout.width).toBeLessThanOrEqual(340);
  });

  it("répartit les arrivées le long du rail de Nexus : jamais deux du même côté à la même hauteur", () => {
    const layout = layoutFlows(realSuite(), 480);
    const node = (id: string) => layout.nodes.find((n) => n.id === id)!;
    for (const side of [-1, 1]) {
      const ys = layout.links
        .filter((l) => l.b === "nexus" && Math.sign(node(l.a).x - layout.rail!.x) === side)
        .map((l) => node(l.a).y)
        .sort((a, b) => a - b);
      expect(ys.length).toBeGreaterThan(3);
      for (let i = 1; i < ys.length; i++) expect(ys[i]! - ys[i - 1]!).toBeGreaterThanOrEqual(40);
    }
    expect(layout.rail!.y2).toBe(Math.max(...layout.links.filter((l) => l.b === "nexus").map((l) => node(l.a).y)));
  });

  it.each(WIDTHS.flatMap((w) => [[w, true] as const, [w, false] as const]))(
    "ne superpose aucun libellé, nom, icône ni tracé à %i px (manifestes lus : %s)",
    (width, reachable) => {
      const layout = layoutFlows(realSuite(reachable), width);
      expect(layout.width).toBeLessThanOrEqual(width);
      const nodeBoxes = layout.nodes.flatMap((n) => n.boxes.map((box) => ({ owner: n.id, what: `${n.id} (icône ou nom)`, box })));
      const labelBoxes = layout.links.flatMap((l) => (l.label ? [{ owner: l.key, what: `« ${l.label.text} »`, box: l.label.box }] : []));
      const all = [...nodeBoxes, ...labelBoxes];
      // Tout tient dans le schéma
      for (const { what, box } of all) {
        expect(box.x, what).toBeGreaterThanOrEqual(0);
        expect(box.y, what).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width, what).toBeLessThanOrEqual(layout.width);
        expect(box.y + box.height, what).toBeLessThanOrEqual(layout.height);
      }
      // Aucune boîte sur une autre (libellés entre eux, libellés et nœuds, nœuds entre eux)
      const clashes: string[] = [];
      for (let i = 0; i < all.length; i++)
        for (let j = i + 1; j < all.length; j++)
          if (all[i]!.owner !== all[j]!.owner && boxesOverlap(all[i]!.box, all[j]!.box)) clashes.push(`${all[i]!.what} / ${all[j]!.what}`);
      expect(clashes).toEqual([]);
      // Aucun tracé ne passe sur une icône, un nom ou un libellé
      const crossed: string[] = [];
      for (const link of layout.links)
        for (const p of link.points)
          for (const { owner, what, box } of all)
            if (owner !== link.key && p.x > box.x && p.x < box.x + box.width && p.y > box.y && p.y < box.y + box.height)
              crossed.push(`${link.key} sur ${what}`);
      expect(crossed).toEqual([]);
    },
  );

  it("réserve à chaque texte au moins sa largeur estimée", () => {
    const layout = layoutFlows(realSuite(), 340);
    for (const link of layout.links) if (link.label) expect(link.label.box.width).toBe(textWidth(link.label.text));
    for (const n of layout.nodes) expect(n.boxes[1].width).toBeGreaterThanOrEqual(textWidth(n.name));
  });

  it("garde les libellés à gauche de leur flèche, et celui d'un lien qui saute une ligne sur son départ", () => {
    const layout = layoutFlows(realSuite(), 340);
    const node = (id: string) => layout.nodes.find((n) => n.id === id)!;
    const link = (a: string, b: string) => layout.links.find((l) => [l.a, l.b].sort().join() === [a, b].sort().join())!;
    const direct = link("convert", "tab");
    expect(direct.path).toMatch(/^M \d+ \d+ V \d+$/);
    expect(direct.label!.x).toBeLessThan(node("tab").x);
    expect(direct.label!.y).toBeGreaterThan(node("convert").y);
    expect(direct.label!.y).toBeLessThan(node("tab").y);
    // Tab → Viz saute Projets : couloir en marge, libellé à la hauteur de Tab
    const skip = link("tab", "viz");
    expect(skip.path).toContain("Q");
    expect(Math.abs(skip.label!.y - node("tab").y)).toBeLessThan(20);
    expect(skip.heads).toHaveLength(1);
  });

  it("réunit un aller-retour entre deux applications en un seul lien à deux pointes", () => {
    // Applications hors du hub (ni action ni transport) : aucun rail
    const map = { ...suiteMapFixture, apps: suiteMapFixture.apps.map((a) => ({ ...a, actions: [], transport: null })), flows: [
      { from: "tab", to: "viz", label: "a", via: "x" },
      { from: "viz", to: "tab", label: "b", via: "x" },
    ] };
    const { links, rail } = layoutFlows(map);
    expect(rail).toBeNull();
    expect(links).toHaveLength(1);
    expect(links[0]).toMatchObject({ heads: [expect.any(String), expect.any(String)], label: { text: expect.stringMatching(/^[ab] · [ab]$/) } });
  });

  it("ignore un flux d'une application vers elle-même", () => {
    const map = { ...suiteMapFixture, apps: suiteMapFixture.apps.map((a) => ({ ...a, actions: [], transport: null })), flows: [{ from: "viz", to: "viz", label: "boucle", via: "x" }] };
    expect(layoutFlows(map).links).toEqual([]);
  });

  it("donne à chaque lien qui saute des lignes son couloir et sa place de libellé", () => {
    const flow = (from: string, to: string, label: string) => ({ from, to, label, via: "x" });
    const map: SuiteMap = {
      ...realSuite(false),
      flows: [flow("viz", "tab", "Un"), flow("tab", "projets", "Deux"), flow("projets", "convert", "Trois"), flow("viz", "projets", "Quatre"), flow("viz", "convert", "Cinq"), flow("tab", "convert", "Six")],
    };
    const layout = layoutFlows(map, 480);
    // Les six échanges entre applications portent un libellé (les traits « non lus » vers le rail n'en ont pas)
    const labels = layout.links.filter((l) => !l.unread).map((l) => l.label!.box);
    expect(labels).toHaveLength(6);
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) expect(boxesOverlap(labels[i]!, labels[j]!)).toBe(false);
    const lanes = layout.links.filter((l) => l.path.includes("Q")).map((l) => Number(/Q (\d+)/.exec(l.path)![1]));
    expect(lanes).toHaveLength(3);
    expect(new Set(lanes).size).toBeGreaterThanOrEqual(2);
  });
});

describe("retour du focus à un nœud du schéma (« Tout afficher »)", () => {
  it("rend le focus sans que le nœud se mette en avant : `quiet` est vrai pendant l'appel seulement", () => {
    const quiet = { current: false };
    const seen: boolean[] = [];
    const focus = vi.fn(() => seen.push(quiet.current));
    expect(focusQuietly({ isConnected: true, focus }, quiet)).toBe(true);
    expect(focus).toHaveBeenCalledOnce();
    expect(seen).toEqual([true]);
    expect(quiet.current).toBe(false);
  });

  it("ne fait rien si le nœud a disparu, et relâche `quiet` même si le focus échoue", () => {
    const quiet = { current: false };
    const focus = vi.fn();
    expect(focusQuietly({ isConnected: false, focus }, quiet)).toBe(false);
    expect(focusQuietly(null, quiet)).toBe(false);
    expect(focusQuietly(undefined, quiet)).toBe(false);
    expect(focus).not.toHaveBeenCalled();
    expect(() => focusQuietly({ isConnected: true, focus: () => { throw new Error("x"); } }, quiet)).toThrow("x");
    expect(quiet.current).toBe(false);
  });
});

describe("fil des derniers événements", () => {
  const ev = (seq: number, at: string, type = "viz.dataset.refreshed") => ({
    seq,
    type,
    at,
    subject: { kind: "dataset", id: String(seq), label: `Jeu ${seq}` },
    data: {},
  });
  const entries: SuiteEventsEntry[] = [
    { app: "viz", events: [ev(1, "2026-10-21T08:00:00Z"), ev(2, "2026-10-21T10:00:00Z")], next: 2, status: "ok" },
    { app: "projets", events: [ev(7, "2026-10-21T09:00:00+00:00", "projets.work_item.created")], next: 7, gap: true, status: "ok" },
    { app: "tab", events: [], next: 0, status: "injoignable" },
  ];

  it("fusionne les apps, les plus récents d'abord", () => {
    const feed = mergeEvents(entries);
    expect(feed.map((e) => `${e.app}:${e.seq}`)).toEqual(["viz:2", "projets:7", "viz:1"]);
    expect(mergeEvents(entries, 1)).toHaveLength(1);
  });

  it("signale les pertes et les applications muettes", () => {
    expect(feedWarnings(entries).map((w) => w.app)).toEqual(["projets", "tab"]);
  });

  it("utilise le libellé déclaré dans le manifeste", () => {
    expect(eventLabel(suiteMapFixture, "viz", "viz.dataset.refreshed")).toBe("Jeu actualisé");
    expect(eventLabel(suiteMapFixture, "viz", "viz.autre")).toBe("viz.autre");
    expect(eventLabel(null, "viz", "x")).toBe("x");
  });
});

describe("déclencheur depuis un événement de la carte", () => {
  it("propose un nouveau workflow, puis l'ajout au workflow ouvert", () => {
    const trigger = { app: "projets", types: ["projets.work_item.status_changed"] };
    expect(triggerChoices("projets", "projets.work_item.status_changed", null)).toEqual([
      { label: "Nouveau workflow déclenché par cet événement", target: { kind: "new", agent: null, trigger } },
    ]);
    const choices = triggerChoices("projets", "projets.work_item.status_changed", { id: "wf_1", title: "Doc" });
    expect(choices[1]).toEqual({ label: "Ajouter à « Doc »", target: { kind: "open", id: "wf_1", panel: "triggers", trigger } });
  });

  it("propose un workflow déclenché par un événement d'Atelier Convert", () => {
    const trigger = { app: "convert", types: ["convert.conversion.created"] };
    expect(triggerChoices("convert", "convert.conversion.created", null)).toEqual([
      { label: "Nouveau workflow déclenché par cet événement", target: { kind: "new", agent: null, trigger } },
    ]);
  });

  it("ne propose rien pour une app qui ne déclenche pas de workflow", () => {
    expect(triggerChoices("cine", "cine.film.added", null)).toEqual([]);
  });
});
