/**
 * Ouverture des écrans « workflows de suite » depuis n'importe où (en-tête, liste des workflows
 * d'un agent, carte de la suite) : éditeur en graphe, liste des workflows, carte de la suite.
 */

import { create } from "zustand";

export type EditorTarget =
  /** Workflow enregistré ; `panel: "run"` ouvre directement le lancement */
  | { kind: "open"; id: string; panel?: "run" }
  /** Nouveau workflow (agent null = workflow de suite), éventuellement avec une première étape */
  | { kind: "new"; agent: string | null; uses?: string };

interface WorkflowStudioState {
  editor: EditorTarget | null;
  /** Fenêtre rouverte à la fermeture de l'éditeur */
  returnTo: "list" | "map" | null;
  /** Modifications non enregistrées dans l'éditeur (fermeture confirmée) */
  editorDirty: boolean;
  /** Change à chaque ouverture : l'éditeur repart de zéro même pour la même cible */
  editorKey: number;
  listOpen: boolean;
  /** Agent dont on liste les workflows ; null = tous (workflows de suite compris) */
  listAgent: string | null;
  mapOpen: boolean;
  /** Incrémenté après un enregistrement, une conversion ou une suppression : les listes se rechargent */
  version: number;
  openEditor: (target: EditorTarget) => void;
  closeEditor: () => void;
  setEditorDirty: (dirty: boolean) => void;
  openList: (agent: string | null) => void;
  setListOpen: (open: boolean) => void;
  setMapOpen: (open: boolean) => void;
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
  version: 0,
  // Une fenêtre à la fois : l'éditeur remplace la liste ou la carte, qui revient à sa fermeture
  openEditor: (target) =>
    set((s) => ({
      editor: target,
      editorKey: s.editorKey + 1,
      editorDirty: false,
      returnTo: s.editor ? s.returnTo : s.mapOpen ? "map" : s.listOpen ? "list" : null,
      listOpen: false,
      mapOpen: false,
    })),
  closeEditor: () =>
    set((s) => ({
      editor: null,
      returnTo: null,
      editorDirty: false,
      listOpen: s.returnTo === "list",
      mapOpen: s.returnTo === "map",
    })),
  setEditorDirty: (dirty) => set({ editorDirty: dirty }),
  openList: (agent) => set({ listOpen: true, listAgent: agent, mapOpen: false }),
  setListOpen: (open) => set({ listOpen: open }),
  setMapOpen: (open) => set((s) => ({ mapOpen: open, listOpen: open ? false : s.listOpen })),
  bump: () => set((s) => ({ version: s.version + 1 })),
}));
