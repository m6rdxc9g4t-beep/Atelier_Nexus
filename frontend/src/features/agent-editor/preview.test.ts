import { describe, expect, it } from "vitest";

import { AGENT_ICONS } from "@/features/chat-agent/agentMeta";
import type { ToolsetInfo } from "@/types/api";

import { ICON_LABELS, iconLabel, previewApps } from "./preview";

const toolset = (id: string, app: string | null, tools: string[] = []): ToolsetInfo => ({
  id,
  label: id,
  description: "",
  app,
  configured: true,
  sensitive: false,
  writes: false,
  tools: tools.map((name) => ({ name, description: "" })),
});

describe("aperçu de l'éditeur d'agents", () => {
  it("nomme en français chaque icône proposée", () => {
    for (const icon of Object.keys(AGENT_ICONS)) expect(ICON_LABELS[icon], icon).toBeTruthy();
    expect(iconLabel("chart-column")).toBe("Graphique");
    expect(iconLabel("table-2")).toBe("Tableau");
    expect(iconLabel("rocket-ship")).toBe("Icône rocket ship");
  });

  it("déduit les applications des boîtes cochées, sans doublon, dans l'ordre du catalogue", () => {
    const toolsets = [
      toolset("core", null),
      toolset("data_via", "viz"),
      toolset("projets_read", "projets"),
      toolset("projets_write", "projets"),
      // Boîte d'extension sans app déclarée : rattachée par le préfixe de ses outils
      toolset("convert_extra", null, ["convert_run"]),
    ];
    expect(previewApps(["projets_write", "core", "convert_extra", "data_via", "projets_read"], toolsets)).toEqual([
      "viz",
      "projets",
      "convert",
    ]);
    expect(previewApps(["core"], toolsets)).toEqual([]);
  });
});
