"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { AgentInfo, DataViaStatus, ProviderStatus } from "@/types/api";

export interface BackendState {
  agents: AgentInfo[];
  providers: ProviderStatus[];
  dataVia: DataViaStatus | null;
  loading: boolean;
  /** Serveur Nexus injoignable ou en erreur. */
  error: string | null;
  reload: () => void;
}

/** Charge agents, moteurs et état de Data Via ; recharge toutes les 30 s. */
export function useBackend(): BackendState {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [dataVia, setDataVia] = useState<DataViaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const [a, p, d] = await Promise.all([
          api.agents(ctrl.signal),
          api.providers(ctrl.signal),
          api.dataViaStatus(ctrl.signal),
        ]);
        setAgents(a);
        setProviders(p);
        setDataVia(d);
        setError(null);
      } catch (err) {
        if (ctrl.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Impossible de joindre le serveur.");
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [tick]);

  useEffect(() => {
    const id = setInterval(reload, 30_000);
    return () => clearInterval(id);
  }, [reload]);

  return { agents, providers, dataVia, loading, error, reload };
}
