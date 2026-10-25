"use client";

import { useSyncExternalStore } from "react";

import { api } from "@/lib/api";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";

import { INBOX_POLL_MS } from "./origin";
import { sharedPoll } from "./sharedPoll";

/**
 * Compteur unique de l'application : barre latérale, barre mobile, Studio et accueil lisent la
 * même valeur, une seule requête toutes les 20 s quel que soit le nombre de badges affichés.
 */
const inbox = sharedPoll<number>({
  read: (signal) => api.inboxCount(signal).then((r) => r.awaiting_approval),
  intervalMs: INBOX_POLL_MS,
  visible: () => document.visibilityState === "visible",
  watch: (wake) => {
    document.addEventListener("visibilitychange", wake);
    // Relu après chaque décision ou lancement (`bumpInbox`)
    const unsubscribe = useWorkflowStudioStore.subscribe((s, prev) => {
      if (s.inboxVersion !== prev.inboxVersion) wake();
    });
    return () => {
      document.removeEventListener("visibilitychange", wake);
      unsubscribe();
    };
  },
});

/**
 * Nombre d'exécutions en attente de validation (badge « À valider »), relu toutes les 20 s.
 * Rien n'est interrogé tant que l'onglet est caché ; relu dès qu'il redevient visible, et après
 * chaque décision ou lancement (`bumpInbox`). null : serveur injoignable ou pas encore lu.
 */
export function useInboxCount(): number | null {
  return useSyncExternalStore(inbox.subscribe, inbox.get, () => null);
}
