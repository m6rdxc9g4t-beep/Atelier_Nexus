/**
 * Logique pure de l'éditeur de workflows (testée dans form.test.ts) : étapes éditées en JSON,
 * paramètres `{{nom}}` détectés dans les étapes, préparation de l'envoi.
 */

import type { WorkflowFields, WorkflowParam, WorkflowRunResult, WorkflowStep } from "@/types/api";

/** Même motif que le backend (app/schemas/workflows.py). */
const PLACEHOLDER = /\{\{\s*([a-z][a-z0-9_]{0,39})\s*\}\}/g;

export interface StepDraft {
  /** Identifiant stable dans l'éditeur (clé React, étape dépliée) */
  key: string;
  tool: string;
  label: string;
  /** Entrée de l'outil, en JSON indenté, modifiable */
  inputText: string;
  /** Étape qui modifie des données (validation à chaque lancement) */
  writes: boolean;
}

export interface WorkflowForm {
  title: string;
  description: string;
  steps: StepDraft[];
  params: WorkflowParam[];
}

let stepSeq = 0;

export const stepDraft = (step: WorkflowStep, writes = false): StepDraft => ({
  key: `etape-${stepSeq++}`,
  tool: step.tool,
  label: step.label ?? "",
  inputText: JSON.stringify(step.input, null, 2),
  writes,
});

/** Noms de paramètres cités dans les étapes, dans l'ordre d'apparition, sans doublon. */
export function placeholderNames(texts: string[]): string[] {
  const names: string[] = [];
  for (const text of texts) {
    for (const match of text.matchAll(PLACEHOLDER)) {
      const name = match[1]!;
      if (!names.includes(name)) names.push(name);
    }
  }
  return names;
}

/** Paramètres alignés sur les étapes : on garde libellé et valeur par défaut déjà saisis. */
export function syncParams(steps: StepDraft[], params: WorkflowParam[]): WorkflowParam[] {
  return placeholderNames(steps.map((s) => s.inputText)).map(
    (name) => params.find((p) => p.name === name) ?? { name, label: "", default: "" },
  );
}

export interface Parsed {
  fields: WorkflowFields | null;
  errors: Record<string, string>;
}

/** Vérifie la saisie et prépare le corps envoyé à l'API. */
export function toFields(form: WorkflowForm): Parsed {
  const errors: Record<string, string> = {};
  if (!form.title.trim()) errors.title = "Donnez un titre au workflow.";
  if (form.steps.length === 0) errors.steps = "Il faut au moins une étape.";
  const steps: WorkflowStep[] = [];
  form.steps.forEach((draft, index) => {
    try {
      const input: unknown = JSON.parse(draft.inputText || "{}");
      if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("objet attendu");
      steps.push({ tool: draft.tool, label: draft.label, input: input as Record<string, unknown> });
    } catch {
      errors[`step-${index}`] = "JSON invalide : un objet { … } est attendu.";
    }
  });
  if (Object.keys(errors).length) return { fields: null, errors };
  return {
    fields: {
      title: form.title.trim(),
      description: form.description.trim(),
      steps,
      params: syncParams(form.steps, form.params).map((p) => ({
        name: p.name,
        label: p.label.trim(),
        default: p.default.trim(),
      })),
    },
    errors,
  };
}

/** Valeurs de départ du formulaire de lancement : la valeur par défaut de chaque paramètre. */
export const initialValues = (params: WorkflowParam[]): Record<string, string> =>
  Object.fromEntries(params.map((p) => [p.name, p.default]));

/** Paramètres encore vides (sans valeur ni valeur par défaut). */
export const missingParams = (params: WorkflowParam[], values: Record<string, string>): string[] =>
  params.filter((p) => !(values[p.name] ?? "").trim() && !p.default.trim()).map((p) => p.label || p.name);

/** Une décision par action en attente (clé : son jeton), pour pouvoir relancer. */
export const allDecided = (result: WorkflowRunResult, decisions: Record<string, boolean>): boolean =>
  result.pending.every((p) => decisions[p.token] !== undefined);
