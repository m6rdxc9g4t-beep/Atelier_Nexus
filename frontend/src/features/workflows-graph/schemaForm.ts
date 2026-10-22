/**
 * Formulaire généré depuis le JSON Schema d'entrée d'une étape (`input_schema`) : nature de
 * chaque champ, lecture de la saisie, valeurs affichées. Les gabarits {{…}} sont acceptés
 * partout (vérifiés à l'exécution). Logique pure, testée dans schemaForm.test.ts.
 */

import { isExactTemplate } from "./refs";

export type FieldKind = "string" | "number" | "integer" | "boolean" | "enum" | "array" | "json";
export type PrimitiveKind = "string" | "number" | "integer" | "boolean";

export interface FormField {
  name: string;
  label: string;
  description: string;
  kind: FieldKind;
  required: boolean;
  /** Valeurs d'un enum (ou d'un tableau d'enum) */
  options?: unknown[];
  /** Nature des éléments d'un tableau de primitifs */
  itemKind?: PrimitiveKind;
  default?: unknown;
  format?: string;
  multiline?: boolean;
  minimum?: number;
  maximum?: number;
}

type Schema = Record<string, unknown>;

const asSchema = (v: unknown): Schema => (v && typeof v === "object" && !Array.isArray(v) ? (v as Schema) : {});

/** Type principal d'un schéma : `type` (tableau autorisé, `null` ignoré), sinon anyOf / oneOf à une branche non nulle. */
function mainType(schema: Schema): string | null {
  const t = schema.type;
  if (typeof t === "string") return t;
  if (Array.isArray(t)) {
    const types = t.filter((x) => x !== "null");
    return types.length === 1 ? String(types[0]) : null;
  }
  for (const key of ["anyOf", "oneOf"] as const) {
    const branches = Array.isArray(schema[key]) ? (schema[key] as unknown[]).map(asSchema) : [];
    const nonNull = branches.filter((b) => b.type !== "null");
    if (nonNull.length === 1) return mainType(nonNull[0]!);
  }
  if (Array.isArray(schema.enum)) return "enum";
  if (schema.const !== undefined) return "enum";
  return null;
}

/** Schéma effectif (première branche non nulle d'un anyOf / oneOf). */
function effective(schema: Schema): Schema {
  if (schema.type !== undefined || schema.enum !== undefined) return schema;
  for (const key of ["anyOf", "oneOf"] as const) {
    const branches = Array.isArray(schema[key]) ? (schema[key] as unknown[]).map(asSchema) : [];
    const nonNull = branches.filter((b) => b.type !== "null");
    if (nonNull.length === 1) return { ...nonNull[0], ...schema, anyOf: undefined, oneOf: undefined };
  }
  return schema;
}

const PRIMITIVES = new Set(["string", "number", "integer", "boolean"]);

export function fieldFromSchema(name: string, raw: unknown, required: boolean): FormField {
  const schema = effective(asSchema(raw));
  const type = mainType(schema);
  const base: FormField = {
    name,
    label: typeof schema.title === "string" && schema.title ? schema.title : name,
    description: typeof schema.description === "string" ? schema.description : "",
    kind: "json",
    required,
    default: schema.default,
    format: typeof schema.format === "string" ? schema.format : undefined,
  };
  const enumValues = Array.isArray(schema.enum) ? schema.enum : schema.const !== undefined ? [schema.const] : null;
  if (enumValues && enumValues.every((v) => v === null || ["string", "number", "boolean"].includes(typeof v)))
    return { ...base, kind: "enum", options: enumValues.filter((v) => v !== null) };
  if (type === "string") {
    const long = typeof schema.maxLength === "number" ? schema.maxLength > 200 : false;
    return { ...base, kind: "string", multiline: long || schema.format === "textarea" };
  }
  if (type === "number" || type === "integer")
    return {
      ...base,
      kind: type,
      minimum: typeof schema.minimum === "number" ? schema.minimum : undefined,
      maximum: typeof schema.maximum === "number" ? schema.maximum : undefined,
    };
  if (type === "boolean") return { ...base, kind: "boolean" };
  if (type === "array") {
    const items = effective(asSchema(schema.items));
    const itemType = mainType(items);
    if (itemType && PRIMITIVES.has(itemType)) return { ...base, kind: "array", itemKind: itemType as PrimitiveKind };
    if (itemType === "enum" && Array.isArray(items.enum)) return { ...base, kind: "array", itemKind: "string", options: items.enum };
  }
  return base;
}

