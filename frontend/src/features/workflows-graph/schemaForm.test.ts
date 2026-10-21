import { describe, expect, it } from "vitest";

import { catalogFixture } from "./fixtures";
import {
  extraKeys,
  fieldFromSchema,
  fieldsFromSchema,
  formatFieldValue,
  missingRequired,
  parseFieldInput,
  setInputValue,
} from "./schemaForm";

const createSchema = catalogFixture.entries.find((e) => e.uses === "node:projets/work_items.create")!.input_schema;

describe("champs depuis JSON Schema", () => {
  it("déduit la nature de chaque champ, requis en tête", () => {
    const fields = fieldsFromSchema(createSchema);
    expect(fields.map((f) => [f.name, f.kind, f.required])).toEqual([
      ["title", "string", true],
      ["type", "enum", false],
      ["estimate", "number", false],
      ["urgent", "boolean", false],
      ["tags", "array", false],
      ["meta", "json", false],
    ]);
    expect(fields[1]!.options).toEqual(["TASK", "BUG"]);
    expect(fields[4]!.itemKind).toBe("string");
  });

  it("gère anyOf nullable, type multiple, titre et bornes", () => {
    expect(fieldFromSchema("n", { anyOf: [{ type: "integer", minimum: 1 }, { type: "null" }], title: "Nombre" }, false)).toMatchObject({
      kind: "integer",
      label: "Nombre",
      minimum: 1,
    });
    expect(fieldFromSchema("s", { type: ["string", "null"], maxLength: 2000 }, false)).toMatchObject({ kind: "string", multiline: true });
    expect(fieldFromSchema("c", { const: "x" }, false)).toMatchObject({ kind: "enum", options: ["x"] });
    expect(fieldFromSchema("u", {}, false).kind).toBe("json");
    expect(fieldFromSchema("l", { type: "array", items: { type: "object" } }, false).kind).toBe("json");
    expect(fieldFromSchema("e", { type: "array", items: { enum: ["a", "b"] } }, false)).toMatchObject({
      kind: "array",
      options: ["a", "b"],
    });
    expect(fieldsFromSchema(null)).toEqual([]);
    expect(fieldsFromSchema({ type: "object" })).toEqual([]);
  });

  it("repère les clés que le schéma ne décrit pas", () => {
    const fields = fieldsFromSchema(createSchema);
    expect(extraKeys({ title: "x", autre: 1 }, fields)).toEqual(["autre"]);
    expect(missingRequired(fields, { title: "" })).toEqual(["title"]);
    expect(missingRequired(fields, { title: "{{params.t}}" })).toEqual([]);
  });
});

describe("saisie ↔ valeur", () => {
  const [title, type, estimate, urgent, tags, meta] = fieldsFromSchema(createSchema);
  const integer = fieldFromSchema("n", { type: "integer" }, false);

  it("convertit selon la nature, gabarits exacts gardés tels quels", () => {
    expect(parseFieldInput(title!, "Bonjour ")).toEqual({ ok: true, value: "Bonjour " });
    expect(parseFieldInput(estimate!, "3,5")).toEqual({ ok: true, value: 3.5 });
    expect(parseFieldInput(estimate!, "{{steps.a.data.total}}")).toEqual({ ok: true, value: "{{steps.a.data.total}}" });
    expect(parseFieldInput(estimate!, "abc").ok).toBe(false);
    expect(parseFieldInput(integer, "2.5")).toEqual({ ok: false, error: "Nombre entier attendu." });
    expect(parseFieldInput(urgent!, "true")).toEqual({ ok: true, value: true });
    expect(parseFieldInput(type!, "BUG")).toEqual({ ok: true, value: "BUG" });
    expect(parseFieldInput(type!, "AUTRE").ok).toBe(false);
    expect(parseFieldInput(tags!, "a\n\n b \n{{params.t}}")).toEqual({ ok: true, value: ["a", "b", "{{params.t}}"] });
    expect(parseFieldInput(meta!, '{"a": 1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(parseFieldInput(meta!, "{nope").ok).toBe(false);
    expect(parseFieldInput(meta!, "{{steps.a.data}}")).toEqual({ ok: true, value: "{{steps.a.data}}" });
    expect(parseFieldInput(title!, "  ")).toEqual({ ok: true, value: undefined });
  });

  it("affiche la valeur enregistrée", () => {
    expect(formatFieldValue(tags!, ["a", "b"])).toBe("a\nb");
    expect(formatFieldValue(meta!, { a: 1 })).toBe('{\n  "a": 1\n}');
    expect(formatFieldValue(estimate!, 4)).toBe("4");
    expect(formatFieldValue(estimate!, "{{params.x}}")).toBe("{{params.x}}");
    expect(formatFieldValue(title!, undefined)).toBe("");
  });

  it("retire la clé d'un champ vidé", () => {
    expect(setInputValue({ a: 1, b: 2 }, "a", undefined)).toEqual({ b: 2 });
    expect(setInputValue({}, "a", 0)).toEqual({ a: 0 });
  });
});
