/**
 * Brouillon édité d'un workflow v2 (titre, agent, paramètres, étapes) ↔ corps de l'API, et
 * fusion des erreurs locales et serveur. Logique pure, testée dans draft.test.ts.
 */

import type { ValidationError, WorkflowParam, WorkflowStepV2, WorkflowV2, WorkflowV2Body } from "@/types/api";

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
