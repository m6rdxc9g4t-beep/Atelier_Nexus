/**
 * Brouillon édité d'un workflow v2 (titre, agent, paramètres, étapes) ↔ corps de l'API, copie
 * d'un modèle de la suite, état d'enregistrement et fusion des erreurs locales et serveur.
 * Logique pure, testée dans draft.test.ts.
 */

import type { TemplateSeed } from "@/stores/useWorkflowStudioStore";
import type {
  Condition,
  StepPosition,
  ValidationError,
  WorkflowParam,
  WorkflowStepV2,
  WorkflowV2,
  WorkflowV2Body,
} from "@/types/api";

import { applyLayout } from "./graph";
import { referencedParams } from "./refs";

export interface WorkflowDraftV2 {
  /** null = nouveau workflow, pas encore enregistré */
  id: string | null;
  /** null = workflow de suite */
  agent: string | null;
  title: string;
  description: string;
  steps: WorkflowStepV2[];
  params: WorkflowParam[];
  sourceConversationId: string | null;
}

export const emptyDraft = (agent: string | null = null, steps: WorkflowStepV2[] = []): WorkflowDraftV2 => ({
  id: null,
  agent,
  title: "",
  description: "",
  steps: applyLayout(steps, true),
  params: [],
  sourceConversationId: null,
});

/** Workflow enregistré → brouillon ; les étapes sans position sont placées en couches. */
export const draftFromWorkflow = (wf: WorkflowV2): WorkflowDraftV2 => ({
  id: wf.id,
  agent: wf.agent,
  title: wf.title,
  description: wf.description,
  steps: applyLayout(
    wf.steps.map((s) => ({ ...s, needs: s.needs ?? [], on_error: s.on_error ?? "stop", when: s.when ?? null })),
    true,
  ),
  params: wf.params,
  sourceConversationId: wf.source_conversation_id,
});

/** Étape d'un modèle telle que reçue du serveur : seuls `id` et `uses` sont sûrs. */
type LooseStep = Partial<WorkflowStepV2> & Pick<WorkflowStepV2, "id" | "uses">;

const isPosition = (p: unknown): p is StepPosition =>
  !!p && typeof p === "object" && Number.isFinite((p as StepPosition).x) && Number.isFinite((p as StepPosition).y);

const isCondition = (when: unknown): when is Condition =>
  !!when && typeof when === "object" && typeof (when as Condition).left === "string" && typeof (when as Condition).op === "string";

/**
 * Étape d'un modèle → étape éditable : `needs` sans doublon ni elle-même, `on_error` limité à
 * stop / continue, `when` illisible retiré, entrée copiée (le modèle reste intact).
 */
function stepFromTemplate(step: LooseStep): WorkflowStepV2 {
  const needs = Array.isArray(step.needs) ? step.needs.filter((n): n is string => typeof n === "string" && n !== step.id) : [];
  const input = step.input && typeof step.input === "object" && !Array.isArray(step.input) ? structuredClone(step.input) : {};
  return {
    id: step.id,
    label: typeof step.label === "string" ? step.label : "",
    uses: step.uses,
    input,
    needs: [...new Set(needs)],
    when: isCondition(step.when) ? structuredClone(step.when) : null,
    on_error: step.on_error === "continue" ? "continue" : "stop",
    position: isPosition(step.position) ? { x: step.position.x, y: step.position.y } : null,
  };
}

/**
 * Modèle de la suite → nouveau brouillon, pas encore enregistré (id null). Positions du modèle
 * gardées si toutes les étapes en ont une ; sinon mise en page complète (aucun chevauchement
 * entre étapes placées et étapes à placer).
 */
export function draftFromTemplate(seed: TemplateSeed, agent: string | null = null): WorkflowDraftV2 {
  const steps = (seed.steps as LooseStep[]).map(stepFromTemplate);
  return {
    id: null,
    agent,
    title: seed.title.trim(),
    description: (seed.description ?? "").trim(),
    steps: steps.every((s) => s.position) ? steps : applyLayout(steps),
    params: seed.params.map((p) => ({ name: p.name, label: p.label ?? "", default: p.default ?? "" })),
    sourceConversationId: null,
  };
}

/** Corps envoyé à l'API (`version: 2`) : textes nettoyés, `when` vide retiré. */
export function toBody(draft: WorkflowDraftV2): WorkflowV2Body {
  return {
    version: 2,
    agent: draft.agent,
    title: draft.title.trim(),
    description: draft.description.trim(),
    params: draft.params.map((p) => ({ name: p.name.trim(), label: p.label.trim(), default: p.default })),
    steps: draft.steps.map((s) => ({
      id: s.id,
      label: s.label.trim(),
      uses: s.uses,
      input: s.input,
      needs: s.needs,
      when: s.when ?? null,
      on_error: s.on_error,
      position: s.position ? { x: Math.round(s.position.x), y: Math.round(s.position.y) } : null,
    })),
    ...(draft.id === null ? { source_conversation_id: draft.sourceConversationId } : {}),
  };
}

/** Paramètres cités dans les étapes mais pas encore déclarés. */
export const undeclaredParams = (draft: Pick<WorkflowDraftV2, "steps" | "params">): string[] =>
  referencedParams(draft.steps).filter((name) => !draft.params.some((p) => p.name === name));

/** Déclare (sans libellé ni défaut) les paramètres cités qui manquent. */
export const declareMissingParams = (draft: WorkflowDraftV2): WorkflowDraftV2 => ({
  ...draft,
  params: [...draft.params, ...undeclaredParams(draft).map((name) => ({ name, label: "", default: "" }))],
});

/** Signature stable du contenu (comparaison « modifié depuis l'enregistrement »). */
export const draftSignature = (draft: WorkflowDraftV2): string => JSON.stringify(toBody({ ...draft, id: "x" }));

/** État affiché par la puce de l'en-tête : brouillon jamais enregistré, modifié, ou à jour. */
export type SaveState = "draft" | "modified" | "saved";

export const saveState = (draft: Pick<WorkflowDraftV2, "id">, dirty: boolean): SaveState =>
  !draft.id ? "draft" : dirty ? "modified" : "saved";

export const SAVE_STATE_LABEL: Record<SaveState, string> = {
  draft: "Non enregistré",
  modified: "Modifié",
  saved: "Enregistré",
};

/** Erreurs locales + serveur, sans doublon (même étape, même champ, même code). */
export function mergeErrors(local: ValidationError[], server: ValidationError[]): ValidationError[] {
  const seen = new Set<string>();
  const out: ValidationError[] = [];
  for (const e of [...server, ...local]) {
    const key = `${e.step_id ?? ""}|${e.field ?? ""}|${e.code}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
}

/** Titre manquant : seul contrôle propre à l'enregistrement (la validation ne le demande pas). */
export const saveBlockers = (draft: WorkflowDraftV2): string[] =>
  draft.title.trim() ? [] : ["Donnez un titre au workflow."];
