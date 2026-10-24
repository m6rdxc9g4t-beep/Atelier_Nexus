"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { ChainInfo } from "@/types/api";

/** Chaînes d'agents fournies (Data, Dev) ; rechargées quand le catalogue d'agents change. */
export function useChains(agentCount: number): ChainInfo[] {
  const [chains, setChains] = useState<ChainInfo[]>([]);
  useEffect(() => {
    if (!agentCount) return;
    const controller = new AbortController();
    api
      .chains(controller.signal)
      .then(setChains)
      .catch(() => {
        // serveur ancien ou indisponible : pas de chaînes, le reste fonctionne
      });
    return () => controller.abort();
  }, [agentCount]);
  return chains;
}
