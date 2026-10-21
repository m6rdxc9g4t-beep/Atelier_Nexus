/**
 * Validation locale d'un workflow v2, immédiate pendant l'édition : mêmes codes et même forme
 * que `POST /api/workflows/validate` (le serveur reste l'autorité : disponibilité des apps,
 * schémas d'entrée). Logique pure, testée dans validate.test.ts.
 */

import type { CatalogEntry, ValidationError, WorkflowParam, WorkflowStepV2 } from "@/types/api";

import { MAX_PARAMS, MAX_STEPS, STEP_ID, ancestors, cyclicSteps } from "./graph";
import { parseRef, templateRefs } from "./refs";

/** Outils qui appellent un modèle ou n'ont pas de sens sans lui (docs/workflows-v2-api.md §6). */
export const NOT_REPLAYABLE = new Set(["tool:delegate_to_agent", "tool:current_datetime"]);

const err = (step_id: string | null, field: string | null, code: string, message: string): ValidationError => ({
  step_id,
  field,
  code,
  message,
});

/** Premier segment de chemin d'une entrée (« filters[0].field » → « filters »). */
const topField = (path: string) => path.split(/[.[]/)[0] ?? path;

/** Chemins (« a.b[0] ») des chaînes d'une valeur, avec la chaîne. */
function stringsWithPath(value: unknown, path = ""): { path: string; text: string }[] {
  if (typeof value === "string") return [{ path, text: value }];
  if (Array.isArray(value)) return value.flatMap((v, i) => stringsWithPath(v, `${path}[${i}]`));
  if (value && typeof value === "object")
    return Object.entries(value).flatMap(([k, v]) => stringsWithPath(v, path ? `${path}.${k}` : k));
  return [];
}

export interface LocalValidationInput {
  title?: string;
  steps: WorkflowStepV2[];
  params: WorkflowParam[];
  /** Sans catalogue (pas encore chargé) : `UNKNOWN_USES` / `UNAVAILABLE` ne sont pas vérifiés. */
  catalog?: Map<string, CatalogEntry> | null;
}

export function validateLocal({ steps, params, catalog }: LocalValidationInput): ValidationError[] {
  const errors: ValidationError[] = [];
  if (steps.length === 0) errors.push(err(null, null, "NO_STEPS", "Ajoutez au moins une étape."));
  if (steps.length > MAX_STEPS)
    errors.push(err(null, null, "TOO_MANY_STEPS", `${MAX_STEPS} étapes au plus (${steps.length}).`));
  if (params.length > MAX_PARAMS)
    errors.push(err(null, "params", "TOO_MANY_PARAMS", `${MAX_PARAMS} paramètres au plus.`));

  const declared = new Set<string>();
  for (const p of params) {
    if (!STEP_ID.test(p.name))
      errors.push(err(null, `params.${p.name}`, "BAD_PARAM", `Nom de paramètre invalide : « ${p.name} » (a-z, 0-9, _).`));
    else if (declared.has(p.name))
      errors.push(err(null, `params.${p.name}`, "DUPLICATE_PARAM", `Paramètre « ${p.name} » déclaré deux fois.`));
    declared.add(p.name);
  }

  const seen = new Set<string>();
  const ids = new Set(steps.map((s) => s.id));
  for (const step of steps) {
    if (!STEP_ID.test(step.id))
      errors.push(
        err(step.id, "id", "BAD_ID", "Identifiant invalide : minuscule en tête, puis a-z, 0-9 ou _ (40 caractères au plus)."),
      );
    if (seen.has(step.id)) errors.push(err(step.id, "id", "DUPLICATE_ID", `Identifiant « ${step.id} » déjà utilisé.`));
    seen.add(step.id);

    if (NOT_REPLAYABLE.has(step.uses))
      errors.push(err(step.id, null, "NOT_REPLAYABLE", "Cette étape fait appel à un modèle : impossible à rejouer."));
    else if (catalog) {
      const entry = catalog.get(step.uses);
      if (!entry) errors.push(err(step.id, null, "UNKNOWN_USES", `Étape inconnue du catalogue : ${step.uses}.`));
      else if (!entry.available)
        errors.push(err(step.id, null, "UNAVAILABLE", entry.unavailable_reason ?? "Application indisponible."));
    }

    for (const need of step.needs)
      if (!ids.has(need)) errors.push(err(step.id, "needs", "UNKNOWN_NEED", `Étape amont inconnue : « ${need} ».`));
  }

  const cyclic = cyclicSteps(steps);
  for (const id of cyclic)
    errors.push(err(id, "needs", "CYCLE", "Boucle dans les dépendances : une étape ne peut pas s'attendre elle-même."));

  for (const step of steps) {
    const upstream = ancestors(steps, step.id);
    const fields = [
      ...stringsWithPath(step.input).map((s) => ({ ...s, field: topField(s.path) })),
      ...stringsWithPath(step.when ?? null).map((s) => ({ ...s, field: "when" })),
    ];
    const reported = new Set<string>();
    for (const { text, field } of fields) {
      for (const expr of templateRefs(text)) {
        const ref = parseRef(expr);
        const key = `${field}|${expr}`;
        if (reported.has(key)) continue;
        reported.add(key);
        if (ref.kind === "param" && !declared.has(ref.name))
          errors.push(err(step.id, field, "UNDECLARED_PARAM", `Paramètre non déclaré : « ${ref.name} ».`));
        else if (ref.kind === "step" && !upstream.has(ref.step))
          errors.push(
            err(
              step.id,
              field,
              "REF_NOT_ANCESTOR",
              ref.step === step.id
                ? "Une étape ne peut pas citer sa propre sortie."
                : `« ${ref.step} » n'est pas une étape amont : reliez-la avant de citer sa sortie.`,
            ),
          );
        else if (ref.kind === "invalid")
          errors.push(err(step.id, field, "BAD_TEMPLATE", `Gabarit illisible : {{${ref.raw}}}.`));
      }
    }
    if (step.when) {
      const unary = step.when.op === "empty" || step.when.op === "not_empty";
      if (!step.when.left.trim()) errors.push(err(step.id, "when", "BAD_CONDITION", "Condition : valeur à tester manquante."));
      if (!unary && (step.when.right === undefined || step.when.right === ""))
        errors.push(err(step.id, "when", "BAD_CONDITION", "Condition : valeur de comparaison manquante."));
    }
  }
  return errors;
}

/** Erreurs d'une étape regroupées par champ (null = l'étape entière). */
export function errorsByField(errors: ValidationError[], stepId: string): Map<string | null, ValidationError[]> {
  const map = new Map<string | null, ValidationError[]>();
  for (const e of errors) {
    if (e.step_id !== stepId) continue;
    const key = e.field ? topField(e.field) : null;
    map.set(key, [...(map.get(key) ?? []), e]);
  }
  return map;
}

/** Erreurs qui ne visent aucune étape (paramètres, nombre d'étapes…). */
export const globalErrors = (errors: ValidationError[]): ValidationError[] => errors.filter((e) => !e.step_id);
