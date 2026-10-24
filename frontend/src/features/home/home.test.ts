import { describe, expect, it } from "vitest";

import type { AgentInfo, AppStatus } from "@/types/api";

import { appsSentence, appsSummary, featuredAgents, greeting } from "./home";

const agent = (name: string, category: string | null): AgentInfo => ({
  name,
  display_name: name,
  description: "",
  category,
  tools: [],
});

const app = (id: string, configured: boolean, available: boolean): AppStatus => ({
  id,
  label: id,
  configured,
  available,
  base_url: null,
  detail: null,
  error: null,
});

describe("accueil", () => {
  it("salue selon l'heure", () => {
    expect(greeting(9)).toBe("Bonjour");
    expect(greeting(17)).toBe("Bonjour");
    expect(greeting(18)).toBe("Bonsoir");
    expect(greeting(2)).toBe("Bonsoir");
  });

  it("met en avant le premier agent de chaque catégorie, puis complète", () => {
    const agents = [agent("a", "Général"), agent("b", "Général"), agent("c", "Données"), agent("d", null)];
    expect(featuredAgents(agents).map((a) => a.name)).toEqual(["a", "c", "d", "b"]);
    expect(featuredAgents(agents, 2).map((a) => a.name)).toEqual(["a", "c"]);
  });

  it("résume l'état des applications", () => {
    const summary = appsSummary([app("viz", true, true), app("tab", true, false), app("cine", false, false)]);
    expect(summary).toEqual({ up: 1, down: 1, off: 1, total: 3 });
    expect(appsSentence(summary)).toBe("1 sur 3 répondent · 1 injoignable.");
    expect(appsSentence(appsSummary([app("viz", true, true)]))).toBe("Toutes les applications répondent.");
    expect(appsSentence(appsSummary([]))).toBe("Aucune application de la suite n'est déclarée.");
  });
});
