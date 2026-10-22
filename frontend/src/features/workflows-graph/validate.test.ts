import { describe, expect, it } from "vitest";

import { catalogIndex } from "./catalog";
import { catalogFixture, diamondSteps, step } from "./fixtures";
import { errorsByField, globalErrors, validateLocal } from "./validate";

const catalog = catalogIndex(catalogFixture);
const params = [{ name: "jeu", label: "", default: "" }];
const codes = (errors: { code: string }[]) => errors.map((e) => e.code);

describe("validation locale", () => {
  it("accepte un graphe correct", () => {
    expect(validateLocal({ steps: diamondSteps, params, catalog })).toEqual([]);
  });

  it("signale identifiants invalides ou en double", () => {
    const errors = validateLocal({ steps: [step("Lire", "tool:data_via_query"), step("a", "x"), step("a", "x")], params: [] });
    expect(codes(errors)).toEqual(["BAD_ID", "DUPLICATE_ID"]);
    expect(errors[1]).toMatchObject({ step_id: "a", field: "id" });
  });

  it("signale les cycles sur chaque étape concernée", () => {
    const errors = validateLocal({ steps: [step("a", "x", ["b"]), step("b", "x", ["a"]), step("c", "x")], params: [] });
    expect(errors.filter((e) => e.code === "CYCLE").map((e) => e.step_id)).toEqual(["a", "b"]);
  });

  it("refuse une référence à une étape qui n'est pas amont", () => {
    const steps = [
      step("a", "x"),
      step("b", "x", [], { v: "{{steps.a.data}}", w: ["{{ steps.b.content }}"] }),
      step("c", "x", ["a"], { v: "{{steps.a.data.rows[0].x}}" }),
    ];
    const errors = validateLocal({ steps, params: [] });
    expect(errors.map((e) => [e.step_id, e.field, e.code])).toEqual([
      ["b", "v", "REF_NOT_ANCESTOR"],
      ["b", "w", "REF_NOT_ANCESTOR"],
    ]);
    expect(errors[1]!.message).toContain("propre sortie");
  });

  it("refuse un paramètre non déclaré (formes v1 et v2) et un gabarit illisible", () => {
    const steps = [step("a", "x", [], { v: "{{params.jeu}} {{mois}}", w: "{{ ??? }}" })];
    expect(codes(validateLocal({ steps, params }))).toEqual(["UNDECLARED_PARAM", "BAD_TEMPLATE"]);
    const when = [{ ...step("a", "x"), when: { left: "{{params.seuil}}", op: "gt" as const, right: 1 } }];
    expect(validateLocal({ steps: when, params: [] })[0]).toMatchObject({ field: "when", code: "UNDECLARED_PARAM" });
  });

  it("vérifie le catalogue s'il est chargé", () => {
    const steps = [step("a", "node:inconnue/x"), step("b", "node:projets/milestones.list"), step("c", "tool:delegate_to_agent")];
    expect(codes(validateLocal({ steps, params: [], catalog }))).toEqual(["UNKNOWN_USES", "UNAVAILABLE", "NOT_REPLAYABLE"]);
    expect(codes(validateLocal({ steps, params: [] }))).toEqual(["NOT_REPLAYABLE"]);
  });

  it("signale dépendance inconnue, condition incomplète et limites", () => {
    const steps = [
      step("a", "x", ["fantome"]),
      { ...step("b", "x"), when: { left: "", op: "eq" as const } },
      { ...step("c", "x"), when: { left: "{{run.id}}", op: "empty" as const } },
    ];
    expect(codes(validateLocal({ steps, params: [] }))).toEqual(["UNKNOWN_NEED", "BAD_CONDITION", "BAD_CONDITION"]);
    const many = Array.from({ length: 31 }, (_, i) => step(`s${i}`, "x"));
    expect(codes(validateLocal({ steps: many, params: [] }))).toEqual(["TOO_MANY_STEPS"]);
    expect(codes(validateLocal({ steps: [], params: [{ name: "1x", label: "", default: "" }] }))).toEqual([
      "NO_STEPS",
      "BAD_PARAM",
    ]);
  });

  it("range les erreurs par champ et isole les erreurs globales", () => {
    const errors = [
      { step_id: "a", field: "filters[0].value", code: "INPUT_INVALID", message: "" },
      { step_id: "a", field: null, code: "UNAVAILABLE", message: "" },
      { step_id: null, field: null, code: "TOO_MANY_STEPS", message: "" },
    ];
    const byField = errorsByField(errors, "a");
    expect([...byField.keys()]).toEqual(["filters", null]);
    expect(globalErrors(errors)).toHaveLength(1);
  });
});
