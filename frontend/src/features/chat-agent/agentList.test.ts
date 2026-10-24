import { describe, expect, it } from "vitest";

import type { AgentInfo } from "@/types/api";

import { filterAgents, fold, groupAgents, parseCollapsed } from "./agentList";

const agent = (name: string, display_name: string, category: string | null, description = ""): AgentInfo => ({
  name,
  display_name,
  description,
  category,
  tools: [],
});

const AGENTS = [
  agent("assistant", "Assistant Atelier", "Général", "Le bon point de départ."),
  agent("tableur", "Tableur", "Données", "Tables d'Atelier Tab, totaux, échéances."),
  agent("data_analyst", "Data Analyst / Power BI", "Données", "Mesures DAX et requêtes."),
  agent("perso", "Mon agent", null),
];

describe("liste des agents", () => {
  it("cherche sans accents ni casse, sur tous les mots", () => {
    expect(fold("Échéances")).toBe("echeances");
    expect(filterAgents(AGENTS, "echeance").map((a) => a.name)).toEqual(["tableur"]);
    expect(filterAgents(AGENTS, "données dax").map((a) => a.name)).toEqual(["data_analyst"]);
    expect(filterAgents(AGENTS, "  ")).toHaveLength(4);
    expect(filterAgents(AGENTS, "introuvable")).toEqual([]);
  });

  it("regroupe par catégorie dans l'ordre du catalogue", () => {
    expect(groupAgents(AGENTS).map(([c, list]) => [c, list.length])).toEqual([
      ["Général", 1],
      ["Données", 2],
      ["Agents", 1],
    ]);
  });

  it("relit les catégories repliées en ignorant une valeur illisible", () => {
    expect(parseCollapsed('["Maison","Métiers"]')).toEqual(["Maison", "Métiers"]);
    expect(parseCollapsed("{")).toEqual([]);
    expect(parseCollapsed('[1,"Maison"]')).toEqual(["Maison"]);
    expect(parseCollapsed(null)).toEqual([]);
  });
});
