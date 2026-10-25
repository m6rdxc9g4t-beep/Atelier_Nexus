import { describe, expect, it } from "vitest";

import { chainLabel, chainView, executionOrder, stepApp, workflowChain } from "./chain";

describe("application d'une étape", () => {
  it("lit l'application d'une action de nœud et d'un outil Nexus", () => {
    expect(stepApp({ uses: "node:convert/conversions.list" })).toBe("convert");
    expect(stepApp({ uses: "tool:data_via_query" })).toBe("viz");
    expect(stepApp({ uses: "tool:tab_projets_export" })).toBe("tab");
    expect(stepApp({ tool: "projets_create_work_item" })).toBe("projets");
  });

  it("rend null pour un outil système ou une étape inconnue", () => {
    expect(stepApp({ uses: "tool:current_datetime" })).toBeNull();
    expect(stepApp({ uses: "inconnu" })).toBeNull();
    expect(stepApp({ uses: "node:sans_action" })).toBeNull();
    expect(stepApp({})).toBeNull();
  });
});

describe("ordre d'exécution", () => {
  it("place chaque étape après ses dépendances, sinon dans l'ordre de la liste", () => {
    const steps = [
      { id: "projet", needs: ["table"] },
      { id: "convert", needs: [] },
      { id: "table", needs: ["convert"] },
      { id: "viz", needs: ["table"] },
    ];
    expect(executionOrder(steps).map((s) => s.id)).toEqual(["convert", "table", "projet", "viz"]);
  });

  it("ignore une dépendance inconnue et ne boucle pas sur un cycle", () => {
    expect(executionOrder([{ id: "a", needs: ["fantome"] }, { id: "b" }]).map((s) => s.id)).toEqual(["a", "b"]);
    const cycle = [
      { id: "a", needs: ["b"] },
      { id: "b", needs: ["a"] },
    ];
    expect(executionOrder(cycle).map((s) => s.id)).toEqual(["a", "b"]);
  });
});

describe("chaîne d'applications", () => {
  it("suit l'ordre d'exécution d'un workflow v2, sans doublon", () => {
    const steps = [
      { id: "projet", uses: "node:projets/work_items.create", needs: ["table"] },
      { id: "liste", uses: "node:convert/conversions.list", needs: [] },
      { id: "table", uses: "node:tab/tables.create", needs: ["liste"] },
      { id: "lignes", uses: "node:tab/rows.add", needs: ["table"] },
      { id: "date", uses: "tool:current_datetime", needs: [] },
    ];
    expect(workflowChain(steps)).toEqual(["convert", "tab", "projets"]);
  });

  it("lit les outils d'un workflow v1 dans l'ordre des étapes", () => {
    expect(workflowChain([{ tool: "data_via_query" }, { tool: "tab_add_rows" }, { tool: "data_via_describe_dataset" }])).toEqual([
      "viz",
      "tab",
    ]);
  });

  it("rattache à Nexus un workflow d'outils système seulement", () => {
    expect(workflowChain([{ tool: "current_datetime" }])).toEqual(["nexus"]);
    expect(workflowChain([])).toEqual([]);
  });

  it("montre les premières puces puis le reste en compteur", () => {
    expect(chainView(["convert", "tab"], 4)).toEqual({ shown: ["convert", "tab"], hidden: 0, rest: [] });
    expect(chainView(["convert", "tab", "viz", "projets", "savoir"], 3)).toEqual({
      shown: ["convert", "tab", "viz"],
      hidden: 2,
      rest: ["projets", "savoir"],
    });
  });

  it("ne montre qu'une fois une application répétée par le serveur", () => {
    expect(chainView(["tab", "projets", "tab"], 4)).toEqual({ shown: ["tab", "projets"], hidden: 0, rest: [] });
    expect(chainLabel(["tab", "tab"], (app) => app)).toBe("Applications : tab");
  });

  it("donne une phrase accessible", () => {
    const name = (app: string) => app.toUpperCase();
    expect(chainLabel(["convert", "tab"], name)).toBe("Applications : CONVERT, puis TAB");
    expect(chainLabel([], name)).toBe("Aucune application");
  });
});
