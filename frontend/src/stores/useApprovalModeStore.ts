/**
 * Réglage APPROVAL_MODE vu par l'interface (textes des déclencheurs et de « À valider ») :
 * lu une fois dans GET /api/settings, mis à jour quand les Réglages sont enregistrés.
 * Tant qu'il n'est pas lu (ou s'il est illisible), on affiche le défaut et le plus prudent :
 * chaque action attend une validation. Le serveur reste seul juge de ce qui s'exécute.
 */

"use client";

import { useEffect } from "react";
import { create } from "zustand";

import { DEFAULT_APPROVAL_MODE, approvalModeOf } from "@/lib/approval";
import { api } from "@/lib/api";
import type { ApprovalMode, SettingsView } from "@/types/api";

interface ApprovalModeState {
  mode: ApprovalMode;
  status: "idle" | "loading" | "ready";
  /** Lit le réglage (une seule lecture à la fois). */
  load: () => Promise<void>;
  /** Vue renvoyée par l'enregistrement des Réglages. */
  fromSettings: (view: SettingsView) => void;
}

export const useApprovalModeStore = create<ApprovalModeState>((set, get) => ({
  mode: DEFAULT_APPROVAL_MODE,
  status: "idle",
  load: async () => {
    if (get().status === "loading") return;
    set({ status: "loading" });
    try {
      set({ mode: approvalModeOf(await api.settings()), status: "ready" });
    } catch {
      set({ status: "ready" }); // illisible : on garde le plus prudent
    }
  },
  fromSettings: (view) => set({ mode: approvalModeOf(view), status: "ready" }),
}));

/** Mode courant ; déclenche la première lecture si besoin. */
export function useApprovalMode(): ApprovalMode {
  const mode = useApprovalModeStore((s) => s.mode);
  const status = useApprovalModeStore((s) => s.status);
  const load = useApprovalModeStore((s) => s.load);
  useEffect(() => {
    if (status === "idle") void load();
  }, [status, load]);
  return mode;
}
