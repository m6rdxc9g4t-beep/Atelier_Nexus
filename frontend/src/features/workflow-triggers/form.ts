/**
 * Formulaire d'un déclencheur (docs/declencheurs-api.md §1) : brouillon ↔ corps de l'API, validation
 * locale aux bornes du contrat, gabarits {{event.…}}, événement d'exemple pour « Tester maintenant ».
 * Logique pure, testée dans form.test.ts.
 */

import type {
  AtelierEvent,
  EventFilter,
  EventFilterOp,
  EventsCatalog,
  EventsCatalogApp,
  Trigger,
  TriggerApp,
  TriggerBody,
  WorkflowParam,
  Weekday,
} from "@/types/api";

import { WEEKDAYS } from "./summary";

// ─── Bornes du contrat ───────────────────────────────────────────

export const LIMITS = {
  everyMinutes: { min: 5, max: 1440 },
  maxRunsPerHour: { min: 1, max: 120, default: 12 },
  debounceSeconds: { min: 0, max: 3600, default: 0 },
  types: { min: 1, max: 10 },
  filters: { max: 10 },
} as const;

export const TRIGGER_APPS: TriggerApp[] = ["viz", "projets", "tab", "wiki", "formulaire"];

/** Applications qui peuvent déclencher un workflow sur événement (contrat §1). */
export const isTriggerApp = (app: string): app is TriggerApp => (TRIGGER_APPS as string[]).includes(app);

export const FILTER_OPS: { value: EventFilterOp; label: string }[] = [
  { value: "eq", label: "est égal à" },
  { value: "ne", label: "est différent de" },
  { value: "in", label: "fait partie de" },
  { value: "contains", label: "contient" },
  { value: "gt", label: "est supérieur à" },
  { value: "gte", label: "est supérieur ou égal à" },
  { value: "lt", label: "est inférieur à" },
  { value: "lte", label: "est inférieur ou égal à" },
  { value: "exists", label: "est renseigné" },
];

/** Champs toujours proposés pour un filtre, en plus de ceux du catalogue. */
export const BASE_FILTER_FIELDS = ["subject.id", "subject.label", "type"];

// ─── Brouillon ───────────────────────────────────────────────────

/** Filtre en cours de saisie : la valeur reste du texte (« CLOSED, RESOLVED » pour « fait partie de »). */
export interface FilterDraft {
  path: string;
  op: EventFilterOp;
  value: string;
}

/** Brouillon : les nombres restent du texte tant que la saisie n'est pas finie. */
export interface TriggerDraft {
  /** null : nouveau déclencheur */
  id: string | null;
  kind: "schedule" | "event";
  label: string;
  enabled: boolean;
  params: Record<string, string>;
  maxRunsPerHour: string;
  // Horaire
  scheduleKind: "interval" | "daily";
  everyMinutes: string;
  at: string;
  days: Weekday[];
  // Événement
  app: TriggerApp | "";
  types: string[];
  filters: FilterDraft[];
  debounceSeconds: string;
}

export const WORKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri"];

export function emptyTriggerDraft(kind: "schedule" | "event", preset: Partial<TriggerDraft> = {}): TriggerDraft {
  return {
    id: null,
    kind,
    label: "",
    enabled: true,
    params: {},
    maxRunsPerHour: String(LIMITS.maxRunsPerHour.default),
    scheduleKind: "daily",
    everyMinutes: "60",
    at: "08:00",
    days: [...WORKDAYS],
    app: "",
    types: [],
    filters: [],
    debounceSeconds: String(LIMITS.debounceSeconds.default),
    ...preset,
  };
}

const filterValueText = (filter: EventFilter): string => {
  if (filter.op === "exists" || filter.value === undefined || filter.value === null) return "";
  if (Array.isArray(filter.value)) return filter.value.map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(", ");
  return typeof filter.value === "string" ? filter.value : JSON.stringify(filter.value);
};

