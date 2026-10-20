import { describe, expect, it } from "vitest";

import { formatCell, parsePreview, toCsv } from "./preview";

describe("parsePreview", () => {
  it("lit un résultat de requête Data Via", () => {
    const content = JSON.stringify({
      columns: [
        { key: "region", field: "region", role: "dimension", type: "string" },
        { key: "sum(ca)", field: "ca", role: "measure", type: "number" },
      ],
      rows: [
        ["Bretagne", 1200.5],
        ["Occitanie", null],
      ],
    });
    const preview = parsePreview(content);
    expect(preview).toEqual({
      view: "table",
      table: {
        headers: ["region", "sum(ca)"],
        numeric: [false, true],
        rows: [
          ["Bretagne", 1200.5],
          ["Occitanie", null],
        ],
      },
    });
  });

  it("lit un schéma avec mesures et échantillon", () => {
    const content = JSON.stringify({
      columns: [{ name: "ca", type: "number", distinct: 3, nulls: 0 }],
      measures: [{ name: "marge", expression: "SUM(ca)" }],
      sample: [{ ca: 1 }, { ca: 2, extra: "x" }],
    });
    const preview = parsePreview(content);
    expect(preview?.view).toBe("schema");
    if (preview?.view !== "schema") return;
    expect(preview.schema.measures[0]!.name).toBe("marge");
    expect(preview.schema.sample?.headers).toEqual(["ca", "extra"]);
    expect(preview.schema.sample?.rows[0]).toEqual([1, null]);
    expect(preview.schema.sample?.numeric).toEqual([true, false]);
  });

  it("renvoie null pour un contenu illisible", () => {
    expect(parsePreview("pas du json")).toBeNull();
    expect(parsePreview('{"rows": []}')).toBeNull();
  });
});

describe("formatage", () => {
  it("formate les cellules en français", () => {
    expect(formatCell(null)).toBe("—");
    expect(formatCell(true)).toBe("Oui");
    expect(formatCell(1234.5)).toMatch(/1\s234,5/);
  });

  it("exporte en CSV « ; » avec virgule décimale et échappement", () => {
    const csv = toCsv({
      headers: ["nom", "valeur"],
      numeric: [false, true],
      rows: [
        ['Dupont; "fils"', 1.5],
        ["Martin", null],
      ],
    });
    expect(csv).toBe('nom;valeur\n"Dupont; ""fils""";1,5\nMartin;');
  });
});
