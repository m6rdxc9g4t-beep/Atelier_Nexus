/**
 * Store des artefacts (CLAUDE.md « Expérience Artefacts ») : tout livrable d'agent
 * (SQL, DAX, Power Query, code, aperçu Data Via…) arrive ici et s'affiche dans
 * le panneau latéral droit, au lieu d'encombrer le fil de discussion.
 */

import { create } from "zustand";

import type { Artifact } from "@/types/api";

export interface StoredArtifact extends Artifact {
  id: string;
  agent: string;
  createdAt: number;
}

interface ArtifactState {
  artifacts: StoredArtifact[];
  selectedId: string | null;
  panelOpen: boolean;
  /** `open` : afficher le panneau (faux sur petit écran, où il recouvrirait la conversation). */
  add: (artifact: Artifact, agent: string, open?: boolean) => StoredArtifact;
  select: (id: string) => void;
  remove: (id: string) => void;
  clear: () => void;
  setPanelOpen: (open: boolean) => void;
}

let counter = 0;
const newId = () => `art_${Date.now().toString(36)}_${(counter++).toString(36)}`;

export const useArtifactStore = create<ArtifactState>((set) => ({
  artifacts: [],
  selectedId: null,
  panelOpen: false,

  add: (artifact, agent, open = true) => {
    const stored: StoredArtifact = { ...artifact, id: newId(), agent, createdAt: Date.now() };
    // Le plus récent en tête et sélectionné
    set((s) => ({
      artifacts: [stored, ...s.artifacts],
      selectedId: stored.id,
      panelOpen: s.panelOpen || open,
    }));
    return stored;
  },

  select: (id) => set({ selectedId: id, panelOpen: true }),

  remove: (id) =>
    set((s) => {
      const artifacts = s.artifacts.filter((a) => a.id !== id);
      const selectedId = s.selectedId === id ? (artifacts[0]?.id ?? null) : s.selectedId;
      return { artifacts, selectedId, panelOpen: s.panelOpen && artifacts.length > 0 };
    }),

  clear: () => set({ artifacts: [], selectedId: null, panelOpen: false }),

  setPanelOpen: (open) => set({ panelOpen: open }),
}));

export const selectSelectedArtifact = (s: ArtifactState): StoredArtifact | null =>
  s.artifacts.find((a) => a.id === s.selectedId) ?? null;
