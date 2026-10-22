import { describe, expect, it } from "vitest";

import type { ChatTurn } from "@/features/chat-agent/conversation";
import type { ChainInfo, ChainRun } from "@/types/api";

import { advanceLabel, progressLabel, stageOfConversation, stageReadiness } from "./chain";

const meta = (stop_reason: NonNullable<ChatTurn["meta"]>["stop_reason"]) => ({
  provider: "anthropic" as const,
  model: "m",
  usage: { input_tokens: 1, output_tokens: 1 },
  stop_reason,
  iterations: 1,
});
const answer = (over: Partial<ChatTurn> = {}): ChatTurn => ({
  id: "t",
  role: "assistant",
  parts: [{ kind: "text", text: "Livrable" }],
  meta: meta("end_turn"),
  ...over,
});
const user: ChatTurn = { id: "u", role: "user", parts: [{ kind: "text", text: "Relais" }] };

const run: ChainRun = {
  id: "r",
  chain: "chaine_data",
  request: "CA",
  status: "running",
  stage_index: 1,
  stages: [
    { agent: "ingenieur_donnees", role: "Préparation des données", status: "validated", conversation_id: "c1", deliverable: null, validated_at: null },
    { agent: "modelisateur_bi", role: "Modèle en étoile", status: "active", conversation_id: "c2", deliverable: null, validated_at: null },
    { agent: "data_analyst", role: "Mesures DAX et analyse", status: "pending", conversation_id: null, deliverable: null, validated_at: null },
  ],
  created_at: "",
  updated_at: "",
};

describe("étape validable", () => {
  it("seulement une réponse terminée, sans rien en attente", () => {
    expect(stageReadiness([user, answer()], false)).toEqual({ ready: true });
    expect(stageReadiness([user, answer({ meta: meta("max_tokens") })], false).ready).toBe(true);
  });

  it("refuse en cours, sans réponse, en erreur, en attente ou arrêtée", () => {
    expect(stageReadiness([user, answer()], true).ready).toBe(false);
    expect(stageReadiness([user], false).ready).toBe(false);
    expect(stageReadiness([user, answer({ error: "x" })], false).ready).toBe(false);
    const waiting = answer({ meta: meta("awaiting_review"), parts: [{ kind: "review", callIds: ["c"] }] });
    expect(stageReadiness([user, waiting], false)).toEqual({
      ready: false,
      reason: "Une action ou un résultat attend votre validation.",
    });
    const approval = answer({
      meta: meta("awaiting_approval"),
      parts: [{ kind: "approval", calls: [], decisions: {}, submitted: false }],
    });
    expect(stageReadiness([user, approval], false).ready).toBe(false);
    expect(stageReadiness([user, answer({ meta: meta("stopped_by_user") })], false).ready).toBe(false);
    expect(stageReadiness([user, answer({ meta: undefined })], false).ready).toBe(false);
  });
});

describe("bandeau", () => {
  const chain = { stages: [{ role: "A" }, { role: "B" }, { role: "Mesures DAX" }] } as unknown as ChainInfo;

  it("libellés de progression et de validation", () => {
    expect(progressLabel(run)).toBe("Étape 2/3 — Modèle en étoile");
    expect(advanceLabel(run, chain)).toBe("Valider ce livrable → Mesures DAX");
    expect(advanceLabel({ ...run, stage_index: 2 }, chain)).toBe("Valider et terminer la chaîne");
  });

  it("retrouve l'étape d'une conversation", () => {
    expect(stageOfConversation(run, "c2")).toBe(1);
    expect(stageOfConversation(run, "autre")).toBeNull();
    expect(stageOfConversation(run, null)).toBeNull();
  });
});
