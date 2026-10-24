import { describe, expect, it } from "vitest";

import { chartToCsv, formatTick, linear, niceTicks, ordinalToDate, parseChart } from "./spec";

const wrap = (spec: Record<string, unknown>) => JSON.stringify({ format: "atelier-chart/1", title: "T", ...spec });

describe("parseChart", () => {
  it("lit un histogramme et ignore les classes invalides", () => {
    const spec = parseChart(
      wrap({
        type: "histogram",
        x: { label: "Montant" },
        y: { label: "Effectif" },
        bins: [
          { start: 0, end: 10, count: 3 },
          { start: 10, end: 20, count: "x" },
        ],
        markers: [{ label: "Moyenne", value: 7.5 }, { label: "Médiane" }],
      }),
    );
    expect(spec?.type).toBe("histogram");
    if (spec?.type !== "histogram") return;
    expect(spec.bins).toEqual([{ start: 0, end: 10, count: 3 }]);
    expect(spec.markers).toEqual([{ label: "Moyenne", value: 7.5 }]);
  });

  it("refuse un autre format, un type inconnu ou du JSON invalide", () => {
    expect(parseChart(JSON.stringify({ format: "autre", type: "bar" }))).toBeNull();
    expect(parseChart(wrap({ type: "pie" }))).toBeNull();
    expect(parseChart("{")).toBeNull();
    expect(parseChart(wrap({ type: "bar", categories: [], series: [] }))).toBeNull();
  });

  it("aligne les valeurs des séries sur les catégories", () => {
    const spec = parseChart(
      wrap({ type: "bar", categories: ["Nord", "Sud", "Est"], series: [{ name: "somme", values: [1, null] }] }),
    );
    expect(spec?.type === "bar" && spec.series[0].values).toEqual([1, null, null]);
  });

  it("garde les groupes d'un nuage alignés sur les points valides", () => {
    const spec = parseChart(
      wrap({
        type: "scatter",
        points: [
          [1, 2],
          [null, 3],
          [4, 5],
        ],
        groups: ["a", "b", "c"],
        trend: { slope: 2, intercept: 1, r2: 0.9 },
        sampled: true,
        total: 5000,
      }),
    );
    expect(spec?.type).toBe("scatter");
    if (spec?.type !== "scatter") return;
    expect(spec.points).toEqual([
      [1, 2],
      [4, 5],
    ]);
    expect(spec.groups).toEqual(["a", "c"]);
    expect(spec.trend).toEqual({ slope: 2, intercept: 1, r2: 0.9 });
    expect(spec.total).toBe(5000);
  });

  it("lit une boîte à moustaches et une carte de chaleur", () => {
    const box = parseChart(
      wrap({
        type: "box",
        groups: [
          { label: "A", n: 4, min: 1, q1: 2, median: 3, q3: 4, max: 5, mean: 3, outliers: [9, "x"] },
          { label: "incomplet", min: 1 },
        ],
      }),
    );
    expect(box?.type === "box" && box.groups.map((g) => [g.label, g.outliers])).toEqual([["A", [9]]]);
    const heat = parseChart(
      wrap({
        type: "heatmap",
        labels: ["a", "b"],
        values: [
          [1, -0.4],
          [-0.4, null],
        ],
        legend: "Spearman",
      }),
    );
    expect(heat?.type === "heatmap" && heat.values).toEqual([
      [1, -0.4],
      [-0.4, null],
    ]);
    expect(heat?.type === "heatmap" && heat.domain).toEqual([-1, 1]);
  });
});

describe("échelles et format", () => {
  it("produit des graduations rondes qui couvrent le domaine", () => {
    expect(niceTicks(0, 97)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(niceTicks(-0.83, 1)).toEqual([-1, -0.5, 0, 0.5, 1]);
    const flat = niceTicks(5, 5);
    expect(flat[0]).toBeLessThan(5);
    expect(flat[flat.length - 1]).toBeGreaterThan(5);
    expect(niceTicks(Number.NaN, 1)).toEqual([]);
  });

  it("projette linéairement", () => {
    const s = linear(0, 10, 100, 0);
    expect(s(0)).toBe(100);
    expect(s(5)).toBe(50);
  });

  it("formate en français, dates comprises", () => {
    expect(formatTick(12.5)).toBe("12,5");
    expect(formatTick(25_000)).toBe("25 k");
    expect(formatTick(2_500_000)).toBe("2,5 M");
    expect(ordinalToDate(739_621)).toBe("05/01/2026"); // date(2026, 1, 5).toordinal()
  });
});

describe("chartToCsv", () => {
  it("exporte les séries par catégorie", () => {
    const spec = parseChart(
      wrap({
        type: "line",
        x: { label: "Mois" },
        categories: ["2026-01", "2026-02"],
        series: [
          { name: "Somme", values: [1.5, 2] },
          { name: "Moyenne", values: [0.5, null] },
        ],
      }),
    );
    expect(spec && chartToCsv(spec)).toBe("Mois;Somme;Moyenne\n2026-01;1,5;0,5\n2026-02;2;");
  });
});
