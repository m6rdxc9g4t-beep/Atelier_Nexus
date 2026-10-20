import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentEvent, AgentRunRequest, ConversationDetail } from "@/types/api";

const calls: AgentRunRequest[] = [];
let script: AgentEvent[] = [];

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      createConversation: vi.fn(async (agent: string) => ({ id: "conv_1", agent }) as ConversationDetail),
      conversation: vi.fn(),
    },
    streamAgent: async function* (_agent: string, body: AgentRunRequest) {
      calls.push(body);
      for (const event of script) yield event;
    },
  };
});

const { useChatStore } = await import("./useChatStore");
const { api } = await import("@/lib/api");

const done: AgentEvent = {
  type: "done",
  result: {
    agent: "assistant",
    provider: "anthropic",
    model: "claude",
    text: "Bonjour",
    stop_reason: "end_turn",
    iterations: 1,
    usage: { input_tokens: 1, output_tokens: 1 },
    artifacts: [],
    new_messages: [{ role: "assistant", content: [{ type: "text", text: "Bonjour" }] }],
  },
};

describe("useChatStore et l'historique", () => {
  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal("window", { matchMedia: () => ({ matches: true }) });
    useChatStore.setState({ conversations: {}, conversationIds: {}, historyVersion: 0, saveError: null });
  });

  it("crée la conversation avant le premier envoi puis réutilise son identifiant", async () => {
    script = [{ type: "text_delta", text: "Bonjour" }, done, { type: "saved", conversation_id: "conv_1" }];
    await useChatStore.getState().send("Salut");
    await useChatStore.getState().send("Encore");

    expect(api.createConversation).toHaveBeenCalledTimes(1);
    expect(calls.map((c) => c.conversation_id)).toEqual(["conv_1", "conv_1"]);
    const state = useChatStore.getState();
    expect(state.conversationIds.assistant).toBe("conv_1");
    expect(state.historyVersion).toBe(2);
    expect(state.conversations.assistant?.history).toHaveLength(4);
  });

  it("sans base, l'agent répond quand même et l'utilisateur est prévenu", async () => {
    vi.mocked(api.createConversation).mockRejectedValueOnce(new Error("down"));
    script = [done, { type: "save_error", message: "Base indisponible" }];
    await useChatStore.getState().send("Salut");

    const state = useChatStore.getState();
    expect(calls[0]?.conversation_id).toBeNull();
    expect(state.conversations.assistant?.turns[1]?.meta?.provider).toBe("anthropic");
    expect(state.saveError).toContain("Base indisponible");
  });

  it("une nouvelle conversation oublie l'identifiant de la précédente", async () => {
    script = [done];
    await useChatStore.getState().send("Salut");
    useChatStore.getState().reset();
    expect(useChatStore.getState().conversationIds.assistant).toBeNull();
    expect(useChatStore.getState().conversations.assistant?.turns).toEqual([]);
  });
});
