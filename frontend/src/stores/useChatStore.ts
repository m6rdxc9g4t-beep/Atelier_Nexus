/** Conversation active, agent et moteur choisis, envoi en streaming. */

import { create } from "zustand";

import {
  type Conversation,
  addUserTurn,
  applyEvent,
  emptyConversation,
  failLastTurn,
  submitApprovals,
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
  /** `localOnly` : agent verrouillé sur le modèle local, le choix de moteur est ignoré. */
  send: (text: string, options?: { localOnly?: boolean }) => Promise<void>;
  /** Reprend le tour après « Autoriser / Refuser ». */
  decide: (decisions: Record<string, boolean>, options?: { localOnly?: boolean }) => Promise<void>;
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

    send: async (text, options) => {
      const trimmed = text.trim();
      const { agent, streaming } = get();
      if (!trimmed || streaming) return;
      mutate(agent, (c) => addUserTurn(c, trimmed));
      await run(agent, null, options?.localOnly ?? false);
    },

    decide: async (decisions, options) => {
      const { agent, streaming } = get();
      if (streaming) return;
      const conv = get().conversations[agent];
      const submitted = conv ? submitApprovals(conv, decisions) : null;
      if (!submitted) return;
      mutate(agent, () => submitted.conv);
      await run(agent, submitted.approvals, options?.localOnly ?? false);
    },

    stop: () => get().controller?.abort(),

    reset: () => {
      if (get().streaming) return;
      mutate(get().agent, () => emptyConversation());
    },
  };

  /** Envoie l'historique (et les validations éventuelles), applique le flux au dernier tour. */
  async function run(agent: string, approvals: Record<string, boolean> | null, localOnly: boolean) {
      const controller = new AbortController();
      set({ streaming: true, controller });
      const provider = localOnly ? null : get().provider;
      const history = get().conversations[agent]?.history ?? [];
      try {
        for await (const event of streamAgent(
          agent,
          { messages: history, provider, approvals },
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
  }
});
