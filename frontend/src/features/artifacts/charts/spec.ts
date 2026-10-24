/**
 * Graphiques des outils d'analyse : artefacts `chart`, format `atelier-chart/1`
 * (backend/app/analysis/charts.py). Lecture défensive + échelles + export CSV.
 * Fonctions pures (testées dans spec.test.ts) ; le dessin est dans ChartView.tsx.
 */

export interface Axis {
  label: string;
  kind?: "number" | "date" | "category";
}

export interface Bin {
  start: number;
  end: number;
  count: number;
}

export interface BoxGroup {
  label: string;
  n: number;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  mean: number | null;
  outliers: number[];
}

export interface Series {
  name: string;
  values: (number | null)[];
}

interface Base {
  title: string;
}

export type ChartSpec =
  | (Base & { type: "histogram"; x: Axis; y: Axis; bins: Bin[]; markers: { label: string; value: number }[] })
  | (Base & { type: "box"; x: Axis; y: Axis; groups: BoxGroup[] })
  | (Base & {
      type: "scatter";
      x: Axis;
      y: Axis;
      points: [number, number][];
      groups: string[] | null;
      trend: { slope: number; intercept: number; r2: number | null } | null;
      sampled: boolean;
      total: number;
    })
  | (Base & { type: "bar" | "line"; x: Axis; y: Axis; categories: string[]; series: Series[] })
  | (Base & { type: "heatmap"; labels: string[]; values: (number | null)[][]; domain: [number, number]; legend: string });

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const numOrNull = (v: unknown): number | null => (isNum(v) ? v : null);
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);

function axis(v: unknown): Axis {
  if (!isRecord(v)) return { label: "" };
  const kind = v.kind === "date" || v.kind === "category" || v.kind === "number" ? v.kind : undefined;
  return { label: str(v.label), kind };
}

/** Spécification valide ou `null` (l'artefact s'affiche alors en JSON brut). */
export function parseChart(content: string): ChartSpec | null {
  let data: unknown;
  try {
    data = JSON.parse(content);
  } catch {
    return null;
  }
  if (!isRecord(data) || data.format !== "atelier-chart/1") return null;
  const title = str(data.title);
  switch (data.type) {
    case "histogram": {
      if (!Array.isArray(data.bins)) return null;
      const bins = data.bins
        .filter(isRecord)
        .filter((b) => isNum(b.start) && isNum(b.end) && isNum(b.count))
        .map((b) => ({ start: b.start as number, end: b.end as number, count: b.count as number }));
      const markers = (Array.isArray(data.markers) ? data.markers : [])
        .filter(isRecord)
        .filter((m) => isNum(m.value))
        .map((m) => ({ label: str(m.label), value: m.value as number }));
      return bins.length ? { type: "histogram", title, x: axis(data.x), y: axis(data.y), bins, markers } : null;
    }
    case "box": {
      if (!Array.isArray(data.groups)) return null;
      const groups = data.groups
        .filter(isRecord)
        .filter((g) => ["min", "q1", "median", "q3", "max"].every((k) => isNum(g[k])))
        .map((g) => ({
          label: str(g.label),
          n: isNum(g.n) ? g.n : 0,
          min: g.min as number,
          q1: g.q1 as number,
          median: g.median as number,
          q3: g.q3 as number,
          max: g.max as number,
          mean: numOrNull(g.mean),
          outliers: Array.isArray(g.outliers) ? g.outliers.filter(isNum) : [],
        }));
      return groups.length ? { type: "box", title, x: axis(data.x), y: axis(data.y), groups } : null;
    }
    case "scatter": {
      if (!Array.isArray(data.points)) return null;
      const keep: number[] = [];
      const points: [number, number][] = [];
      data.points.forEach((p, i) => {
        if (Array.isArray(p) && isNum(p[0]) && isNum(p[1])) {
          points.push([p[0], p[1]]);
          keep.push(i);
        }
      });
      const rawGroups = Array.isArray(data.groups) ? data.groups : null;
      const groups = rawGroups ? keep.map((i) => str(rawGroups[i], "∅")) : null;
      const t = isRecord(data.trend) && isNum(data.trend.slope) && isNum(data.trend.intercept) ? data.trend : null;
      return points.length
        ? {
            type: "scatter",
            title,
            x: axis(data.x),
            y: axis(data.y),
            points,
            groups,
            trend: t ? { slope: t.slope as number, intercept: t.intercept as number, r2: numOrNull(t.r2) } : null,
            sampled: data.sampled === true,
            total: isNum(data.total) ? data.total : points.length,
          }
        : null;
    }
    case "bar":
    case "line": {
      if (!Array.isArray(data.categories) || !Array.isArray(data.series)) return null;
      const categories = data.categories.map((c) => str(c, String(c)));
      const series = data.series
        .filter(isRecord)
        .map((s) => ({
          name: str(s.name),
          values: categories.map((_, i) => (Array.isArray(s.values) ? numOrNull(s.values[i]) : null)),
        }));
      return categories.length && series.length
        ? { type: data.type, title, x: axis(data.x), y: axis(data.y), categories, series }
        : null;
    }
    case "heatmap": {
      if (!Array.isArray(data.labels) || !Array.isArray(data.values)) return null;
      const labels = data.labels.map((l) => str(l, String(l)));
      const values = labels.map((_, i) => {
        const row = Array.isArray(data.values) ? (data.values as unknown[])[i] : null;
        return labels.map((__, j) => (Array.isArray(row) ? numOrNull(row[j]) : null));
      });
      const domain: [number, number] =
        Array.isArray(data.domain) && isNum(data.domain[0]) && isNum(data.domain[1])
          ? [data.domain[0], data.domain[1]]
          : [-1, 1];
      return labels.length ? { type: "heatmap", title, labels, values, domain, legend: str(data.legend) } : null;
    }
    default:
      return null;
  }
}

