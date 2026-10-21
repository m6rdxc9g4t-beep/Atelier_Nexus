import { describe, expect, it } from "vitest";

import { suiteMapFixture } from "@/features/workflows-graph/fixtures";
import type { SuiteEventsEntry } from "@/types/api";

import {
  actionUses,
  eventLabel,
  feedWarnings,
  flowNodes,
  flowsOf,
  layoutFlows,
  mergeEvents,
  splitActions,
  transportLabel,
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

describe("schéma des flux", () => {
  it("ajoute Nexus au centre et place les apps en cercle", () => {
    expect(flowNodes(suiteMapFixture)).toEqual(["viz", "projets", "tab", "nexus"]);
    const layout = layoutFlows(suiteMapFixture, 400);
    const nexus = layout.nodes.find((n) => n.id === "nexus")!;
    expect(nexus).toEqual({ id: "nexus", x: 200, y: 200 });
    // Première app en haut
    expect(layout.nodes[0]).toMatchObject({ id: "viz", x: 200 });
    expect(layout.nodes[0]!.y).toBeLessThan(100);
    expect(layout.edges).toHaveLength(4);
    expect(layout.edges[0]!.path).toMatch(/^M \d+ \d+ Q -?\d+ -?\d+ \d+ \d+$/);
  });

  it("dessine deux courbes distinctes pour un aller-retour", () => {
    const map = { ...suiteMapFixture, flows: [
      { from: "tab", to: "viz", label: "a", via: "x" },
      { from: "viz", to: "tab", label: "b", via: "x" },
    ] };
    const [ab, ba] = layoutFlows(map).edges;
    expect(ab!.labelX === ba!.labelX && ab!.labelY === ba!.labelY).toBe(false);
  });

  it("ignore un flux vers une application inconnue de lui-même", () => {
    const map = { ...suiteMapFixture, flows: [{ from: "viz", to: "viz", label: "boucle", via: "x" }] };
    expect(layoutFlows(map).edges).toEqual([]);
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
