import { describe, expect, it } from "vitest";

import type { AgentResult } from "@/types/api";

import { addUserTurn, applyEvent, emptyConversation, failLastTurn } from "./conversation";

const result = (over: Partial<AgentResult> = {}): AgentResult => ({
  agent: "assistant",
  provider: "anthropic",
  model: "claude",
  text: "Fini",
  stop_reason: "end_turn",
  iterations: 2,
  usage: { input_tokens: 10, output_tokens: 5 },
  artifacts: [],
  new_messages: [{ role: "assistant", content: [{ type: "text", text: "Fini" }] }],
  ...over,
});

describe("conversation", () => {
  it("ajoute le message utilisateur et un tour assistant vide", () => {
    const conv = addUserTurn(emptyConversation(), "Bonjour");
    expect(conv.turns.map((t) => t.role)).toEqual(["user", "assistant"]);
    expect(conv.history).toEqual([{ role: "user", content: [{ type: "text", text: "Bonjour" }] }]);
  });

  it("concatène les deltas de texte dans la même partie", () => {
    let conv = addUserTurn(emptyConversation(), "?");
    conv = applyEvent(conv, { type: "text_delta", text: "Bon" });
    conv = applyEvent(conv, { type: "text_delta", text: "jour" });
    expect(conv.turns[1]!.parts).toEqual([{ kind: "text", text: "Bonjour" }]);
  });

  it("suit un appel d'outil puis son résultat, et ouvre une nouvelle partie de texte après", () => {
    let conv = addUserTurn(emptyConversation(), "?");
    conv = applyEvent(conv, { type: "text_delta", text: "Je regarde." });
    conv = applyEvent(conv, { type: "tool_call", id: "c1", name: "data_via_query", input: { a: 1 } });
    conv = applyEvent(conv, {
      type: "tool_result",
      id: "c1",
      name: "data_via_query",
      content: "5 lignes",
      is_error: false,
    });
    conv = applyEvent(conv, { type: "text_delta", text: "Voilà." });
    const parts = conv.turns[1]!.parts;
    expect(parts.map((p) => p.kind)).toEqual(["text", "tool", "text"]);
    expect(parts[1]).toMatchObject({ status: "done", result: "5 lignes" });
  });

  it("référence l'artefact par l'identifiant du store", () => {
    let conv = addUserTurn(emptyConversation(), "?");
    conv = applyEvent(
      conv,
      {
        type: "artifact",
        artifact: { kind: "dax", title: "CA", content: "CA = 1", language: "dax", metadata: {} },
      },
      "art_1",
    );
    expect(conv.turns[1]!.parts).toEqual([{ kind: "artifact", artifactId: "art_1", title: "CA" }]);
  });

  it("à la fin du flux, ajoute les nouveaux messages à l'historique API", () => {
    let conv = addUserTurn(emptyConversation(), "?");
    conv = applyEvent(conv, { type: "done", result: result() });
    expect(conv.history.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(conv.turns[1]!.meta).toMatchObject({ provider: "anthropic", iterations: 2 });
  });

  it("en cas d'erreur, retire la question sans réponse de l'historique mais l'affiche", () => {
    let conv = addUserTurn(emptyConversation(), "?");
    conv = applyEvent(conv, { type: "tool_call", id: "c1", name: "x", input: {} });
    conv = applyEvent(conv, { type: "error", code: "provider_unavailable", message: "Panne", provider: "anthropic" });
    expect(conv.history).toEqual([]);
    expect(conv.turns).toHaveLength(2);
    expect(conv.turns[1]!.error).toBe("Panne");
    expect(conv.turns[1]!.parts[0]).toMatchObject({ status: "error" });
  });

  it("un échec après la fin du flux ne retire pas un historique complet", () => {
    let conv = addUserTurn(emptyConversation(), "?");
    conv = applyEvent(conv, { type: "done", result: result() });
    conv = failLastTurn(conv, "Réponse arrêtée.");
    expect(conv.history).toHaveLength(2);
  });
});
