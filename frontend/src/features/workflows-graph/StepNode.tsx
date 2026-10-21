"use client";

import { Handle, type NodeProps, Position } from "@xyflow/react";
import { GitBranch, Repeat2 } from "lucide-react";
import { memo } from "react";

import { cn } from "@/lib/utils";

import { appTheme } from "./catalog";
import type { StepNode as StepNodeType } from "./graph";
import { STEP_STATUS_LABEL } from "./run";
import { AppTile, ErrorIcon, KindBadge, StepStatusIcon } from "./StepBadges";

/**
 * Nœud du graphe : une étape, dans la couleur de son application (trait, halo, tuile), avec son
 * libellé, son identifiant, la nature de l'action et son état d'exécution.
 */
function StepNodeView({ data, selected }: NodeProps<StepNodeType>) {
  const theme = appTheme(data.app, data.color);
  const run = data.run;
  const hasErrors = data.errors.length > 0;
  return (
    <div
      {...theme}
      title={data.errors.map((e) => e.message).join("\n") || data.unavailable || undefined}
      className={cn(
        "w-60 rounded-md border bg-card px-3 py-2.5 text-card-foreground transition-shadow",
        "border-atelier-border shadow-glow",
        selected && "shadow-glow-strong ring-2 ring-primary",
        hasErrors && "border-destructive ring-destructive/40",
        (data.unknown || data.unavailable) && "border-dashed opacity-80",
        run?.status === "running" && "ring-2 ring-primary/60",
        run?.status === "awaiting_approval" && "border-warning ring-2 ring-warning/50",
        run?.status === "skipped" && "opacity-60",
      )}
    >
      <Handle type="target" position={Position.Left} aria-label={`Entrée de ${data.label}`} />
      <div className="flex items-start gap-2">
        <AppTile app={data.app} color={data.color} size="xs" className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm leading-tight font-medium">{data.label}</p>
          <p className="truncate font-mono text-[11px] text-muted-foreground">{data.stepId}</p>
        </div>
        {run && <StepStatusIcon status={run.status} className="mt-0.5 size-4" />}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {data.kind && <KindBadge kind={data.kind} />}
        {data.outputFormat === "atelier-table/1" && (
          <span className="rounded-sm border border-atelier-line px-1 text-[10px] text-muted-foreground">table</span>
        )}
        {data.conditional && (
          <span className="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground" title="Exécutée seulement si sa condition est vraie">
            <GitBranch className="size-3" aria-hidden />
            si…
          </span>
        )}
        {data.continueOnError && (
          <span className="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground" title="En cas d'erreur, la suite continue">
            <Repeat2 className="size-3" aria-hidden />
            continue
          </span>
        )}
        {hasErrors && <ErrorIcon className="ml-auto" label={`${data.errors.length} problème(s)`} />}
      </div>
      {(data.unknown || data.unavailable || run?.errorCode) && (
        <p className="mt-1.5 line-clamp-2 text-[11px] text-muted-foreground">
          {data.unknown
            ? "Inconnue du catalogue"
            : data.unavailable
              ? data.unavailable
              : `${STEP_STATUS_LABEL[run!.status]} · ${run!.errorCode}`}
        </p>
      )}
      <Handle type="source" position={Position.Right} aria-label={`Sortie de ${data.label}`} />
    </div>
  );
}

export const StepNode = memo(StepNodeView);
