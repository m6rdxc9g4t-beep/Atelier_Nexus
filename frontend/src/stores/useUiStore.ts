/**
 * État d'interface partagé : fenêtre des Réglages, ouvrable depuis n'importe où (barre latérale,
 * message « non configuré », accueil d'un agent), une seule à la fois.
 */

import { create } from "zustand";

interface UiState {
  settingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;
  openSettings: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  settingsOpen: false,
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  openSettings: () => set({ settingsOpen: true }),
}));
