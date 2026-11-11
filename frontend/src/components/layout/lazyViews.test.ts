import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it, vi } from "vitest";

import { whenIdle } from "./lazyViews";

const read = (name: string) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

/** Modules d'une instruction `import … from "…"` statique (pas les `import()` à la demande). */
const staticImports = (source: string) => [...source.matchAll(/^import\s[^;]*?from\s+"([^"]+)"/gm)].map((m) => m[1]);

describe("vues chargées à la demande", () => {
  // Le paquet initial ne doit contenir ni l'éditeur en graphe (@xyflow/react), ni le Studio, ni les
  // Réglages, ni l'éditeur d'agent, ni la conversation (react-markdown) : un import statique dans
  // l'écran principal ou la barre latérale les y ramènerait.
  const HEAVY = [
    "@/features/chat-agent/ChatPanel",
    "@/features/workflows/WorkflowsStudio",
    "@/features/workflows-graph/WorkflowGraphEditor",
    "@/features/settings/SettingsDialog",
    "@/features/agent-editor/AgentEditor",
  ];

  it.each(["Workspace.tsx", "AppSidebar.tsx", "AppHeader.tsx"])("%s n'importe aucune vue lourde en statique", (file) => {
    const imports = staticImports(read(file));
    expect(imports.length).toBeGreaterThan(3);
    for (const heavy of HEAVY) expect(imports).not.toContain(heavy);
  });

  it("chaque vue lourde a son chargeur", () => {
    const source = read("lazyViews.ts");
    for (const heavy of HEAVY) expect(source).toContain(`import("${heavy}")`);
  });
});

describe("whenIdle", () => {
  it("passe par requestIdleCallback, avec un délai maximal, et s'annule", () => {
    const requestIdleCallback = vi.fn(() => 7);
    const cancelIdleCallback = vi.fn();
    const run = vi.fn();
    const cancel = whenIdle(run, { requestIdleCallback, cancelIdleCallback, setTimeout: vi.fn(), clearTimeout: vi.fn() }, 3000);
    expect(requestIdleCallback).toHaveBeenCalledWith(run, { timeout: 3000 });
    cancel();
    expect(cancelIdleCallback).toHaveBeenCalledWith(7);
  });

  it("sans requestIdleCallback (Safari) : court délai, annulable", () => {
    const setTimeout = vi.fn(() => 3);
    const clearTimeout = vi.fn();
    const run = vi.fn();
    const cancel = whenIdle(run, { setTimeout, clearTimeout });
    expect(setTimeout).toHaveBeenCalledWith(run, 1500);
    expect(run).not.toHaveBeenCalled();
    cancel();
    expect(clearTimeout).toHaveBeenCalledWith(3);
  });
});
