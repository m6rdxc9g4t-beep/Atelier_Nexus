/**
 * Références {{…}} des workflows v2 (docs/workflows-v2-api.md §2) : lecture, renommage,
 * paramètres cités. Logique pure, testée dans templates.test.ts.
 */

import type { WorkflowStepV2 } from "@/types/api";

const TEMPLATE = /\{\{\s*([^{}]*?)\s*\}\}/g;
const EXACT = /^\s*\{\{\s*([^{}]*?)\s*\}\}\s*$/;
const NAME = /^[a-z][a-z0-9_]{0,39}$/;

export type Ref =
  | { kind: "param"; name: string; legacy: boolean }
  | { kind: "step"; step: string; path: string }
  | { kind: "run"; path: string }
  | { kind: "invalid"; raw: string };

/** Une valeur qui est exactement un gabarit garde le type JSON de sa cible. */
export const isExactTemplate = (value: unknown): boolean =>
  typeof value === "string" && EXACT.test(value);

/** Expressions citées (`params.x`, `steps.a.data`…) dans une valeur, récursivement. */
export function templateRefs(value: unknown): string[] {
  const found: string[] = [];
  const visit = (v: unknown) => {
    if (typeof v === "string") {
      for (const match of v.matchAll(TEMPLATE)) found.push(match[1]!);
    } else if (Array.isArray(v)) v.forEach(visit);
    else if (v && typeof v === "object") Object.values(v).forEach(visit);
  };
  visit(value);
  return found;
}

export function parseRef(expr: string): Ref {
  const raw = expr.trim();
  if (NAME.test(raw)) return { kind: "param", name: raw, legacy: true };
  const param = /^params\.([a-z][a-z0-9_]{0,39})$/.exec(raw);
  if (param) return { kind: "param", name: param[1]!, legacy: false };
  const step = /^steps\.([a-z][a-z0-9_]{0,39})((?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*)$/.exec(raw);
  if (step) return { kind: "step", step: step[1]!, path: step[2]!.replace(/^\./, "") };
  const run = /^run\.([a-z_]+)$/.exec(raw);
  if (run) return { kind: "run", path: run[1]! };
  return { kind: "invalid", raw };
}

export const template = (expr: string) => `{{${expr}}}`;

/** Remplace l'étape `from` par `to` dans les références `{{steps.from…}}`, récursivement. */
export function renameStepRefs<T>(value: T, from: string, to: string): T {
  const pattern = new RegExp(`(\\{\\{\\s*steps\\.)${from}(?=[.\\[\\s}])`, "g");
  const visit = (v: unknown): unknown => {
    if (typeof v === "string") return v.replace(pattern, `$1${to}`);
    if (Array.isArray(v)) return v.map(visit);
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, visit(x)]));
    return v;
  };
  return visit(value) as T;
}

/** Paramètres cités (`{{params.x}}` ou `{{x}}`) dans les étapes, dans l'ordre, sans doublon. */
export function referencedParams(steps: WorkflowStepV2[]): string[] {
  const names: string[] = [];
  for (const step of steps) {
    for (const expr of [...templateRefs(step.input), ...templateRefs(step.when ?? null)]) {
      const ref = parseRef(expr);
      if (ref.kind === "param" && !names.includes(ref.name)) names.push(ref.name);
    }
  }
  return names;
}
