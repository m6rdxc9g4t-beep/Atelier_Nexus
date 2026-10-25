"use client";

import { ArrowUpRight, Eye, Lock, PenLine, Settings, Workflow } from "lucide-react";
import { useEffect, useState } from "react";

import { AppChip } from "@/components/layout/AppChip";
import { appShort } from "@/components/layout/appIcons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useUiStore } from "@/stores/useUiStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo } from "@/types/api";

import { agentApps } from "./agentApps";
import { AgentTile } from "./AgentTile";

/** Nombre de workflows de l'agent (null tant qu'il n'est pas connu, ou illisible). */
function useWorkflowCount(agent: string | undefined): number | null {
  const version = useWorkflowStudioStore((s) => s.version);
  const key = agent ? `${agent}:${version}` : "";
  const [state, setState] = useState<{ key: string; count: number } | null>(null);
  useEffect(() => {
    if (!agent) return;
    const controller = new AbortController();
    api
      .workflows(agent, controller.signal)
      .then((list) => setState({ key, count: list.length }))
      .catch(() => undefined); // sans liste, le bouton reste « Workflows »
    return () => controller.abort();
  }, [agent, key]);
  return state?.key === key ? state.count : null;
}

/**
 * Accueil d'une conversation vide : qui est l'agent, avec quelles applications il travaille et
 * s'il écrit (toujours avec validation), exemples pour commencer, workflows déjà enregistrés.
 * La pastille de l'agent porte le seul halo de l'écran.
 */
export function AgentWelcome({
  agent,
  label,
  starters,
  disabled,
  onStart,
}: {
  agent: AgentInfo | undefined;
  label: string;
  starters: string[];
  /** Envoi impossible (moteur non configuré, serveur absent) */
  disabled: boolean;
  onStart: (text: string) => void;
}) {
  const openList = useWorkflowStudioStore((s) => s.openList);
  const setListSection = useWorkflowStudioStore((s) => s.setListSection);
  const openSettings = useUiStore((s) => s.openSettings);
  const workflows = useWorkflowCount(agent?.name);
  const apps = agent ? agentApps(agent) : [];
  const writes = agent?.tools.some((t) => t.requires_approval) ?? false;
  const missing = agent?.unavailable_toolsets ?? [];
  // Boîtes écartées nommées par leur application ; une boîte d'extension inconnue, par son identifiant
  const missingNames = [
    ...new Set(
      missing.map((id) => {
        const [app] = agentApps({ toolsets: [id] });
        return app ? appShort(app) : id;
      }),
    ),
  ];

  return (
    <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center gap-8 px-6 py-10">
      <div className="flex flex-col items-start gap-4">
        <AgentTile
          icon={agent?.icon}
          size="lg"
          variant="plain"
          className="size-12 rounded-xl border-atelier-border-soft shadow-glow [&_svg]:size-6"
        />
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-shadow-glow">{label}</h2>
          {agent?.description && <p className="mt-1.5 text-muted-foreground">{agent.description}</p>}
        </div>
        {agent && (
          <div className="flex flex-wrap items-center gap-1.5">
            {apps.length > 0 && (
              <>
                <span className="text-xs text-muted-foreground">Travaille avec</span>
                {apps.map((app) => (
                  <AppChip key={app} app={app} />
                ))}
                <span aria-hidden className="text-muted-foreground">
                  ·
                </span>
              </>
            )}
            {writes ? (
              <Badge variant="outline" title="Toute modification de vos données attend votre accord, action par action">
                <PenLine aria-hidden />
                Écrit avec validation
              </Badge>
            ) : (
              <Badge variant="outline" title="Lit vos données sans jamais les modifier">
                <Eye aria-hidden />
                Lecture seule
              </Badge>
            )}
          </div>
        )}
        {agent?.local_only && (
          <Callout tone="signature" icon={Lock} className="w-full">
            Cet agent travaille sur des données qui ne quittent pas la machine : il utilise uniquement le modèle
            local (Ollama).
          </Callout>
        )}
        {missing.length > 0 && (
          <Callout
            tone="warning"
            className="w-full"
            action={
              <Button size="sm" variant="outline" onClick={openSettings}>
                <Settings />
                Ouvrir les réglages
              </Button>
            }
          >
            Non configuré : {missingNames.join(", ")}. Renseignez l&apos;adresse de l&apos;application dans les
            Réglages pour que l&apos;agent s&apos;en serve.
          </Callout>
        )}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {starters.map((starter) => (
          <button
            key={starter}
            type="button"
            disabled={disabled}
            onClick={() => onStart(starter)}
            className="group flex items-start gap-3 rounded-xl border border-atelier-line bg-card px-4 py-3 text-left text-sm leading-snug transition-colors hover:border-atelier-border hover:bg-atelier-surface-2 disabled:pointer-events-none disabled:opacity-50"
          >
            <span className="min-w-0 flex-1">{starter}</span>
            <ArrowUpRight className="size-4 shrink-0 text-accent-ink" aria-hidden />
          </button>
        ))}
      </div>

      {agent && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Button
            variant="soft"
            size="sm"
            onClick={() => {
              // Comme le bouton « Workflows » de l'en-tête : la liste de l'agent, pas les modèles
              openList(agent.name);
              setListSection("mine");
            }}
          >
            <Workflow />
            {workflows === null ? "Workflows" : `${workflows} workflow${workflows > 1 ? "s" : ""}`}
          </Button>
          <p className="text-xs text-muted-foreground">
            Après une réponse, enregistrez ses actions pour les rejouer sans modèle.
          </p>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Les agents peuvent se tromper : vérifiez les chiffres et le code avant de les utiliser.
      </p>
    </div>
  );
}

/** Ouverture d'une conversation enregistrée : la place du fil est gardée (trois blocs). */
export function ThreadSkeleton() {
  return (
    <div role="status" className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-8">
      <span className="sr-only">Ouverture de la conversation…</span>
      <Skeleton className="ml-auto h-11 w-2/3 rounded-2xl" />
      <div className="flex flex-col gap-2.5">
        <Skeleton className="h-6 w-36" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-2/3" />
      </div>
      <Skeleton className="ml-auto h-11 w-1/2 rounded-2xl" />
    </div>
  );
}
