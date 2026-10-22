/** Conversation active, agent et moteur choisis, envoi en streaming, historique enregistré. */

import { create } from "zustand";

import {
  type Conversation,
  addUserTurn,
  applyEvent,
  emptyConversation,
  failLastTurn,
  fromStored,
  type ReviewDecision,
  submitApprovals,
  submitReview,
} from "@/features/chat-agent/conversation";
import { ApiError, api, streamAgent } from "@/lib/api";
import { lastConversation, rememberConversation } from "@/lib/lastConversation";
import { saveStepMode } from "@/lib/stepMode";
import { type StoredArtifact, useArtifactStore } from "@/stores/useArtifactStore";
import type { AttachmentBlock, ConversationDetail, ProviderName } from "@/types/api";

const SAVE_OFF = "Historique indisponible : cette conversation ne sera pas enregistrée.";

interface ChatState {
  agent: string;
  /** null = moteur par défaut du serveur */
  provider: ProviderName | null;
  /** Une conversation par agent : changer d'agent ne perd rien. */
  conversations: Record<string, Conversation>;
  /** Conversation enregistrée affichée pour chaque agent (null = nouvelle, pas encore créée). */
  conversationIds: Record<string, string | null>;
  /** Incrémenté à chaque enregistrement : la liste de l'historique se recharge. */
  historyVersion: number;
  /** Dernier problème d'enregistrement (la conversation continue quand même). */
  saveError: string | null;
  /** Ouverture d'une conversation enregistrée en cours. */
  opening: boolean;
  streaming: boolean;
  controller: AbortController | null;

