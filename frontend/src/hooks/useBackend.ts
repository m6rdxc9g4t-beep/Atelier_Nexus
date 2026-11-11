"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { registerToolLabels } from "@/features/chat-agent/ToolCall";
import { ApiError, api } from "@/lib/api";
import { stable } from "@/lib/stable";
import type { AgentInfo, AppStatus, ProviderStatus } from "@/types/api";

export interface BackendState {
  agents: AgentInfo[];
  providers: ProviderStatus[];
  apps: AppStatus[];
  loading: boolean;
  /** Serveur Nexus injoignable ou en erreur. */
  error: string | null;
  /** Recharge tout, sans le cache du serveur ; la promesse se résout une fois l'état à jour. */
  reload: () => Promise<void>;
}

/**
 * Charge agents, moteurs et état des applications ; recharge toutes les 30 s tant que l'onglet
 * est visible (rien n'est interrogé onglet caché ; relu dès qu'il redevient visible).
 */
export function useBackend(): BackendState {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [apps, setApps] = useState<AppStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const current = useRef<AbortController | null>(null);

  const load = useCallback(async (refresh: boolean) => {
    current.current?.abort();
    const ctrl = new AbortController();
    current.current = ctrl;
    try {
      const [a, p, d] = await Promise.all([
        api.agents(ctrl.signal),
        api.providers(ctrl.signal, refresh),
        api.appsStatus(ctrl.signal, refresh),
      ]);
      if (ctrl.signal.aborted) return;
      registerToolLabels(a);
      // Relecture identique (le cas courant, toutes les 30 s) : mêmes références, aucun re-rendu
      setAgents((before) => stable(before, a));
      setProviders((before) => stable(before, p));
      setApps((before) => stable(before, d));
      setError(null);
    } catch (err) {
      if (ctrl.signal.aborted) return;
      setError(err instanceof ApiError ? err.message : "Impossible de joindre le serveur.");
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, []);

  // Demande explicite (« Réessayer », réglages ou agent enregistrés) : état relu par le serveur
  const reload = useCallback(() => load(true), [load]);

  useEffect(() => {
    // Premier chargement puis rafraîchissement périodique (mises à jour d'état asynchrones),
    // servi par le cache du serveur ; suspendu tant que l'onglet est caché
    const visible = () => document.visibilityState === "visible";
    const first = setTimeout(() => void load(false), 0);
    const id = setInterval(() => {
      if (visible()) void load(false);
    }, 30_000);
    const wake = () => {
      if (visible()) void load(false);
    };
    document.addEventListener("visibilitychange", wake);
    return () => {
      clearTimeout(first);
      clearInterval(id);
      document.removeEventListener("visibilitychange", wake);
      current.current?.abort();
    };
  }, [load]);

  return { agents, providers, apps, loading, error, reload };
}
