import { describe, expect, it } from "vitest";

import type { TemplateSeed } from "@/stores/useWorkflowStudioStore";
import type { WorkflowStepV2, WorkflowV2 } from "@/types/api";

import {
  SAVE_STATE_LABEL,
  declareMissingParams,
  draftFromTemplate,
  draftFromWorkflow,
  draftSignature,
  emptyDraft,
  mergeErrors,
  saveBlockers,
  saveState,
  toBody,
  undeclaredParams,
} from "./draft";
import { diamondSteps, step } from "./fixtures";
import { LAYOUT } from "./graph";

const workflow: WorkflowV2 = {
  id: "wf_1",
  version: 2,
  agent: null,
  title: "CA → tâches",
  description: "",
  steps: diamondSteps,
  params: [{ name: "jeu", label: "Jeu", default: "ventes" }],
  source_conversation_id: null,
  run_count: 0,
  last_run_at: null,
  last_status: null,
  created_at: "",
  updated_at: "",
};

describe("brouillon ↔ API", () => {
  it("place les étapes sans position à l'ouverture", () => {
    const draft = draftFromWorkflow(workflow);
    expect(draft.steps.every((s) => s.position)).toBe(true);
    expect(draft.id).toBe("wf_1");
  });

  it("prépare un corps version 2 nettoyé", () => {
    const draft = { ...draftFromWorkflow(workflow), title: "  Titre ", steps: [{ ...diamondSteps[0]!, label: " Lire ", position: { x: 1.6, y: 2.2 } }] };
    const body = toBody(draft);
    expect(body).toMatchObject({ version: 2, agent: null, title: "Titre" });
    expect(body.steps[0]).toMatchObject({ label: "Lire", position: { x: 2, y: 2 }, when: null, on_error: "stop" });
    expect("source_conversation_id" in body).toBe(false);
    expect(toBody(emptyDraft("data_analyst"))).toMatchObject({ agent: "data_analyst", source_conversation_id: null });
  });

  it("déclare les paramètres cités qui manquent", () => {
    const draft = { ...emptyDraft(), steps: [step("a", "x", [], { v: "{{params.jeu}} {{mois}}" })] };
    expect(undeclaredParams(draft)).toEqual(["jeu", "mois"]);
    expect(declareMissingParams(draft).params).toEqual([
      { name: "jeu", label: "", default: "" },
      { name: "mois", label: "", default: "" },
    ]);
  });

  it("compare le contenu et exige un titre", () => {
    const draft = draftFromWorkflow(workflow);
    expect(draftSignature(draft)).toBe(draftSignature({ ...draft }));
    expect(draftSignature(draft)).not.toBe(draftSignature({ ...draft, title: "autre" }));
    expect(saveBlockers({ ...draft, title: " " })).toHaveLength(1);
    expect(saveBlockers(draft)).toEqual([]);
  });

  it("fusionne erreurs locales et serveur sans doublon", () => {
    const local = [{ step_id: "a", field: null, code: "CYCLE", message: "local" }];
    const server = [
      { step_id: "a", field: null, code: "CYCLE", message: "serveur" },
      { step_id: "a", field: "x", code: "INPUT_INVALID", message: "" },
    ];
    const merged = mergeErrors(local, server);
    expect(merged.map((e) => e.message)).toEqual(["serveur", ""]);
  });
});

describe("brouillon copié d'un modèle de la suite", () => {
  const seed = (steps: WorkflowStepV2[], extra: Partial<TemplateSeed> = {}): TemplateSeed => ({
    slug: "conversions-tab",
    title: " Conversions → Tab ",
    description: "Copie les conversions du jour dans Tab. ",
    params: [{ name: "table", label: "Table", default: "conversions" }],
    steps,
    ...extra,
  });

  it("prérempli mais jamais enregistré : titre, description, paramètres, étapes", () => {
    const draft = draftFromTemplate(seed(diamondSteps));
    expect(draft).toMatchObject({
      id: null,
      agent: null,
      title: "Conversions → Tab",
      description: "Copie les conversions du jour dans Tab.",
      sourceConversationId: null,
    });
    expect(draft.params).toEqual([{ name: "table", label: "Table", default: "conversions" }]);
    expect(draft.steps.map((s) => s.id)).toEqual(["lire", "taches", "creer", "ajouter"]);
    expect(saveState(draft, true)).toBe("draft");
    expect(toBody(draft)).toMatchObject({ version: 2, source_conversation_id: null });
  });

  it("garde les positions du modèle quand toutes les étapes en ont une", () => {
    const placed = diamondSteps.map((s, i) => ({ ...s, position: { x: i * 10, y: 5 } }));
    const draft = draftFromTemplate(seed(placed));
    expect(draft.steps.map((s) => s.position)).toEqual(placed.map((s) => s.position));
  });

  it("recalcule toute la mise en page s'il manque une position", () => {
    const partial = diamondSteps.map((s, i) => (i === 0 ? { ...s, position: { x: 999, y: 999 } } : s));
    const draft = draftFromTemplate(seed(partial));
    const byId = Object.fromEntries(draft.steps.map((s) => [s.id, s.position]));
    expect(byId.lire).toEqual({ x: 0, y: expect.any(Number) });
    expect(byId.creer!.x).toBe(LAYOUT.columnWidth);
    expect(draft.steps.every((s) => s.position)).toBe(true);
  });

  it("normalise on_error, needs et when reçus du serveur", () => {
    const loose = [
      { id: "a", uses: "tool:x" },
      { id: "b", uses: "tool:y", needs: ["a", "a", "b"], on_error: "ignore", when: "si…", label: 3, input: [1] },
      { id: "c", uses: "tool:z", needs: ["b"], on_error: "continue", when: { left: "{{steps.b.data}}", op: "not_empty" } },
    ] as unknown as WorkflowStepV2[];
    const [a, b, c] = draftFromTemplate(seed(loose)).steps;
    expect(a).toMatchObject({ needs: [], on_error: "stop", when: null, label: "", input: {} });
    expect(b).toMatchObject({ needs: ["a"], on_error: "stop", when: null, label: "", input: {} });
    expect(c).toMatchObject({ needs: ["b"], on_error: "continue", when: { left: "{{steps.b.data}}", op: "not_empty" } });
  });

  it("copie les entrées : modifier le brouillon ne touche pas le modèle", () => {
    const original = seed([step("lire", "tool:data_via_query", [], { filtre: { mois: "{{params.mois}}" } })], {
      params: [{ name: "mois" } as TemplateSeed["params"][number]],
    });
    const draft = draftFromTemplate(original, "data_analyst");
    (draft.steps[0]!.input.filtre as Record<string, string>).mois = "juin";
    expect(original.steps[0]!.input).toEqual({ filtre: { mois: "{{params.mois}}" } });
    expect(draft.agent).toBe("data_analyst");
    expect(draft.params).toEqual([{ name: "mois", label: "", default: "" }]);
  });
});

describe("état d'enregistrement", () => {
  it("brouillon, modifié ou enregistré", () => {
    expect(saveState({ id: null }, false)).toBe("draft");
    expect(saveState({ id: "wf_1" }, true)).toBe("modified");
    expect(saveState({ id: "wf_1" }, false)).toBe("saved");
    expect(SAVE_STATE_LABEL.saved).toBe("Enregistré");
  });
});
