/**
 * Navigation de l'écran principal : vue affichée (accueil ou conversation avec un agent) et
 * barre latérale en tiroir sur les petits écrans.
 */

import { create } from "zustand";

export type View = "home" | "agents";

interface NavState {
  view: View;
  /** Tiroir de navigation (sous lg) */
  drawerOpen: boolean;
  setView: (view: View) => void;
  setDrawerOpen: (open: boolean) => void;
}

export const useNavStore = create<NavState>((set) => ({
  view: "home",
  drawerOpen: false,
  // Changer de vue referme le tiroir (petits écrans)
  setView: (view) => set({ view, drawerOpen: false }),
  setDrawerOpen: (open) => set({ drawerOpen: open }),
}));