  setAgent: (agent: string) => void;
  setProvider: (provider: ProviderName | null) => void;
  /** `localOnly` : agent verrouillé sur le modèle local, le choix de moteur est ignoré. */
  /** `attachments` : fichiers déjà importés (POST /api/attachments), joints au message. */
  send: (text: string, options?: { localOnly?: boolean; attachments?: AttachmentBlock[] }) => Promise<void>;
  /** Reprend le tour après « Autoriser / Refuser ». */
  decide: (decisions: Record<string, boolean>, options?: { localOnly?: boolean }) => Promise<void>;
  /** Mode pas à pas : l'agent s'arrête après chaque résultat d'outil (activé par défaut). */
  stepMode: boolean;
  setStepMode: (on: boolean) => void;
  /** Réponse à une pause de revue : continuer, corriger (consigne) ou arrêter. */
  review: (decision: ReviewDecision, options?: { localOnly?: boolean }) => Promise<void>;
  stop: () => void;
  /** Repart d'une conversation vide (l'ancienne reste dans l'historique). */
  reset: () => void;
  /** Rouvre une conversation enregistrée (et passe sur son agent). */
  open: (id: string) => Promise<void>;
  /** Au premier passage sur un agent : rouvre sa dernière conversation, si elle existe encore. */
  restore: (agent: string) => Promise<void>;
  rename: (id: string, title: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
}

/** Artefacts enregistrés → store (identifiant serveur conservé), plus récents en tête. */
function storedArtifacts(detail: ConversationDetail): StoredArtifact[] {
  return [...detail.artifacts]
    .sort((a, b) => b.position - a.position)
    .map(({ id, agent, kind, title, content, language, metadata, created_at }) => ({
      id,
      agent,
      kind,
      title,
      content,
      language,
      metadata,
      createdAt: Date.parse(created_at),
    }));
}

export const useChatStore = create<ChatState>((set, get) => {
  const mutate = (agent: string, fn: (c: Conversation) => Conversation) =>
    set((s) => ({
      conversations: {
        ...s.conversations,
        [agent]: fn(s.conversations[agent] ?? emptyConversation()),
      },
    }));
  const setId = (agent: string, id: string | null) => {
    rememberConversation(agent, id);
    set((s) => ({ conversationIds: { ...s.conversationIds, [agent]: id } }));
  };
  const restored = new Set<string>();

  /** Affiche une conversation enregistrée pour son agent. */
  const show = (detail: ConversationDetail) => {
    const artifacts = storedArtifacts(detail);
    useArtifactStore.getState().replaceForAgent(detail.agent, artifacts);
    const ids = Object.fromEntries(artifacts.map((a) => [a.id, a.id]));
    mutate(detail.agent, () => fromStored(detail, ids));
    setId(detail.agent, detail.id);
  };

  /** Crée la conversation en base avant le premier envoi ; sans base, on continue sans historique. */
  const ensureConversation = async (agent: string): Promise<string | null> => {
    const current = get().conversationIds[agent];
    if (current) return current;
    try {
      const created = await api.createConversation(agent);
      setId(agent, created.id);
      return created.id;
    } catch {
      set({ saveError: SAVE_OFF });
      return null;
    }
  };

  return {
    agent: "assistant",
    provider: null,
    conversations: {},
    conversationIds: {},
    historyVersion: 0,
    saveError: null,
    opening: false,
    streaming: false,
    controller: null,

    setAgent: (agent) => {
      if (get().streaming) return;
      set({ agent, saveError: null });
    },

    setProvider: (provider) => set({ provider }),

    send: async (text, options) => {
      const trimmed = text.trim();
      const attachments = options?.attachments ?? [];
      const { agent, streaming } = get();
      if ((!trimmed && !attachments.length) || streaming) return;
      restored.add(agent); // une conversation commencée ne doit pas être remplacée par la restauration
      mutate(agent, (c) => addUserTurn(c, trimmed, attachments));
      await run(agent, null, options?.localOnly ?? false);
    },

    stepMode: true, // lu dans le navigateur au montage (ChatPanel), pas au rendu serveur
    setStepMode: (on) => {
      saveStepMode(on);
      set({ stepMode: on });
    },

    review: async (decision, options) => {
      const { agent, streaming } = get();
      if (streaming) return;
      const conv = get().conversations[agent];
      const submitted = conv ? submitReview(conv, decision) : null;
      if (!submitted) return;
      mutate(agent, () => submitted.conv);
      await run(agent, null, options?.localOnly ?? false, submitted.review);
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
      const { agent, streaming } = get();
      if (streaming) return;
      mutate(agent, () => emptyConversation());
      setId(agent, null);
      useArtifactStore.getState().replaceForAgent(agent, []);
      set({ saveError: null });
    },

    open: async (id) => {
      if (get().streaming || get().opening) return;
      set({ opening: true });
      try {
        const detail = await api.conversation(id);
        restored.add(detail.agent);
        show(detail);
        set({ agent: detail.agent, saveError: null });
      } catch (err) {
        set({ saveError: err instanceof ApiError ? err.message : "Impossible d'ouvrir la conversation." });
      } finally {
        set({ opening: false });
      }
    },

    restore: async (agent) => {
      if (restored.has(agent)) return;
      restored.add(agent);
      const id = lastConversation(agent);
      const { conversations, conversationIds } = get();
      if (!id || conversationIds[agent] || conversations[agent]?.turns.length) return;
      try {
        const detail = await api.conversation(id);
        // L'utilisateur a pu commencer à écrire entre-temps : ne rien écraser
        if (detail.agent !== agent || get().conversations[agent]?.turns.length) return;
        show(detail);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) rememberConversation(agent, null);
      }
    },

    rename: async (id, title) => {
      const trimmed = title.trim();
      if (!trimmed) return;
      try {
        await api.renameConversation(id, trimmed.slice(0, 120));
      } catch (err) {
        set({ saveError: err instanceof ApiError ? err.message : "Renommage impossible." });
      }
      set((s) => ({ historyVersion: s.historyVersion + 1 }));
    },

    remove: async (id) => {
      try {
        await api.deleteConversation(id);
      } catch (err) {
        set({ saveError: err instanceof ApiError ? err.message : "Suppression impossible." });
        return;
      }
      const { agent, conversationIds, streaming } = get();
      if (conversationIds[agent] === id && !streaming) get().reset();
      set((s) => ({ historyVersion: s.historyVersion + 1 }));
    },
  };

  /** Envoie l'historique (et les validations éventuelles), applique le flux au dernier tour. */
  async function run(
    agent: string,
    approvals: Record<string, boolean> | null,
    localOnly: boolean,
    review: "continue" | "stop" | null = null,
  ) {
    const controller = new AbortController();
    set({ streaming: true, controller });
    const provider = localOnly ? null : get().provider;
    try {
      const conversationId = await ensureConversation(agent);
      const history = get().conversations[agent]?.history ?? [];
      for await (const event of streamAgent(
        agent,
        {
          messages: history,
          provider,
          approvals,
          conversation_id: conversationId,
          review_results: get().stepMode,
          review,
        },
        controller.signal,
      )) {
        let artifactId: string | undefined;
        if (event.type === "artifact") {
          // Grand écran (xl) : le panneau s'ouvre à côté du chat ; sinon, bouton « Artefacts »
          const wide = window.matchMedia("(min-width: 1280px)").matches;
          artifactId = useArtifactStore.getState().add(event.artifact, agent, wide).id;
        } else if (event.type === "saved") {
          set((s) => ({ historyVersion: s.historyVersion + 1, saveError: null }));
        } else if (event.type === "save_error") {
          set({ saveError: `Conversation non enregistrée : ${event.message}` });
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
