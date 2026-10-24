"use client";

import { Check, CircleDot, CircleSlash, FileText, Square, Workflow as ChainIcon, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { emptyConversation } from "@/features/chat-agent/conversation";
import { cn } from "@/lib/utils";
import { useChainStore } from "@/stores/useChainStore";
import { useChatStore } from "@/stores/useChatStore";
import type { ChainInfo } from "@/types/api";

import { RUN_STATUS_LABEL, advanceLabel, progressLabel, stageOfConversation, stageReadiness } from "./chain";

const STAGE_ICON = {
  validated: { Icon: Check, label: "validée", className: "text-success" },
  active: { Icon: CircleDot, label: "en cours", className: "text-accent-ink" },
  pending: { Icon: CircleDot, label: "à venir", className: "text-muted-foreground opacity-50" },
  skipped: { Icon: CircleSlash, label: "non jouée", className: "text-muted-foreground" },
} as const;

/**
 * Bandeau de la chaîne suivie, au-dessus de la conversation : étapes, validation du livrable
 * de l'étape courante (quand l'agent a fini), arrêt. Hors de la conversation d'une étape : un
 * rappel pour la reprendre.
 */
export function ChainBar({ chains }: { chains: ChainInfo[] }) {
  const run = useChainStore((s) => s.run);
  const busy = useChainStore((s) => s.busy);
  const error = useChainStore((s) => s.error);
  const advance = useChainStore((s) => s.advance);
  const stop = useChainStore((s) => s.stop);
  const openStage = useChainStore((s) => s.openStage);
  const showRecap = useChainStore((s) => s.showRecap);
  const close = useChainStore((s) => s.close);
  const agent = useChatStore((s) => s.agent);
  const conversationId = useChatStore((s) => s.conversationIds[agent] ?? null);
  const turns = (useChatStore((s) => s.conversations[agent]) ?? emptyConversation()).turns;
  const streaming = useChatStore((s) => s.streaming);
  const saveError = useChatStore((s) => s.saveError);
  const [confirmStop, setConfirmStop] = useState(false);

  if (!run) return null;
  const chain = chains.find((c) => c.id === run.chain);
  const shown = stageOfConversation(run, conversationId);
  const running = run.status === "running";
  const onCurrent = running && shown === run.stage_index;
  const readiness = stageReadiness(turns, streaming, saveError);

  return (
    <section
      aria-label={`Chaîne : ${chain?.title ?? run.chain}`}
      className="shrink-0 border-b border-atelier-line bg-accent-soft/60 px-4 py-2"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        <div className="flex items-center gap-2">
          <ChainIcon className="size-4 shrink-0 text-accent-ink" aria-hidden />
          <p className="min-w-0 flex-1 truncate text-sm font-medium">
            {chain?.title ?? run.chain}
            <span className="font-normal text-muted-foreground">
              {" · "}
              {running ? progressLabel(run) : RUN_STATUS_LABEL[run.status]}
            </span>
          </p>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Ne plus suivre cette chaîne"
            title="Ne plus suivre cette chaîne (elle reste dans « Chaînes »)"
            onClick={close}
          >
            <X />
          </Button>
        </div>
        <ol className="flex min-w-0 flex-wrap items-center gap-1" aria-label="Étapes">
          {run.stages.map((stage, i) => {
            const { Icon, label, className } = STAGE_ICON[stage.status];
            const reachable = !!stage.conversation_id && !streaming;
            return (
              <li key={`${stage.agent}-${i}`}>
                <button
                  type="button"
                  disabled={!reachable}
                  aria-current={shown === i ? "step" : undefined}
                  title={`${i + 1}. ${stage.role} — ${label}${reachable ? " (ouvrir)" : ""}`}
                  onClick={() => void openStage(i)}
                  className={cn(
                    "flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-xs transition-colors enabled:hover:border-primary",
                    shown === i ? "border-primary bg-card font-medium" : "border-transparent",
                  )}
                >
                  <Icon className={cn("size-3", className)} aria-hidden />
                  <span className="tabular-nums">{i + 1}</span>
                  <span className="hidden sm:inline">{stage.role}</span>
                  <span className="sr-only">({label})</span>
                </button>
              </li>
            );
          })}
        </ol>

        {running && !onCurrent && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Cette conversation n&apos;est pas l&apos;étape en cours.</span>
            <Button size="sm" variant="outline" disabled={streaming} onClick={() => void openStage(run.stage_index)}>
              Reprendre l&apos;étape {run.stage_index + 1}
            </Button>
          </div>
        )}

        {onCurrent && (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={busy || !readiness.ready} onClick={() => void advance()}>
              <Check />
              {busy ? "Validation…" : advanceLabel(run, chain)}
            </Button>
            {!readiness.ready && <span className="text-xs text-muted-foreground">{readiness.reason}</span>}
            {readiness.ready && (
              <span className="text-xs text-muted-foreground">
                Pas satisfait ? Écrivez une correction à l&apos;agent avant de valider.
              </span>
            )}
            <span className="ml-auto flex items-center gap-1">
              {confirmStop ? (
                <>
                  <Button size="sm" variant="destructive" disabled={busy} onClick={() => void stop().then(() => setConfirmStop(false))}>
                    Arrêter la chaîne
                  </Button>
                  <Button size="icon-sm" variant="ghost" aria-label="Annuler" onClick={() => setConfirmStop(false)}>
                    <X />
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirmStop(true)}>
                  <Square />
                  Arrêter
                </Button>
              )}
            </span>
          </div>
        )}

        {run.status !== "running" && (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => void showRecap()}>
              <FileText />
              Récapitulatif
            </Button>
          </div>
        )}

        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
