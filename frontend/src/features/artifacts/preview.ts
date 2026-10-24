/**
 * Lecture des artefacts `data_preview` produits par le connecteur Data Via :
 *  - vue « query »  : { columns: QueryColumn[], rows: Scalar[][] }
 *  - vue « schema » : { columns: ColumnProfile[], measures: [...], sample: object[] }
 * Fonctions pures (testées dans preview.test.ts).
 */

import type { Scalar } from "@/types/api";

export interface TableData {
  headers: string[];
  /** Colonnes numériques : alignées à droite. */
  numeric: boolean[];
  rows: Scalar[][];
}

export interface SchemaData {
  columns: { name: string; type: string; distinct: number; nulls: number }[];
  measures: { name: string; expression: string }[];
  sample: TableData | null;
}

export type PreviewData = { view: "table"; table: TableData } | { view: "schema"; schema: SchemaData };

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const asScalar = (v: unknown): Scalar => {
  if (v === null || v === undefined) return null;
  return ["string", "number", "boolean"].includes(typeof v) ? (v as Scalar) : JSON.stringify(v);
};

/** Tableau à partir de lignes-objets (échantillon) : colonnes = union des clés, dans l'ordre. */
export function tableFromObjects(items: unknown[]): TableData | null {
  const records = items.filter(isRecord);
  if (!records.length) return null;
  const headers = [...new Set(records.flatMap((r) => Object.keys(r)))];
  const rows = records.map((r) => headers.map((h) => asScalar(r[h])));
  const numeric = headers.map((_, i) => rows.every((row) => row[i] === null || typeof row[i] === "number"));
  return { headers, numeric, rows };
}

export function parsePreview(content: string): PreviewData | null {
  let data: unknown;
  try {
    data = JSON.parse(content);
  } catch {
    return null;
  }
  if (!isRecord(data) || !Array.isArray(data.columns)) return null;

  // Vue requête : colonnes {key, type} + lignes en tableaux
  if (Array.isArray(data.rows)) {
    const columns = data.columns.filter(isRecord);
    return {
      view: "table",
      table: {
        headers: columns.map((c) => String(c.key ?? "")),
        numeric: columns.map((c) => c.type === "number"),
        rows: data.rows.filter(Array.isArray).map((row) => row.map(asScalar)),
      },
    };
  }

  // Vue schéma : profils de colonnes + mesures + échantillon
  return {
    view: "schema",
    schema: {
      columns: data.columns.filter(isRecord).map((c) => ({
        name: String(c.name ?? ""),
        type: String(c.type ?? ""),
        distinct: Number(c.distinct ?? 0),
        nulls: Number(c.nulls ?? 0),
      })),
      measures: (Array.isArray(data.measures) ? data.measures : [])
        .filter(isRecord)
        .map((m) => ({ name: String(m.name ?? ""), expression: String(m.expression ?? "") })),
      sample: Array.isArray(data.sample) ? tableFromObjects(data.sample) : null,
    },
  };
}

/** Valeur affichée dans une cellule (nombres au format français). */
export function formatCell(value: Scalar): string {
  if (value === null) return "—";
  if (typeof value === "number") return value.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  return value;
}

/** Export CSV (séparateur « ; », comme Excel en français). */
export function toCsv(table: TableData): string {
  const esc = (v: Scalar) => {
    let s = v === null ? "" : typeof v === "number" ? String(v).replace(".", ",") : String(v);
    // Texte commençant par = + - @ : neutralisé (pas de formule à l'ouverture dans Excel)
    if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [table.headers, ...table.rows].map((row) => row.map(esc).join(";")).join("\n");
}
