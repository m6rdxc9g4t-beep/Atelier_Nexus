/** Conversation active, agent et moteur choisis, envoi en streaming. */

import { create } from "zustand";

import {
  type Conversation,
  addUserTurn,
  applyEvent,
  emptyConversation,
  failLastTurn,
} from "@/features/chat-agent/conversation";
import { ApiError, streamAgent } from "@/lib/api";
import { useArtifactStore } from "@/stores/useArtifactStore";
import type { ProviderName } from "@/types/api";

interface ChatState {
  agent: string;
  /** null = moteur par défaut du serveur */
  provider: ProviderName | null;
  /** Une conversation par agent : changer d'agent ne perd rien. */
  conversations: Record<string, Conversation>;
  streaming: boolean;
  controller: AbortController | null;

  setAgent: (agent: string) => void;
  setProvider: (provider: ProviderName | null) => void;
  send: (text: string) => Promise<void>;
  stop: () => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set, get) => {
  const mutate = (agent: string, fn: (c: Conversation) => Conversation) =>
    set((s) => ({
      conversations: {
        ...s.conversations,
        [agent]: fn(s.conversations[agent] ?? emptyConversation()),
      },
    }));

  return {
    agent: "assistant",
    provider: null,
    conversations: {},
    streaming: false,
    controller: null,

    setAgent: (agent) => {
      if (get().streaming) return;
      set({ agent });
    },

    setProvider: (provider) => set({ provider }),

    send: async (text) => {
      const trimmed = text.trim();
      const { agent, provider, streaming } = get();
      if (!trimmed || streaming) return;

      const controller = new AbortController();
      mutate(agent, (c) => addUserTurn(c, trimmed));
      set({ streaming: true, controller });

      const history = get().conversations[agent]?.history ?? [];
      try {
        for await (const event of streamAgent(
          agent,
          { messages: history, provider },
          controller.signal,
        )) {
          let artifactId: string | undefined;
          if (event.type === "artifact") {
            // Grand écran (xl) : le panneau s'ouvre à côté du chat ; sinon, bouton « Artefacts »
            const wide = window.matchMedia("(min-width: 1280px)").matches;
            artifactId = useArtifactStore.getState().add(event.artifact, agent, wide).id;
          }
          mutate(agent, (c) => applyEvent(c, event, artifactId));
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          const message = err instanceof ApiError ? err.message : "La réponse a été interrompue.";
          mutate(agent, (c) => failLastTurn(c, message));
        }
      } finally {
        if (controller.signal.aborted) mutate(agent, (c) => failLastTurn(c, "Réponse arrêtée."));
        set({ streaming: false, controller: null });
      }
    },

    stop: () => get().controller?.abort(),

    reset: () => {
      if (get().streaming) return;
      mutate(get().agent, () => emptyConversation());
    },
  };
});
