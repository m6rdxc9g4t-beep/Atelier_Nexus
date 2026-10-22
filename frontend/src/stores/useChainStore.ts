/**
 * Chaîne d'agents active : exécution suivie, passage d'une étape à l'autre. Chaque étape se joue
 * dans une conversation ordinaire (useChatStore) ; ce store ouvre la bonne conversation et y
 * envoie le message de passage de relais. L'exécution active est retenue dans le navigateur.
 */

import { create } from "zustand";

import { ApiError, api } from "@/lib/api";
import { setChainConversations } from "@/lib/chainConversations";
import { useArtifactStore } from "@/stores/useArtifactStore";
import { useChatStore } from "@/stores/useChatStore";
import type { Artifact, ChainRun, ChainStep } from "@/types/api";

const KEY = "nexus.activeChainRun";

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(KEY, id);
    else localStorage.removeItem(KEY);
  } catch {
    // sans stockage, la chaîne reste suivie pendant la session
  }
}

function remembered(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

interface ChainState {
  /** Fenêtre de lancement : ouverte, et chaîne présélectionnée (null = choisir). */
  launcher: { open: boolean; chain: string | null };
  openLauncher: (chain?: string | null) => void;
  closeLauncher: () => void;
  run: ChainRun | null;
  busy: boolean;
  error: string | null;
  /** Rouvre l'exécution retenue (au chargement de l'interface). */
  restore: () => Promise<void>;
  start: (chain: string, request: string) => Promise<boolean>;
  /** Valide le livrable de l'étape courante et lance la suivante (ou termine). */
  advance: () => Promise<void>;
  stop: () => Promise<void>;
  /** Suit une exécution existante et ouvre la conversation d'une étape (courante par défaut). */
  follow: (run: ChainRun, stage?: number) => Promise<void>;
  /** Ouvre la conversation d'une étape de l'exécution suivie. */
  openStage: (index: number) => Promise<void>;
  showRecap: () => Promise<void>;
  /** Ne plus suivre de chaîne (l'exécution reste dans la liste). */
  close: () => void;
}

const message = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

function addRecap(recap: Artifact, agent: string) {
  const wide = typeof window !== "undefined" && window.matchMedia("(min-width: 1280px)").matches;
  useArtifactStore.getState().add(recap, agent, wide);
  if (!wide) useArtifactStore.getState().setPanelOpen(true);
}

/** Suit l'exécution et tient à jour les conversations où le pas à pas est imposé. */
function track(run: ChainRun | null) {
  setChainConversations(
    run && run.status === "running"
      ? run.stages.flatMap((s) => (s.conversation_id && s.status === "active" ? [s.conversation_id] : []))
      : [],
  );
}

export const useChainStore = create<ChainState>((set, get) => {
  const setRun = (run: ChainRun | null) => {
    track(run);
    set({ run });
  };

  /**
   * Ouvre la conversation de l'étape et y envoie le relais. L'envoi n'est pas attendu : la
   * fenêtre se ferme et le bandeau reste utilisable pendant que l'agent travaille. Si
   * l'ouverture échoue, rien n'est envoyé ailleurs ; « Reprendre » renverra le relais.
   */
  const play = async (step: ChainStep) => {
    setRun(step.run);
    remember(step.run.id);
    if (step.recap) addRecap(step.recap, step.run.stages.at(-1)?.agent ?? "assistant");
    if (!step.conversation_id || !step.handoff) return;
    const opened = await useChatStore.getState().open(step.conversation_id);
    const chat = useChatStore.getState();
    if (!opened || chat.conversationIds[chat.agent] !== step.conversation_id) {
      set({ error: "La conversation de l'étape n'a pas pu s'ouvrir : utilisez « Reprendre »." });
      return;
    }
    void chat.send(step.handoff, { localOnly: step.local_only });
  };

  return {
    launcher: { open: false, chain: null },
    openLauncher: (chain = null) => set({ launcher: { open: true, chain }, error: null }),
    closeLauncher: () => set((s) => ({ launcher: { ...s.launcher, open: false } })),
    run: null,
    busy: false,
    error: null,

    restore: async () => {
      const id = remembered();
      if (!id || get().run) return;
      try {
        setRun(await api.chainRun(id));
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) remember(null);
      }
    },

    start: async (chain, request) => {
      if (get().busy || useChatStore.getState().streaming) return false;
      set({ busy: true, error: null });
      try {
        await play(await api.startChain(chain, request));
        return true;
      } catch (err) {
        set({ error: message(err, "Lancement impossible.") });
        return false;
      } finally {
        set({ busy: false });
      }
    },

    advance: async () => {
      const run = get().run;
      if (!run || get().busy || useChatStore.getState().streaming) return;
      set({ busy: true, error: null });
      try {
        await play(await api.advanceChain(run.id));
      } catch (err) {
        set({ error: message(err, "Validation impossible.") });
      } finally {
        set({ busy: false });
      }
    },

    stop: async () => {
      const run = get().run;
      if (!run || get().busy) return;
      set({ busy: true, error: null });
      try {
        setRun(await api.stopChain(run.id));
      } catch (err) {
        set({ error: message(err, "Arrêt impossible.") });
      } finally {
        set({ busy: false });
      }
    },

    follow: async (run, stage) => {
      setRun(run);
      set({ error: null });
      remember(run.id);
      const index = stage ?? Math.min(run.stage_index, run.stages.length - 1);
      await get().openStage(index);
    },

    openStage: async (index) => {
      const run = get().run;
      const id = run?.stages[index]?.conversation_id;
      if (!run || !id) return;
      const opened = await useChatStore.getState().open(id);
      if (!opened) return;
      // Étape en cours jamais commencée (relais perdu) : on le redemande et on l'envoie
      const chat = useChatStore.getState();
      const empty = !(chat.conversations[chat.agent]?.turns.length ?? 0);
      if (run.status === "running" && index === run.stage_index && empty) {
        try {
          const step = await api.chainHandoff(run.id);
          if (step.handoff && step.conversation_id === id) void chat.send(step.handoff, { localOnly: step.local_only });
        } catch (err) {
          set({ error: message(err, "Message de relais indisponible.") });
        }
      }
    },

    showRecap: async () => {
      const run = get().run;
      if (!run) return;
      try {
        addRecap(await api.chainRecap(run.id), run.stages.at(-1)?.agent ?? "assistant");
      } catch (err) {
        set({ error: message(err, "Récapitulatif indisponible.") });
      }
    },

    close: () => {
      remember(null);
      setRun(null);
      set({ error: null });
    },
  };
});
