/** Mode pas à pas : revue des résultats (flux en direct, décisions, réouverture). */

import { describe, expect, it } from "vitest";

import type { AgentResult, ConversationDetail, Message } from "@/types/api";

import {
  CORRECTION_PREFIX,
  addUserTurn,
  applyEvent,
  canSaveAsWorkflow,
  emptyConversation,
  fromStored,
  pendingReview,
  submitReview,
} from "./conversation";

const call: Message = {
  role: "assistant",
  content: [{ type: "tool_use", id: "c1", name: "data_via_query", input: { dataset_id: "ventes" } }],
};
const results: Message = {
  role: "user",
  content: [{ type: "tool_result", tool_use_id: "c1", tool_name: "data_via_query", content: "| Bretagne | 12 |", is_error: false }],
};

const paused = (over: Partial<AgentResult> = {}): AgentResult => ({
  agent: "data_analyst",
  provider: "anthropic",
  model: "claude",
  text: "",
  stop_reason: "awaiting_review",
  iterations: 1,
  usage: { input_tokens: 1, output_tokens: 1 },
  artifacts: [],
  new_messages: [call, results],
  ...over,
});

/** Tour en direct jusqu'à la pause de revue. */
function live() {
  let conv = addUserTurn(emptyConversation(), "CA par région ?");
  conv = applyEvent(conv, { type: "tool_call", id: "c1", name: "data_via_query", input: { dataset_id: "ventes" } });
  conv = applyEvent(conv, { type: "tool_result", id: "c1", name: "data_via_query", content: "| Bretagne | 12 |", is_error: false });
  conv = applyEvent(conv, { type: "review_required", call_ids: ["c1"] });
  return applyEvent(conv, { type: "done", result: paused() });
}

describe("revue des résultats", () => {
  it("la pause ajoute une carte de revue et bloque l'enregistrement en workflow", () => {
    const conv = live();
    expect(pendingReview(conv)?.callIds).toEqual(["c1"]);
    const turn = conv.turns.at(-1)!;
    expect(turn.meta?.stop_reason).toBe("awaiting_review");
    expect(canSaveAsWorkflow(turn)).toBe(false);
    expect(conv.history.at(-1)).toEqual(results);
  });

  it("continuer et arrêter laissent l'historique tel quel", () => {
    const conv = live();
    const go = submitReview(conv, { action: "continue" })!;
    expect(go.review).toBe("continue");
    expect(go.conv.history).toEqual(conv.history);
    expect(pendingReview(go.conv)).toBeNull();
    expect(submitReview(conv, { action: "stop" })!.review).toBe("stop");
  });

  it("corriger joint la consigne aux résultats, puis continue", () => {
    const fixed = submitReview(live(), { action: "correct", instruction: "  Seulement 2026  " })!;
    expect(fixed.review).toBe("continue");
    const last = fixed.conv.history.at(-1)!;
    expect(last.content).toEqual([...results.content, { type: "text", text: `${CORRECTION_PREFIX}Seulement 2026` }]);
    expect(submitReview(live(), { action: "correct", instruction: "   " })).toBeNull();
  });

  it("sans pause en attente, rien à soumettre", () => {
    expect(submitReview(addUserTurn(emptyConversation(), "x"), { action: "continue" })).toBeNull();
  });
});

describe("réouverture d'une conversation en pas à pas", () => {
  const detail = (history: Message[], meta: Record<string, AgentResult["stop_reason"]>): ConversationDetail => ({
    id: "conv",
    agent: "data_analyst",
    title: "CA",
    created_at: "2026-10-22T10:00:00Z",
    updated_at: "2026-10-22T10:00:00Z",
    message_count: history.length,
    artifact_count: 0,
    history,
    artifacts: [],
    turn_meta: Object.fromEntries(
      Object.entries(meta).map(([k, stop_reason]) => [
        k,
        { provider: "anthropic", model: "claude", usage: { input_tokens: 1, output_tokens: 1 }, stop_reason, iterations: 1 },
      ]),
    ),
    pending_approvals: [],
  });
  const question: Message = { role: "user", content: [{ type: "text", text: "CA par région ?" }] };

  it("une conversation arrêtée sur des résultats rouvre la carte de revue, avec sa méta", () => {
    const conv = fromStored(detail([question, call, results], { "2": "awaiting_review" }), {});
    expect(pendingReview(conv)?.callIds).toEqual(["c1"]);
    expect(conv.turns.at(-1)?.meta?.stop_reason).toBe("awaiting_review");
    const tool = conv.turns.at(-1)?.parts.find((p) => p.kind === "tool");
    expect(tool && tool.kind === "tool" && tool.status).toBe("done");
  });

  it("une correction passée s'affiche comme décision, sans carte en attente", () => {
    const corrected: Message = {
      role: "user",
      content: [...results.content, { type: "text", text: `${CORRECTION_PREFIX}Seulement 2026` }],
    };
    const answer: Message = { role: "assistant", content: [{ type: "text", text: "En 2026 : 12." }] };
    const conv = fromStored(detail([question, call, corrected, answer], { "3": "end_turn" }), {});
    expect(pendingReview(conv)).toBeNull();
    const review = conv.turns.at(-1)?.parts.find((p) => p.kind === "review");
    expect(review && review.kind === "review" && review.decision).toEqual({ action: "correct", instruction: "Seulement 2026" });
    // La question d'origine reste le seul message utilisateur affiché
    expect(conv.turns.filter((t) => t.role === "user")).toHaveLength(1);
  });
});

describe("réouverture : pas de fausse pause", () => {
  it("un tour coupé par la limite d'étapes, terminé par des résultats, n'affiche pas de revue", () => {
    const question: Message = { role: "user", content: [{ type: "text", text: "Q" }] };
    const detail: ConversationDetail = {
      id: "c", agent: "a", title: "", created_at: "", updated_at: "", message_count: 3, artifact_count: 0,
      history: [question, call, results],
      artifacts: [],
      turn_meta: { "2": { provider: "anthropic", model: "m", usage: { input_tokens: 1, output_tokens: 1 }, stop_reason: "max_iterations", iterations: 8 } },
      pending_approvals: [],
    };
    expect(pendingReview(fromStored(detail, {}))).toBeNull();
  });
});
