"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";

import { INBOX_POLL_MS } from "./origin";

/**
 * Nombre d'exécutions en attente de validation (badge « À valider »), relu toutes les 20 s.
 * Rien n'est interrogé tant que l'onglet est caché ; relu dès qu'il redevient visible, et après
 * chaque décision ou lancement (`bumpInbox`). null : serveur injoignable ou pas encore lu.
 */
export function useInboxCount(): number | null {
  const [count, setCount] = useState<number | null>(null);
  const version = useWorkflowStudioStore((s) => s.inboxVersion);

  useEffect(() => {
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const read = () => {
      api
        .inboxCount(ctrl.signal)
        .then((r) => setCount(r.awaiting_approval))
        .catch(() => !ctrl.signal.aborted && setCount(null));
    };
    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = null;
      if (document.visibilityState !== "visible") return;
      timer = setTimeout(() => {
        read();
        schedule();
      }, INBOX_POLL_MS);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") read();
      schedule();
    };
    // Première lecture hors du rendu, puis toutes les 20 s
    const first = setTimeout(() => {
      if (document.visibilityState === "visible") read();
      schedule();
    }, 0);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      ctrl.abort();
      clearTimeout(first);
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [version]);

  return count;
}