// ─── Échelles ──────────────────────────────────────────────────────

/** Graduations « rondes » couvrant [min, max] (pas de 1, 2 ou 5 × 10^k). */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    const pad = Math.abs(min) || 1;
    return niceTicks(min - pad, max + pad, count);
  }
  const span = max - min;
  const raw = span / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => span / s <= count) ?? 10 * mag;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  if (ticks[ticks.length - 1] < max) ticks.push(Number((ticks[ticks.length - 1] + step).toPrecision(12)));
  return ticks;
}

/** Échelle linéaire du domaine [d0, d1] vers [r0, r1]. */
export function linear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Nombre d'axe en français : 1 200 · 12,5 · 1,2 M. Dates : ordinal de jour → JJ/MM/AAAA. */
export function formatTick(value: number, kind?: Axis["kind"]): string {
  if (kind === "date") return ordinalToDate(value);
  const a = Math.abs(value);
  if (a >= 1e6) return `${(value / 1e6).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} M`;
  if (a >= 1e4) return `${(value / 1e3).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} k`;
  return value.toLocaleString("fr-FR", { maximumFractionDigits: a < 1 ? 3 : 2 });
}

/** Ordinal Python (`date.toordinal`, 1 = 01/01/0001) → date française. */
export function ordinalToDate(ordinal: number): string {
  const epoch = 719163; // date(1970, 1, 1).toordinal()
  const d = new Date((Math.floor(ordinal) - epoch) * 86_400_000);
  return d.toLocaleDateString("fr-FR", { timeZone: "UTC" });
}

// ─── Export ────────────────────────────────────────────────────────

/** Données du graphique en tableau (export CSV et tableau lu par les lecteurs d'écran). */
export function chartRows(spec: ChartSpec): (string | number | null)[][] {
  switch (spec.type) {
    case "histogram":
      return [["Début", "Fin", "Effectif"], ...spec.bins.map((b) => [b.start, b.end, b.count])];
    case "box":
      return [
        ["Groupe", "n", "Min", "Q1", "Médiane", "Q3", "Max", "Moyenne"],
        ...spec.groups.map((g) => [g.label, g.n, g.min, g.q1, g.median, g.q3, g.max, g.mean]),
      ];
    case "scatter":
      return [
        [spec.x.label || "x", spec.y.label || "y", ...(spec.groups ? ["Groupe"] : [])],
        ...spec.points.map((p, i) => [p[0], p[1], ...(spec.groups ? [spec.groups[i]] : [])]),
      ];
    case "bar":
    case "line":
      return [
        [spec.x.label || "Catégorie", ...spec.series.map((s) => s.name)],
        ...spec.categories.map((c, i) => [c, ...spec.series.map((s) => s.values[i])]),
      ];
    case "heatmap":
      return [["", ...spec.labels], ...spec.labels.map((l, i) => [l, ...spec.values[i]])];
  }
}

/** Données du graphique en CSV (séparateur « ; », virgule décimale). Un libellé qui commence
 * par = + - @ (venu d'un fichier) est neutralisé : pas de formule à l'ouverture dans Excel. */
export function chartToCsv(spec: ChartSpec): string {
  const cell = (v: string | number | null) => {
    if (v === null) return "";
    let s = typeof v === "number" ? String(v).replace(".", ",") : v;
    if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return chartRows(spec)
    .map((r) => r.map(cell).join(";"))
    .join("\n");
}