/** Champs d'un schéma d'objet : requis d'abord, puis l'ordre déclaré. */
export function fieldsFromSchema(schema: Record<string, unknown> | null | undefined): FormField[] {
  const s = asSchema(schema);
  const properties = asSchema(s.properties);
  const required = new Set(Array.isArray(s.required) ? s.required.map(String) : []);
  const fields = Object.entries(properties).map(([name, sub]) => fieldFromSchema(name, sub, required.has(name)));
  return [...fields.filter((f) => f.required), ...fields.filter((f) => !f.required)];
}

/** Clés de l'entrée que le schéma ne décrit pas (affichées en JSON, jamais perdues). */
export const extraKeys = (input: Record<string, unknown>, fields: FormField[]): string[] =>
  Object.keys(input).filter((k) => !fields.some((f) => f.name === k));

// ─── Saisie ↔ valeur ─────────────────────────────────────────────

export type Parsed = { ok: true; value: unknown } | { ok: false; error: string };

const parsePrimitive = (text: string, kind: PrimitiveKind): Parsed => {
  const trimmed = text.trim();
  if (isExactTemplate(trimmed)) return { ok: true, value: trimmed };
  if (kind === "string") return { ok: true, value: text };
  if (kind === "boolean") {
    if (["true", "vrai", "oui"].includes(trimmed.toLowerCase())) return { ok: true, value: true };
    if (["false", "faux", "non"].includes(trimmed.toLowerCase())) return { ok: true, value: false };
    return { ok: false, error: "Vrai ou faux attendu." };
  }
  const n = Number(trimmed.replace(",", "."));
  if (!trimmed || !Number.isFinite(n)) return { ok: false, error: "Nombre attendu (ou gabarit {{…}})." };
  if (kind === "integer" && !Number.isInteger(n)) return { ok: false, error: "Nombre entier attendu." };
  return { ok: true, value: n };
};

/**
 * Lit la saisie d'un champ. Vide → `undefined` (la clé est retirée de l'entrée). Un gabarit
 * exact est gardé tel quel quelle que soit la nature du champ.
 */
export function parseFieldInput(field: FormField, text: string): Parsed {
  if (text.trim() === "") return { ok: true, value: undefined };
  switch (field.kind) {
    case "string":
      return { ok: true, value: text };
    case "number":
    case "integer":
    case "boolean":
      return parsePrimitive(text, field.kind);
    case "enum": {
      if (isExactTemplate(text)) return { ok: true, value: text.trim() };
      const match = (field.options ?? []).find((o) => String(o) === text);
      return match === undefined ? { ok: false, error: "Valeur hors liste." } : { ok: true, value: match };
    }
    case "array": {
      if (isExactTemplate(text)) return { ok: true, value: text.trim() };
      const items = text
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const values: unknown[] = [];
      for (const [i, item] of items.entries()) {
        const parsed = parsePrimitive(item, field.itemKind ?? "string");
        if (!parsed.ok) return { ok: false, error: `Ligne ${i + 1} : ${parsed.error}` };
        values.push(parsed.value);
      }
      return { ok: true, value: values };
    }
    case "json": {
      if (isExactTemplate(text)) return { ok: true, value: text.trim() };
      try {
        return { ok: true, value: JSON.parse(text) as unknown };
      } catch {
        return { ok: false, error: "JSON invalide." };
      }
    }
  }
}

/** Texte affiché dans le champ pour une valeur de l'entrée. */
export function formatFieldValue(field: FormField, value: unknown): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if (field.kind === "array" && Array.isArray(value) && value.every((v) => typeof v !== "object" || v === null))
    return value.map((v) => String(v)).join("\n");
  if (field.kind === "json" || typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

/** Nouvelle entrée après modification d'un champ (`undefined` retire la clé). */
export function setInputValue(input: Record<string, unknown>, name: string, value: unknown): Record<string, unknown> {
  const next = { ...input };
  if (value === undefined) delete next[name];
  else next[name] = value;
  return next;
}

/** Champs requis encore vides. */
export const missingRequired = (fields: FormField[], input: Record<string, unknown>): string[] =>
  fields.filter((f) => f.required && (input[f.name] === undefined || input[f.name] === "")).map((f) => f.name);
