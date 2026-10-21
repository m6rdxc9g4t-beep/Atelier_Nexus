import { describe, expect, it } from "vitest";

import type { WorkflowV2 } from "@/types/api";

import {
  declareMissingParams,
  draftFromWorkflow,
  draftSignature,
  emptyDraft,
  mergeErrors,
  saveBlockers,
  toBody,
  undeclaredParams,
} from "./draft";
import { diamondSteps, step } from "./fixtures";

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
