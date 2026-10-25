"use client";

import { Handle, type NodeProps, Position } from "@xyflow/react";
import { GitBranch, Repeat2, Table2 } from "lucide-react";
import { memo } from "react";

import { cn } from "@/lib/utils";

import { appTheme } from "./catalog";
import { type NodeTone, type StepNode as StepNodeType, nodeTone } from "./graph";
import { STEP_STATUS_LABEL } from "./run";
import { AppTile, ErrorIcon, KindBadge, StepStatusIcon } from "./StepBadges";

/**
 * Teinte de bordure par état (graph.ts › nodeTone). Au repos, le trait est celui de l'application
 * (jetons recalculés par `data-atelier-app`) ; l'étape à valider porte en plus la barre ambre des
 * cartes de décision.
 */
const TONE: Record<NodeTone, string> = {
  idle: "border-atelier-border-soft hover:border-atelier-border",
  invalid: "border-destructive",
  awaiting:
    "border-warning before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:rounded-l-[inherit] before:bg-warning",
  running: "border-atelier-border shadow-glow",
  failed: "border-destructive",
  done: "border-success/60",
  faded: "border-atelier-line opacity-60",
};

/**
 * Nœud du graphe : une étape, dans la couleur de son application (trait, tuile), avec son
 * libellé, son identifiant, la nature de l'action et son état d'exécution (bordure + icône).
 * Sélectionné : halo renforcé, sans anneau supplémentaire.
 */
function StepNodeView({ data, selected }: NodeProps<StepNodeType>) {
  const theme = appTheme(data.app, data.color);
  const run = data.run;
  const tone = nodeTone(data);
  const hasErrors = data.errors.length > 0;
  const note = data.unknown
    ? "Inconnue du catalogue"
    : data.unavailable
      ? data.unavailable
      : run?.errorCode
        ? `${STEP_STATUS_LABEL[run.status]} · ${run.errorCode}`
        : null;
  return (
    <div
      {...theme}
      title={data.errors.map((e) => e.message).join("\n") || data.unavailable || undefined}
      className={cn(
        "relative w-60 rounded-lg border bg-card px-3 py-2.5 text-card-foreground transition-[border-color,box-shadow,opacity]",
        TONE[tone],
        // Sélection : halo renforcé ; le trait reste celui de l'état (seul le repos s'avive)
        selected && "shadow-glow-strong",
        selected && tone === "idle" && "border-atelier-border",
        (data.unknown || data.unavailable) && "border-dashed",
      )}
    >
      <Handle type="target" position={Position.Left} aria-label={`Entrée de ${data.label}`} />
      <div className="flex items-start gap-2">
        <AppTile app={data.app} color={data.color} size="xs" className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm leading-tight font-medium">{data.label}</p>
          <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{data.stepId}</p>
        </div>
        {/* État d'exécution, puis problèmes : toujours en tête, même sans ligne de nature */}
        {(run || hasErrors) && (
          <span className="mt-0.5 flex shrink-0 items-center gap-1">
            {run && <StepStatusIcon status={run.status} className="size-4" />}
            {hasErrors && <ErrorIcon className="size-4" label={`${data.errors.length} problème(s)`} />}
          </span>
        )}
      </div>
      {(data.kind || data.outputFormat === "atelier-table/1" || data.conditional || data.continueOnError) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {data.kind && <KindBadge kind={data.kind} compact />}
          {data.outputFormat === "atelier-table/1" && (
            <span className="inline-flex items-center gap-1" title="Sortie en table (atelier-table/1)">
              <Table2 className="size-3.5" aria-hidden />
              table
            </span>
          )}
          {data.conditional && (
            <span className="inline-flex items-center gap-1" title="Exécutée seulement si sa condition est vraie">
              <GitBranch className="size-3.5" aria-hidden />
              si…
            </span>
          )}
          {data.continueOnError && (
            <span className="inline-flex items-center gap-1" title="En cas d'erreur, la suite continue">
              <Repeat2 className="size-3.5" aria-hidden />
              continue
            </span>
          )}
        </div>
      )}
      {note && <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">{note}</p>}
      <Handle type="source" position={Position.Right} aria-label={`Sortie de ${data.label}`} />
    </div>
  );
}

export const StepNode = memo(StepNodeView);
