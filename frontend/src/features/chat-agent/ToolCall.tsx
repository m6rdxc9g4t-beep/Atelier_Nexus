"use client";

import { ChevronRight, CircleAlert, CircleCheck, LoaderCircle, Wrench } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import type { ToolCallPart } from "./conversation";

/** Libellés lisibles des outils connus ; les autres gardent leur nom technique. */
const TOOL_LABELS: Record<string, string> = {
  current_datetime: "Date et heure",
  publish_artifact: "Publication d'un artefact",
  data_via_list_datasets: "Data Via · jeux de données",
  data_via_describe_dataset: "Data Via · schéma",
  data_via_query: "Data Via · requête",
  data_via_check_expression: "Data Via · vérification de mesure",
};

export const toolLabel = (name: string) => TOOL_LABELS[name] ?? name;

/** Appel d'outil replié : on voit qu'il a eu lieu, on déplie pour l'entrée et le résultat. */
export function ToolCall({ part }: { part: ToolCallPart }) {
  const [open, setOpen] = useState(false);
  const Icon =
    part.status === "running" ? LoaderCircle : part.status === "error" ? CircleAlert : CircleCheck;
  const state =
    part.status === "running" ? "en cours" : part.status === "error" ? "en erreur" : "terminé";

  return (
    <div className="rounded-md border bg-sunken text-sm">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-muted-foreground hover:text-foreground"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        <Wrench className="size-3.5" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{toolLabel(part.name)}</span>
        <Icon
          aria-label={state}
          className={cn(
            "size-3.5",
            part.status === "running" && "animate-spin",
            part.status === "error" && "text-destructive",
            part.status === "done" && "text-success",
          )}
        />
      </button>
      {open && (
        <div className="space-y-2 border-t px-2.5 py-2">
          <Detail label="Paramètres">{JSON.stringify(part.input, null, 2)}</Detail>
          {part.result !== undefined && <Detail label="Résultat">{part.result}</Detail>}
        </div>
      )}
    </div>
  );
}

function Detail({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <p className="mb-1 text-xs text-muted-foreground">{label}</p>
      <pre className="max-h-64 overflow-auto rounded-sm bg-card p-2 font-mono text-xs leading-snug whitespace-pre-wrap">
        {children}
      </pre>
    </div>
  );
}
