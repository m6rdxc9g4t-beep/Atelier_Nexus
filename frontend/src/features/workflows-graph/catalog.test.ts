import { describe, expect, it } from "vitest";

import type { Catalog } from "@/types/api";

import { appTheme, catalogIndex, fold, groupCatalog, parseUses, usesLabel } from "./catalog";
import { catalogFixture } from "./fixtures";

describe("parseUses", () => {
  it("distingue outils et actions d'application", () => {
    expect(parseUses("tool:data_via_query")).toEqual({ source: "tool", app: null, name: "data_via_query" });
    expect(parseUses("node:projets/work_items.create")).toEqual({
      source: "node",
      app: "projets",
      name: "work_items.create",
    });
    expect(parseUses("bizarre")).toEqual({ source: null, app: null, name: "bizarre" });
  });

  it("donne un libellé même hors catalogue", () => {
    expect(usesLabel("node:tab/rows.add")).toBe("tab · rows.add");
    expect(usesLabel("tool:x")).toBe("x");
  });
});

describe("groupCatalog", () => {
  it("un groupe par application, dans l'ordre du catalogue, outils système à la fin", () => {
    const groups = groupCatalog(catalogFixture);
    expect(groups.map((g) => g.key)).toEqual(["viz", "tab", "projets", "cine", "nexus"]);
    expect(groups[0]!.name).toBe("Atelier Viz");
    expect(groups.at(-1)!.name).toBe("Outils Nexus");
    // Ciné : sans contrat, aucune entrée, mais visible sans filtre
    expect(groups.find((g) => g.key === "cine")!.entries).toEqual([]);
    expect(groups.find((g) => g.key === "cine")!.status).toBe("no_contract");
  });

  it("met les entrées disponibles en tête de leur groupe", () => {
    const projets = groupCatalog(catalogFixture).find((g) => g.key === "projets")!;
    expect(projets.entries.map((e) => e.available)).toEqual([true, true, false]);
  });

  it("filtre sans tenir compte des accents ni de la casse, et retire les groupes vides", () => {
    const groups = groupCatalog(catalogFixture, "CRÉER tâche");
    expect(groups.map((g) => g.key)).toEqual(["projets"]);
    expect(groups[0]!.entries.map((e) => e.uses)).toEqual(["node:projets/work_items.create"]);
    expect(groups[0]!.total).toBe(3);
    expect(groupCatalog(catalogFixture, "destructif").flatMap((g) => g.entries.map((e) => e.uses))).toEqual([
      "node:tab/rows.delete",
    ]);
  });

  it("filtre par nature et par disponibilité", () => {
    const writes = groupCatalog(catalogFixture, "", { kinds: ["write", "destructive"] });
    expect(writes.flatMap((g) => g.entries).every((e) => e.kind !== "read")).toBe(true);
    const available = groupCatalog(catalogFixture, "", { availableOnly: true });
    expect(available.flatMap((g) => g.entries).every((e) => e.available)).toBe(true);
  });

  it("crée un groupe pour une application absente de `apps`", () => {
    const catalog: Catalog = {
      apps: [],
      entries: [{ ...catalogFixture.entries[0]!, app: "savoir", uses: "node:savoir/x" }],
    };
    const [group] = groupCatalog(catalog);
    expect(group).toMatchObject({ key: "savoir", name: "savoir", color: "#9B5DE5" });
  });
});

describe("thème d'application", () => {
  it("utilise la marque pour une app connue, la couleur du backend sinon", () => {
    expect(appTheme("viz")).toEqual({ "data-atelier-app": "viz" });
    expect(appTheme(null)).toEqual({ "data-atelier-app": "nexus" });
    expect(appTheme("ailleurs", "#123456")).toEqual({
      "data-atelier-app": "ailleurs",
      style: { "--atelier-signature": "#123456" },
    });
    expect(appTheme("ailleurs", "red; x")).toMatchObject({ style: { "--atelier-signature": "#E8590C" } });
  });

  it("donne à Convert sa signature locale (absente de la marque copiée)", () => {
    const convert = { "data-atelier-app": "convert", style: { "--atelier-signature": "#C9951D" } };
    expect(appTheme("convert")).toEqual(convert);
    expect(appTheme("convert", "#C9951D")).toEqual(convert);
  });

  it("indexe le catalogue et replie les accents", () => {
    expect(catalogIndex(catalogFixture).get("tool:data_via_query")?.label).toBe("Interroger un jeu");
    expect(catalogIndex(null).size).toBe(0);
    expect(fold("Écriture Élément")).toBe("ecriture element");
  });
});
