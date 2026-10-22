/**
 * Ouverture des écrans « workflows de suite » depuis n'importe où (en-tête, liste des workflows
 * d'un agent, carte de la suite, boîte « À valider ») : éditeur en graphe, liste des workflows,
 * carte de la suite, boîte « À valider ».
 */

import { create } from "zustand";

import type { TriggerApp } from "@/types/api";

/** Déclencheur événement à préremplir (« + » d'un événement de la carte de la suite). */
export interface TriggerPreset {
  app: TriggerApp;
  types: string[];
}

export type EditorTarget =
  /**
   * Workflow enregistré ; `panel` ouvre directement le lancement ou les déclencheurs, `runId`
   * affiche cette exécution dans le suivi, `trigger` ouvre un déclencheur prérempli.
   */
  | { kind: "open"; id: string; panel?: "run" | "triggers"; runId?: string; trigger?: TriggerPreset }
  /** Nouveau workflow (agent null = workflow de suite), éventuellement avec une première étape ou un déclencheur */
  | { kind: "new"; agent: string | null; uses?: string; trigger?: TriggerPreset };

type Window = "list" | "map" | "inbox";

interface WorkflowStudioState {
  editor: EditorTarget | null;
  /** Fenêtre rouverte à la fermeture de l'éditeur */
  returnTo: Window | null;
  /** Modifications non enregistrées dans l'éditeur (fermeture confirmée) */
  editorDirty: boolean;
  /** Change à chaque ouverture : l'éditeur repart de zéro même pour la même cible */
  editorKey: number;
  listOpen: boolean;
  /** Agent dont on liste les workflows ; null = tous (workflows de suite compris) */
  listAgent: string | null;
  mapOpen: boolean;
  /** Boîte « À valider » (exécutions en attente de validation, tous workflows) */
  inboxOpen: boolean;
  /** Incrémenté après une décision ou un lancement : le badge « À valider » se relit */
  inboxVersion: number;
  /** Dernier workflow v2 enregistré ouvert dans l'éditeur (« Ajouter au workflow ouvert ») */
  lastWorkflow: { id: string; title: string } | null;
  /** Incrémenté après un enregistrement, une conversion ou une suppression : les listes se rechargent */
  version: number;
  openEditor: (target: EditorTarget) => void;
  closeEditor: () => void;
  setEditorDirty: (dirty: boolean) => void;
  openList: (agent: string | null) => void;
  setListOpen: (open: boolean) => void;
  setMapOpen: (open: boolean) => void;
  setInboxOpen: (open: boolean) => void;
  bumpInbox: () => void;
  setLastWorkflow: (wf: { id: string; title: string } | null) => void;
  bump: () => void;
}

export const useWorkflowStudioStore = create<WorkflowStudioState>((set) => ({
  editor: null,
  returnTo: null,
  editorDirty: false,
  editorKey: 0,
  listOpen: false,
  listAgent: null,
  mapOpen: false,
  inboxOpen: false,
  inboxVersion: 0,
  lastWorkflow: null,
  version: 0,
  // Une fenêtre à la fois : l'éditeur remplace la liste ou la carte, qui revient à sa fermeture
  openEditor: (target) =>
    set((s) => ({
      editor: target,
      editorKey: s.editorKey + 1,
      editorDirty: false,
      returnTo: s.editor ? s.returnTo : s.mapOpen ? "map" : s.listOpen ? "list" : s.inboxOpen ? "inbox" : null,
      listOpen: false,
      mapOpen: false,
      inboxOpen: false,
    })),
  closeEditor: () =>
    set((s) => ({
      editor: null,
      returnTo: null,
      editorDirty: false,
      listOpen: s.returnTo === "list",
      mapOpen: s.returnTo === "map",
      inboxOpen: s.returnTo === "inbox",
    })),
  setEditorDirty: (dirty) => set({ editorDirty: dirty }),
  openList: (agent) => set({ listOpen: true, listAgent: agent, mapOpen: false, inboxOpen: false }),
  setListOpen: (open) => set({ listOpen: open }),
  setMapOpen: (open) => set((s) => ({ mapOpen: open, listOpen: open ? false : s.listOpen, inboxOpen: open ? false : s.inboxOpen })),
  setInboxOpen: (open) =>
    set((s) => ({ inboxOpen: open, listOpen: open ? false : s.listOpen, mapOpen: open ? false : s.mapOpen })),
  bumpInbox: () => set((s) => ({ inboxVersion: s.inboxVersion + 1 })),
  setLastWorkflow: (wf) => set({ lastWorkflow: wf }),
  bump: () => set((s) => ({ version: s.version + 1 })),
}));
