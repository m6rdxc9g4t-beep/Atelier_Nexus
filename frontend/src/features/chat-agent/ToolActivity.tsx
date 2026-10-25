"use client";

import { ChevronRight } from "lucide-react";
import { useId, useState } from "react";

import { AppChip } from "@/components/layout/AppChip";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { ActionStatusIcon } from "./ActionStatusIcon";
import { type ActivityEntry, activitySummary } from "./thread";
import { ToolCall, toolLabel } from "./ToolCall";

/** Libellé d'une action ; une délégation nomme l'agent qui reçoit la sous-tâche. */
export function actionLabel(entry: Pick<ActivityEntry, "name" | "input">, agentLabel: (name: string) => string): string {
  const target = entry.input.agent;
  if (entry.name === "delegate_to_agent" && typeof target === "string" && target) {
    return `Délégation à ${agentLabel(target)}`;
  }
  return toolLabel(entry.name);
}

/**
 * Appels d'outils consécutifs d'un tour, sur une seule ligne : « 4 actions · Viz, Projets » et
 * l'état global. Dépliée, la chronologie des actions (une ligne chacune, paramètres et résultat
 * repliés). Montre les applications plutôt que les noms techniques des outils.
 */
export function ToolActivity({
  entries,
  agentLabel,
}: {
  entries: ActivityEntry[];
  agentLabel: (name: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const summary = activitySummary(entries);
  const label = (entry: ActivityEntry) => actionLabel(entry, agentLabel);
  const single = summary.count === 1 ? entries[0] : undefined;
  const title = single ? label(single) : `${summary.count} actions`;

  return (
    <div className="text-sm">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen((o) => !o)}
        className="-mx-2 flex w-[calc(100%+1rem)] min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <ActionStatusIcon status={summary.status} />
        <span className="max-w-[60%] min-w-0 shrink-0 truncate font-medium text-foreground">{title}</span>
        {summary.apps.length > 0 && (
          <span className="flex min-w-0 items-center gap-1 overflow-hidden">
            <span aria-hidden>·</span>
            {summary.apps.map((app) => (
              <AppChip key={app} app={app} />
            ))}
          </span>
        )}
        {summary.status === "running" && summary.current && summary.count > 1 && (
          <span className="min-w-0 flex-1 truncate text-xs">{label(summary.current)}…</span>
        )}
        {/* Reçu de la validation : décision d'une action seule, refus comptés sinon */}
        {single?.decision !== undefined ? (
          <Badge variant={single.decision ? "success" : "outline"} className="shrink-0">
            {single.decision ? "Autorisée" : "Refusée"}
          </Badge>
        ) : (
          summary.refused > 0 && (
            <span className="shrink-0 text-xs">
              · {summary.refused} refusée{summary.refused > 1 ? "s" : ""}
            </span>
          )
        )}
        {summary.errors > 0 && (
          <span className="shrink-0 text-xs text-destructive-ink">· {summary.errors} en erreur</span>
        )}
        {summary.interrupted > 0 && (
          <span className="shrink-0 text-xs text-warning-ink">
            · {summary.interrupted} non exécutée{summary.interrupted > 1 ? "s" : ""}
          </span>
        )}
        <ChevronRight className={cn("ml-auto size-4 shrink-0 transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open && (
        <ol
          id={listId}
          aria-label="Chronologie des actions"
          className="mt-1 ml-2 flex flex-col gap-0.5 border-l border-atelier-line pl-3"
        >
          {entries.map((entry) => (
            <ToolCall key={entry.id} entry={entry} label={label(entry)} />
          ))}
        </ol>
      )}
    </div>
  );
}