/** Déclencheur enregistré → brouillon. */
export function draftFromTrigger(trigger: Trigger): TriggerDraft {
  const base = emptyTriggerDraft(trigger.kind, {
    id: trigger.id,
    label: trigger.label,
    enabled: trigger.enabled,
    params: { ...trigger.params },
    maxRunsPerHour: String(trigger.max_runs_per_hour),
  });
  if (trigger.kind === "schedule") {
    const s = trigger.schedule;
    return s.kind === "interval"
      ? { ...base, scheduleKind: "interval", everyMinutes: String(s.every_minutes) }
      : { ...base, scheduleKind: "daily", at: s.at, days: [...s.days] };
  }
  return {
    ...base,
    app: trigger.app,
    types: [...trigger.types],
    filters: trigger.filters.map((f) => ({ path: f.path, op: f.op, value: filterValueText(f) })),
    debounceSeconds: String(trigger.debounce_seconds),
  };
}

/**
 * Valeur saisie → valeur JSON du filtre : liste pour « fait partie de » (séparée par des virgules),
 * nombre pour les comparaisons d'ordre, sinon texte (les identifiants des événements sont des chaînes).
 */
export function filterValue(op: EventFilterOp, text: string): unknown {
  if (op === "exists") return undefined;
  if (op === "in")
    return text
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
  if (op === "gt" || op === "gte" || op === "lt" || op === "lte") {
    const n = Number(text.trim().replace(",", "."));
    return text.trim() !== "" && Number.isFinite(n) ? n : text.trim();
  }
  if (text === "true" || text === "false") return text === "true";
  return text;
}

const toInt = (text: string): number => Number.parseInt(text.trim(), 10);

/** Ordre de la semaine, sans doublon. */
const sortDays = (days: Weekday[]): Weekday[] => WEEKDAYS.filter((d) => days.includes(d));

/**
 * Paramètres envoyés : seulement ceux que le workflow déclare, et seulement s'ils diffèrent de la
 * valeur par défaut (vide = garder le défaut du workflow).
 */
export function cleanParams(values: Record<string, string>, params: WorkflowParam[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of params) {
    const v = values[p.name];
    if (v !== undefined && v !== "" && v !== p.default) out[p.name] = v;
  }
  return out;
}

/** Corps de l'API (à n'envoyer qu'après `validateTrigger` sans erreur). */
export function toTriggerBody(draft: TriggerDraft, params: WorkflowParam[]): TriggerBody {
  const base = {
    label: draft.label.trim(),
    enabled: draft.enabled,
    params: cleanParams(draft.params, params),
    max_runs_per_hour: toInt(draft.maxRunsPerHour),
  };
  if (draft.kind === "schedule")
    return {
      ...base,
      kind: "schedule",
      schedule:
        draft.scheduleKind === "interval"
          ? { kind: "interval", every_minutes: toInt(draft.everyMinutes) }
          : { kind: "daily", at: normalizeTime(draft.at) ?? draft.at, days: sortDays(draft.days) },
    };
  return {
    ...base,
    kind: "event",
    app: draft.app as TriggerApp,
    types: [...new Set(draft.types)],
    filters: draft.filters.map((f) => {
      const value = filterValue(f.op, f.value);
      return value === undefined ? { path: f.path.trim(), op: f.op } : { path: f.path.trim(), op: f.op, value };
    }),
    debounce_seconds: toInt(draft.debounceSeconds),
  };
}

/**
 * Corps d'un déclencheur enregistré, tel quel, avec quelques champs changés (interrupteur
 * actif / coupé) : rien n'est recalculé ni retiré.
 */
export function bodyFromTrigger(trigger: Trigger, patch: Partial<Pick<TriggerBody, "enabled" | "label">> = {}): TriggerBody {
  const base = {
    label: trigger.label,
    enabled: trigger.enabled,
    params: { ...trigger.params },
    max_runs_per_hour: trigger.max_runs_per_hour,
    ...patch,
  };
  if (trigger.kind === "schedule") return { ...base, kind: "schedule", schedule: trigger.schedule };
  return {
    ...base,
    kind: "event",
    app: trigger.app,
    types: [...trigger.types],
    filters: trigger.filters.map((f) => ({ ...f })),
    debounce_seconds: trigger.debounce_seconds,
  };
}

/** Le déclencheur (corps) entier, pour comparer « modifié ». */
export const triggerSignature = (draft: TriggerDraft, params: WorkflowParam[]) => JSON.stringify(toTriggerBody(draft, params));

