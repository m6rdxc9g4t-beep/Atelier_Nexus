import { describe, expect, it } from "vitest";

import { catalogIndex } from "./catalog";
import { catalogFixture, diamondSteps, step } from "./fixtures";
import { isExactTemplate, parseRef, referencedParams, renameStepRefs, templateRefs } from "./refs";
import { insertTemplate, templateOptions } from "./templates";

const catalog = catalogIndex(catalogFixture);

describe("lecture des gabarits", () => {
  it("trouve les références dans les objets et listes", () => {
    expect(
      templateRefs({ a: "{{params.x}} et {{ steps.b.data }}", l: ["{{y}}", 3, { z: "{{run.id}}" }] }),
    ).toEqual(["params.x", "steps.b.data", "y", "run.id"]);
    expect(isExactTemplate(" {{steps.a.data}} ")).toBe(true);
    expect(isExactTemplate("CA {{steps.a.data}}")).toBe(false);
    expect(isExactTemplate(3)).toBe(false);
  });

  it("analyse chaque forme de référence", () => {
    expect(parseRef("jeu")).toEqual({ kind: "param", name: "jeu", legacy: true });
    expect(parseRef("params.jeu")).toEqual({ kind: "param", name: "jeu", legacy: false });
    expect(parseRef("steps.lire.data.rows[0].titre")).toEqual({ kind: "step", step: "lire", path: "data.rows[0].titre" });
    expect(parseRef("steps.lire")).toEqual({ kind: "step", step: "lire", path: "" });
    expect(parseRef("run.id")).toEqual({ kind: "run", path: "id" });
    expect(parseRef("Steps.X")).toEqual({ kind: "invalid", raw: "Steps.X" });
  });

  it("liste les paramètres cités, condition comprise", () => {
    const steps = [
      step("a", "x", [], { v: "{{params.jeu}}", w: "{{mois}}" }),
      { ...step("b", "x"), when: { left: "{{params.seuil}}", op: "gt" as const, right: 3 } },
    ];
    expect(referencedParams(steps)).toEqual(["jeu", "mois", "seuil"]);
  });

  it("renomme les références d'étape", () => {
    expect(renameStepRefs({ a: ["{{steps.x.data}}", "{{steps.x[0]}}", "{{steps.xy.data}}"] }, "x", "y")).toEqual({
      a: ["{{steps.y.data}}", "{{steps.y[0]}}", "{{steps.xy.data}}"],
    });
  });
});

describe("Utiliser… : propositions d'un champ", () => {
  const params = [{ name: "jeu", label: "Jeu de données", default: "ventes" }];

  it("ne propose que les paramètres et les étapes ancêtres", () => {
    const groups = templateOptions(diamondSteps, params, "creer", catalog);
    expect(groups.map((g) => g.stepId)).toEqual([null, "lire", "taches", null]);
    expect(groups[0]!.options[0]).toEqual({ label: "Jeu de données", value: "{{params.jeu}}", hint: "défaut : ventes" });
    expect(groups.at(-1)!.options[0]!.value).toBe("{{run.id}}");
    // « ajouter » n'est pas un ancêtre de « creer »
    expect(groups.some((g) => g.stepId === "ajouter")).toBe(false);
    expect(templateOptions(diamondSteps, [], "lire", catalog).map((g) => g.label)).toEqual(["Exécution"]);
  });

  it("détaille une sortie atelier-table/1 avec ses colonnes", () => {
    const lire = templateOptions(diamondSteps, params, "creer", catalog).find((g) => g.stepId === "lire")!;
    expect(lire.label).toBe("Interroger un jeu (lire)");
    expect(lire.options.map((o) => o.value)).toEqual([
      "{{steps.lire.data}}",
      "{{steps.lire.content}}",
      "{{steps.lire.data.rows[0].region}}",
      "{{steps.lire.data.rows[0].ca}}",
      "{{steps.lire.data.total}}",
      "{{steps.lire.status}}",
    ]);
    expect(lire.options[2]!.label).toBe("1re ligne · Région");
  });

  it("propose les champs annoncés d'une sortie objet", () => {
    const steps = [step("creer", "node:projets/work_items.create"), step("suite", "x", ["creer"])];
    const group = templateOptions(steps, [], "suite", catalog).find((g) => g.stepId === "creer")!;
    expect(group.options.map((o) => o.value)).toContain("{{steps.creer.data.id}}");
  });
});

describe("insertion d'un gabarit", () => {
  it("ajoute au texte, remplace les autres natures", () => {
    expect(insertTemplate("", "{{params.x}}", "string")).toBe("{{params.x}}");
    expect(insertTemplate("CA de", "{{params.x}}", "string")).toBe("CA de {{params.x}}");
    expect(insertTemplate("CA ", "{{params.x}}", "string")).toBe("CA {{params.x}}");
    expect(insertTemplate("{{params.y}}", "{{params.x}}", "string")).toBe("{{params.x}}");
    expect(insertTemplate(12, "{{steps.a.data.total}}", "number")).toBe("{{steps.a.data.total}}");
    expect(insertTemplate("abc", "{{steps.a.data}}", "json")).toBe("{{steps.a.data}}");
    expect(insertTemplate(undefined, "{{params.x}}", "string")).toBe("{{params.x}}");
  });
});
