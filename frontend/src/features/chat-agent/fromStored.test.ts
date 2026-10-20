import { describe, expect, it } from "vitest";

import type { ConversationDetail, Message } from "@/types/api";

import { fromStored, pendingApproval } from "./conversation";
import { formatWhen } from "./formatWhen";

const user = (text: string): Message => ({ role: "user", content: [{ type: "text", text }] });

const detail = (over: Partial<ConversationDetail>): ConversationDetail => ({
  id: "c1",
  agent: "assistant",
  title: "Test",
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  message_count: 0,
  artifact_count: 0,
  history: [],
  artifacts: [],
  turn_meta: {},
  pending_approvals: [],
  ...over,
});

const meta = {
  provider: "anthropic" as const,
  model: "claude",
  usage: { input_tokens: 3, output_tokens: 2 },
  stop_reason: "end_turn" as const,
  iterations: 2,
};

describe("fromStored", () => {
  it("reconstruit les tours, les outils, la méta et les artefacts", () => {
    const history: Message[] = [
      user("Fais un plan"),
      {
        role: "assistant",
        content: [
          { type: "text", text: "Je publie." },
          { type: "tool_use", id: "p1", name: "publish_artifact", input: { title: "Plan" } },
        ],
      },
      {
        role: "user",
        content: [
          { type: "tool_result", tool_use_id: "p1", tool_name: "publish_artifact", content: "ok", is_error: false },
        ],
      },
      { role: "assistant", content: [{ type: "text", text: "Voilà." }] },
      user("Merci"),
      { role: "assistant", content: [{ type: "text", text: "Avec plaisir." }] },
    ];
    const conv = fromStored(
      detail({
        history,
        turn_meta: { "3": meta, "5": { ...meta, provider: "ollama" } },
        artifacts: [
          {
            id: "a1",
            agent: "assistant",
            kind: "markdown",
            title: "Plan",
            content: "# Plan",
            language: null,
            metadata: {},
            position: 4,
            created_at: "2026-10-20T10:00:00Z",
          },
        ],
      }),
      { a1: "local-a1" },
    );

    expect(conv.history).toBe(history);
    expect(conv.turns.map((t) => t.role)).toEqual(["user", "assistant", "user", "assistant"]);
    const first = conv.turns[1]!;
    expect(first.parts).toEqual([
      { kind: "text", text: "Je publie." },
      { kind: "tool", id: "p1", name: "publish_artifact", input: { title: "Plan" }, status: "done", result: "ok" },
      { kind: "text", text: "Voilà." },
      { kind: "artifact", artifactId: "local-a1", title: "Plan" },
    ]);
    expect(first.meta?.provider).toBe("anthropic");
    expect(conv.turns[3]!.meta?.provider).toBe("ollama");
    expect(conv.turns[3]!.parts).toEqual([{ kind: "text", text: "Avec plaisir." }]);
  });

  it("restaure une validation en attente sans afficher les appels non exécutés", () => {
    const call = { id: "w1", name: "projets_create_item", input: { name: "x" }, summary: "Créer x" };
    const conv = fromStored(
      detail({
        history: [
          user("Crée x"),
          {
            role: "assistant",
            content: [
              { type: "tool_use", id: "w1", name: "projets_create_item", input: { name: "x" } },
              { type: "tool_use", id: "r1", name: "projets_list", input: {} },
            ],
          },
        ],
        pending_approvals: [call],
      }),
      {},
    );
    expect(conv.turns[1]!.parts).toEqual([
      { kind: "approval", calls: [call], decisions: {}, submitted: false },
    ]);
    expect(pendingApproval(conv)?.calls[0]?.id).toBe("w1");
  });

  it("marque en erreur un appel resté sans résultat (tour interrompu)", () => {
    const conv = fromStored(
      detail({
        history: [
          user("?"),
          { role: "assistant", content: [{ type: "tool_use", id: "t1", name: "current_datetime", input: {} }] },
        ],
      }),
      {},
    );
    expect(conv.turns[1]!.parts[0]).toMatchObject({ kind: "tool", status: "error" });
  });
});

describe("formatWhen", () => {
  const now = new Date(2026, 9, 20, 15, 0);
  it("dit aujourd'hui, hier, puis la date", () => {
    expect(formatWhen(new Date(2026, 9, 20, 9, 5).toISOString(), now)).toMatch(/^Aujourd'hui, 09:05$/);
    expect(formatWhen(new Date(2026, 9, 19, 22, 0).toISOString(), now)).toMatch(/^Hier, 22:00$/);
    expect(formatWhen(new Date(2026, 9, 2).toISOString(), now)).toMatch(/^2 oct\.?$/);
    expect(formatWhen(new Date(2025, 0, 3).toISOString(), now)).toMatch(/2025/);
    expect(formatWhen("n'importe quoi", now)).toBe("");
  });
});