// ─── Validation locale ───────────────────────────────────────────

/** "8:05" → "08:05" ; null si l'heure n'est pas valide (24 h). */
export function normalizeTime(text: string): string | null {
  const m = /^\s*(\d{1,2}):(\d{2})\s*$/.exec(text);
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, "0")}:${m[2]}`;
}

/** Erreurs par champ : `label`, `every_minutes`, `at`, `days`, `app`, `types`, `filters.<i>`, `debounce_seconds`, `max_runs_per_hour`, `params.<nom>`. */
export type TriggerErrors = Record<string, string>;

const EVENT_TEMPLATE = /\{\{\s*event\b[^{}]*\}\}/;
const ANY_TEMPLATE = /\{\{\s*([^{}]*?)\s*\}\}/g;

/** Gabarits {{event.…}} reconnus par le contrat. */
const EVENT_EXPR = /^event\.(type|seq|at|subject\.(id|label|kind)|data(\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+)$/;

function intError(text: string, min: number, max: number, unit: string): string | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return `Nombre entier attendu (${min} à ${max} ${unit}).`;
  const n = Number(t);
  if (n < min || n > max) return `Entre ${min} et ${max} ${unit}.`;
  return null;
}

/**
 * Validation immédiate, aux bornes du contrat (le serveur reste l'autorité : types déclarés par le
 * manifeste, paramètres connus). `catalogApp` : app choisie dans le catalogue, pour signaler un type inconnu.
 */
export function validateTrigger(
  draft: TriggerDraft,
  params: WorkflowParam[],
  catalogApp?: EventsCatalogApp | null,
): TriggerErrors {
  const errors: TriggerErrors = {};
  if (draft.label.length > 120) errors.label = "120 caractères au plus.";

  const runs = intError(draft.maxRunsPerHour, LIMITS.maxRunsPerHour.min, LIMITS.maxRunsPerHour.max, "lancements par heure");
  if (runs) errors.max_runs_per_hour = runs;

  if (draft.kind === "schedule") {
    if (draft.scheduleKind === "interval") {
      const e = intError(draft.everyMinutes, LIMITS.everyMinutes.min, LIMITS.everyMinutes.max, "minutes");
      if (e) errors.every_minutes = e;
    } else {
      if (!normalizeTime(draft.at)) errors.at = "Heure au format HH:MM (24 h), par exemple 08:00.";
      if (sortDays(draft.days).length === 0) errors.days = "Choisissez au moins un jour.";
    }
  } else {
    if (!draft.app) errors.app = "Choisissez l'application qui publie l'événement.";
    const types = [...new Set(draft.types)];
    if (types.length < LIMITS.types.min) errors.types = "Cochez au moins un type d'événement.";
    else if (types.length > LIMITS.types.max) errors.types = `${LIMITS.types.max} types au plus.`;
    else if (catalogApp && catalogApp.events.length > 0) {
      const unknown = types.filter((t) => !catalogApp.events.some((e) => e.type === t));
      if (unknown.length) errors.types = `Type(s) inconnu(s) de ${catalogApp.name} : ${unknown.join(", ")}.`;
    }
    if (draft.filters.length > LIMITS.filters.max) errors.filters = `${LIMITS.filters.max} filtres au plus.`;
    draft.filters.forEach((f, i) => {
      if (!f.path.trim()) errors[`filters.${i}`] = "Choisissez le champ à tester.";
      else if (!/^(type|subject\.(id|label|kind)|data(\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+)$/.test(f.path.trim()))
        errors[`filters.${i}`] = "Champ attendu : type, subject.id, subject.label ou data.<champ>.";
      else if (f.op === "in" && (filterValue("in", f.value) as string[]).length === 0)
        errors[`filters.${i}`] = "Donnez au moins une valeur (séparées par des virgules).";
      else if (f.op !== "exists" && f.op !== "in" && f.value.trim() === "") errors[`filters.${i}`] = "Donnez la valeur à comparer.";
      else if (EVENT_TEMPLATE.test(f.value)) errors[`filters.${i}`] = "Les gabarits {{event.…}} ne servent que dans les paramètres.";
    });
    const debounce = intError(draft.debounceSeconds, LIMITS.debounceSeconds.min, LIMITS.debounceSeconds.max, "secondes");
    if (debounce) errors.debounce_seconds = debounce;
  }

  if (EVENT_TEMPLATE.test(draft.label)) errors.label = "Les gabarits {{event.…}} ne servent que dans les paramètres.";

  for (const [name, value] of Object.entries(draft.params)) {
    if (!value) continue;
    if (!params.some((p) => p.name === name)) {
      errors[`params.${name}`] = "Ce paramètre n'existe plus dans le workflow.";
      continue;
    }
    for (const match of value.matchAll(ANY_TEMPLATE)) {
      const expr = match[1]!;
      if (!expr.startsWith("event")) continue;
      if (draft.kind === "schedule") {
        errors[`params.${name}`] = "Un horaire n'a pas d'événement : {{event.…}} n'est utilisable qu'avec un déclencheur événement.";
        break;
      }
      if (!EVENT_EXPR.test(expr)) {
        errors[`params.${name}`] = `Gabarit inconnu : {{${expr}}}.`;
        break;
      }
    }
  }
  return errors;
}

export const hasErrors = (errors: TriggerErrors) => Object.keys(errors).length > 0;

// ─── Gabarits {{event.…}} ────────────────────────────────────────

export interface EventTemplateOption {
  label: string;
  value: string;
  hint?: string;
}

export interface EventTemplateGroup {
  label: string;
  options: EventTemplateOption[];
}

/**
 * Propositions du menu « Utiliser… » d'un paramètre : sujet et méta de l'événement, puis les champs
 * `data.*` annoncés par le catalogue pour les types cochés (sans doublon).
 */
export function eventTemplateOptions(app: EventsCatalogApp | null | undefined, types: string[]): EventTemplateGroup[] {
  const groups: EventTemplateGroup[] = [
    {
      label: "Sujet de l'événement",
      options: [
        { label: "Identifiant", value: "{{event.subject.id}}", hint: "ex. 123" },
        { label: "Libellé", value: "{{event.subject.label}}", hint: "ex. Écrire la doc" },
        { label: "Nature", value: "{{event.subject.kind}}", hint: "ex. work_item" },
      ],
    },
  ];
  const fields: string[] = [];
  for (const ev of app?.events ?? []) {
    if (types.length && !types.includes(ev.type)) continue;
    for (const f of ev.fields) if (f.startsWith("data.") && !fields.includes(f)) fields.push(f);
  }
  if (fields.length)
    groups.push({
      label: "Données de l'événement",
      options: fields.map((f) => ({ label: f.slice(5), value: `{{event.${f}}}` })),
    });
  groups.push({
    label: "Événement",
    options: [
      { label: "Type", value: "{{event.type}}" },
      { label: "Date", value: "{{event.at}}", hint: "ISO 8601" },
      { label: "Numéro", value: "{{event.seq}}" },
    ],
  });
  return groups;
}

/** Insère un gabarit dans un paramètre (texte) : ajouté à la suite, séparé par une espace. */
export function insertEventTemplate(current: string, tpl: string): string {
  if (!current) return tpl;
  return /\s$/.test(current) ? `${current}${tpl}` : `${current} ${tpl}`;
}

// ─── Catalogue et événement d'exemple ────────────────────────────

/** Champs proposés pour un filtre : ceux des types cochés (ou de toute l'app), puis les champs de base. */
export function filterFields(app: EventsCatalogApp | null | undefined, types: string[]): string[] {
  const out: string[] = [];
  for (const ev of app?.events ?? []) {
    if (types.length && !types.includes(ev.type)) continue;
    for (const f of ev.fields) if (!out.includes(f)) out.push(f);
  }
  for (const f of BASE_FILTER_FIELDS) if (!out.includes(f)) out.push(f);
  return out;
}

export const catalogApp = (catalog: EventsCatalog | null | undefined, app: string): EventsCatalogApp | null =>
  catalog?.apps.find((a) => a.app === app) ?? null;

/** Valeur d'exemple d'un champ `data.<chemin>` (statuts Atelier pour from / to, identifiants en texte). */
function sampleValue(path: string): unknown {
  const key = path.split(/[.[]/).pop() ?? path;
  if (key === "to") return "CLOSED";
  if (key === "from") return "IN_PROGRESS";
  if (key === "status") return "ok";
  if (key === "trigger") return "manual";
  if (key === "rows" || key === "pages" || key === "value" || key === "threshold" || key === "count") return 1;
  if (key.endsWith("_id") || key === "id") return "1";
  if (key.endsWith("_at")) return "2026-10-21T08:00:00+02:00";
  return "exemple";
}

/** Écrit `value` au chemin `a.b[0].c` dans `target` (objets et listes créés au besoin). */
function setPath(target: Record<string, unknown>, path: string, value: unknown) {
  const keys = [...path.matchAll(/([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]/g)].map((m) => (m[1] !== undefined ? m[1] : Number(m[2])));
  let node: Record<string | number, unknown> = target;
  keys.forEach((key, i) => {
    if (i === keys.length - 1) {
      node[key] = value;
      return;
    }
    const nextIsIndex = typeof keys[i + 1] === "number";
    if (node[key] === undefined || typeof node[key] !== "object" || node[key] === null) node[key] = nextIsIndex ? [] : {};
    node = node[key] as Record<string | number, unknown>;
  });
}

/** Nature du sujet déduite du type (« projets.work_item.status_changed » → « work_item »). */
const subjectKind = (type: string) => type.split(".")[1] ?? "objet";

/**
 * Événement d'exemple pour « Tester maintenant » : premier type coché, champs `data.*` du catalogue
 * remplis, et les filtres d'égalité respectés (l'exemple passe les filtres du déclencheur).
 */
export function sampleEvent(
  app: EventsCatalogApp | null | undefined,
  types: string[],
  filters: FilterDraft[] = [],
  now: Date = new Date(),
): AtelierEvent {
  const type = types[0] ?? app?.events[0]?.type ?? "evenement";
  const ev = app?.events.find((e) => e.type === type);
  const event: AtelierEvent = {
    seq: 0,
    type,
    at: now.toISOString(),
    subject: { kind: subjectKind(type), id: "1", label: "Exemple" },
    data: {},
  };
  for (const field of ev?.fields ?? []) {
    if (field.startsWith("data.")) setPath(event.data, field.slice(5), sampleValue(field));
  }
  for (const f of filters) {
    const path = f.path.trim();
    if (f.op !== "eq" && f.op !== "in") continue;
    const value = f.op === "in" ? (filterValue("in", f.value) as string[])[0] : filterValue("eq", f.value);
    if (value === undefined || value === "") continue;
    if (path.startsWith("data.")) setPath(event.data, path.slice(5), value);
    else if (path === "subject.id" || path === "subject.label" || path === "subject.kind")
      event.subject = { ...event.subject, [path.slice(8)]: String(value) };
  }
  return event;
}

/** Lecture de l'événement d'exemple modifié en JSON : forme minimale vérifiée. */
export function parseSampleEvent(text: string): { ok: true; event: AtelierEvent } | { ok: false; error: string } {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, error: "JSON invalide." };
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return { ok: false, error: "Objet JSON { … } attendu." };
  const ev = value as Partial<AtelierEvent>;
  if (typeof ev.type !== "string" || !ev.type) return { ok: false, error: "Champ « type » (texte) attendu." };
  const subject = ev.subject as Partial<AtelierEvent["subject"]> | undefined;
  if (!subject || typeof subject !== "object" || typeof subject.id !== "string" || typeof subject.label !== "string" || typeof subject.kind !== "string")
    return { ok: false, error: "Champ « subject » attendu : { kind, id, label } en texte." };
  if (ev.data !== undefined && (typeof ev.data !== "object" || ev.data === null || Array.isArray(ev.data)))
    return { ok: false, error: "Champ « data » : objet attendu." };
  return {
    ok: true,
    event: {
      seq: typeof ev.seq === "number" ? ev.seq : 0,
      type: ev.type,
      at: typeof ev.at === "string" ? ev.at : new Date().toISOString(),
      subject: { kind: subject.kind, id: subject.id, label: subject.label },
      data: (ev.data as Record<string, unknown> | undefined) ?? {},
    },
  };
}
