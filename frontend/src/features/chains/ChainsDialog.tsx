"use client";

import { ArrowLeft, Lock, Play, RotateCcw } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { AgentIcon } from "@/features/chat-agent/agentMeta";
import { formatWhen } from "@/features/chat-agent/formatWhen";
import { ApiError, api } from "@/lib/api";
import { useChainStore } from "@/stores/useChainStore";
import { useChatStore } from "@/stores/useChatStore";
import type { AgentInfo, ChainInfo, ChainRun } from "@/types/api";

import { RUN_STATUS_LABEL, progressLabel } from "./chain";

const EXAMPLES: Record<string, string> = {
  chaine_data: "Ex. : analyser le chiffre d'affaires par région et par mois de ventes_2026, avec les mesures DAX pour mon rapport Power BI.",
  chaine_dev: "Ex. : ajouter un export CSV de la liste des tâches dans l'application, avec ses tests.",
};

/** Lancer une chaîne (Data, Dev) ou reprendre une exécution récente. */
export function ChainsDialog({ chains, agents }: { chains: ChainInfo[]; agents: AgentInfo[] }) {
  const launcher = useChainStore((s) => s.launcher);
  const close = useChainStore((s) => s.closeLauncher);
  const open = useChainStore((s) => s.openLauncher);
  const chain = chains.find((c) => c.id === launcher.chain);

  return (
    <Dialog open={launcher.open} onOpenChange={(o) => (o ? open(launcher.chain) : close())}>
      <DialogContent className="max-w-2xl grid-cols-[minmax(0,1fr)]">
        {chain ? (
          <ChainForm key={chain.id} chain={chain} agents={agents} onBack={() => open(null)} onDone={close} />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Chaînes d&apos;agents</DialogTitle>
              <DialogDescription>
                Une demande traverse plusieurs agents spécialisés, dans l&apos;ordre. Vous validez le
                livrable de chaque agent avant que le suivant ne commence.
              </DialogDescription>
            </DialogHeader>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-2">
              {chains.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => open(c.id)}
                    className="flex w-full items-start gap-3 rounded-md border border-atelier-border bg-card p-3 text-left shadow-glow transition-colors hover:border-primary hover:bg-atelier-surface-2"
                  >
                    <AgentIcon icon={c.icon} className="mt-0.5 size-5 shrink-0 text-accent-ink" aria-hidden />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{c.title}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{c.description}</span>
                      <span className="mt-1.5 block text-xs text-muted-foreground">
                        {c.stages.map((s) => s.display_name).join(" → ")}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ChainForm({
  chain,
  agents,
  onBack,
  onDone,
}: {
  chain: ChainInfo;
  agents: AgentInfo[];
  onBack: () => void;
  onDone: () => void;
}) {
  const [request, setRequest] = useState("");
  const [runs, setRuns] = useState<ChainRun[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const start = useChainStore((s) => s.start);
  const follow = useChainStore((s) => s.follow);
  const busy = useChainStore((s) => s.busy);
  const error = useChainStore((s) => s.error);
  const streaming = useChatStore((s) => s.streaming);
  const id = useId();

  useEffect(() => {
    const controller = new AbortController();
    api
      .chainRuns(chain.id, controller.signal)
      .then(setRuns)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setListError(err instanceof ApiError ? err.message : "Liste indisponible.");
      });
    return () => controller.abort();
  }, [chain.id]);

  const icon = (agent: string) => agents.find((a) => a.name === agent)?.icon;

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Button variant="ghost" size="icon-sm" aria-label="Toutes les chaînes" onClick={onBack}>
            <ArrowLeft />
          </Button>
          {chain.title}
        </DialogTitle>
        <DialogDescription>{chain.description}</DialogDescription>
      </DialogHeader>

      <ol className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
        {chain.stages.map((stage, i) => (
          <li key={stage.agent} className="flex items-start gap-2.5 rounded-md border border-atelier-line bg-card px-3 py-2">
            <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-medium text-accent-ink tabular-nums">
              {i + 1}
            </span>
            <AgentIcon icon={icon(stage.agent)} className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 text-sm">
              <span className="font-medium">{stage.role}</span>
              <span className="text-muted-foreground"> · {stage.display_name}</span>
              {stage.local_only && <Lock className="ml-1 inline size-3 text-muted-foreground" aria-label="100 % local" />}
              <span className="block text-xs text-muted-foreground">{stage.instructions}</span>
            </span>
          </li>
        ))}
      </ol>

      <form
        className="grid grid-cols-[minmax(0,1fr)] gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void start(chain.id, request.trim()).then((ok) => ok && onDone());
        }}
      >
        <label htmlFor={id} className="text-sm font-medium">
          Votre demande
        </label>
        <Textarea
          id={id}
          rows={3}
          maxLength={8000}
          value={request}
          placeholder={EXAMPLES[chain.id] ?? "Décrivez ce que vous voulez obtenir."}
          onChange={(e) => setRequest(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Chaque agent travaille dans sa propre conversation : ses actions et ses résultats attendent
          votre validation, puis vous validez son livrable pour passer à l&apos;étape suivante.
        </p>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button type="submit" disabled={busy || streaming || request.trim().length < 3}>
            <Play />
            {busy ? "Lancement…" : "Lancer la chaîne"}
          </Button>
        </DialogFooter>
      </form>

      {listError && <p className="text-xs text-muted-foreground">Exécutions récentes indisponibles : {listError}</p>}
      {runs && runs.length > 0 && (
        <section aria-label="Exécutions récentes" className="grid grid-cols-[minmax(0,1fr)] gap-1.5 border-t border-atelier-line pt-3">
          <h3 className="text-xs font-medium text-muted-foreground">Exécutions récentes</h3>
          <ul className="grid max-h-48 grid-cols-[minmax(0,1fr)] gap-1.5 overflow-y-auto">
            {runs.map((run) => (
              <li key={run.id} className="flex items-center gap-2 rounded-md border border-atelier-line px-3 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{run.request}</span>
                  <span className="block text-xs text-muted-foreground">
                    {formatWhen(run.updated_at)} · {run.status === "running" ? progressLabel(run) : RUN_STATUS_LABEL[run.status]}
                  </span>
                </span>
                <Badge variant={run.status === "completed" ? "success" : run.status === "stopped" ? "outline" : "warning"}>
                  {RUN_STATUS_LABEL[run.status]}
                </Badge>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={streaming}
                  onClick={() => void follow(run).then(onDone)}
                >
                  <RotateCcw />
                  {run.status === "running" ? "Reprendre" : "Ouvrir"}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
