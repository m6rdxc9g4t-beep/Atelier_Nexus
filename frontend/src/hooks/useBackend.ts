"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { AgentInfo, AppStatus, ProviderStatus } from "@/types/api";

export interface BackendState {
  agents: AgentInfo[];
  providers: ProviderStatus[];
  apps: AppStatus[];
  loading: boolean;
  /** Serveur Nexus injoignable ou en erreur. */
  error: string | null;
  /** Recharge tout ; la promesse se résout une fois l'état à jour. */
  reload: () => Promise<void>;
}

/** Charge agents, moteurs et état des applications ; recharge toutes les 30 s. */
export function useBackend(): BackendState {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [apps, setApps] = useState<AppStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    current.current?.abort();
    const ctrl = new AbortController();
    current.current = ctrl;
    try {
      const [a, p, d] = await Promise.all([
        api.agents(ctrl.signal),
        api.providers(ctrl.signal),
        api.appsStatus(ctrl.signal),
      ]);
      if (ctrl.signal.aborted) return;
      setAgents(a);
      setProviders(p);
      setApps(d);
      setError(null);
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Impossible de joindre le serveur.");
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Premier chargement puis rafraîchissement périodique (mises à jour d'état asynchrones)
    const first = setTimeout(() => void reload(), 0);
    const id = setInterval(() => void reload(), 30_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
      current.current?.abort();
    };
  }, [reload]);

  return { agents, providers, apps, loading, error, reload };
}
