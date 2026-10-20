"use client";

import { Check, ShieldQuestion, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { ApprovalPart } from "./conversation";
import { toolLabel } from "./ToolCall";

interface ApprovalCardProps {
  part: ApprovalPart;
  disabled: boolean;
  onSubmit: (decisions: Record<string, boolean>) => void;
}

/**
 * Validation humaine d'une action qui modifie des données. Un seul appel : « Autoriser » /
 * « Refuser » répondent directement. Plusieurs : on décide de chacun, puis on envoie.
 */
export function ApprovalCard({ part, disabled, onSubmit }: ApprovalCardProps) {
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const single = part.calls.length === 1;
  const decided = part.submitted ? part.decisions : decisions;
  const complete = part.calls.every((c) => decided[c.id] !== undefined);

  const choose = (id: string, value: boolean) => {
    if (single) {
      onSubmit({ [id]: value });
      return;
    }
    setDecisions((d) => ({ ...d, [id]: value }));
  };

  return (
    <section
      aria-label="Action à valider"
      className={cn(
        "rounded-lg border p-3",
        part.submitted ? "bg-card" : "border-warning/50 bg-warning/8",
      )}
    >
      <header className="mb-2 flex items-center gap-2 text-sm font-medium">
        <ShieldQuestion className="size-4 text-warning" aria-hidden />
        {part.submitted
          ? "Votre décision"
          : single
            ? "L'agent veut effectuer cette action"
            : `L'agent veut effectuer ${part.calls.length} actions`}
      </header>
      <ul className="flex flex-col gap-2">
        {part.calls.map((call) => {
          const choice = decided[call.id];
          return (
            <li key={call.id} className="flex flex-wrap items-center gap-2 rounded-md bg-card px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm">{call.summary}</p>
                <p className="text-xs text-muted-foreground">{toolLabel(call.name)}</p>
              </div>
              {part.submitted ? (
                <Badge variant={choice ? "success" : "destructive"}>
                  {choice ? "Autorisée" : "Refusée"}
                </Badge>
              ) : (
                <div className="flex gap-1.5">
                  <Button
                    size="sm"
                    variant={choice === false ? "secondary" : "outline"}
                    disabled={disabled}
                    aria-pressed={choice === false}
                    onClick={() => choose(call.id, false)}
                  >
                    <X />
                    Refuser
                  </Button>
                  <Button
                    size="sm"
                    variant={choice === true || single ? "default" : "outline"}
                    disabled={disabled}
                    aria-pressed={choice === true}
                    onClick={() => choose(call.id, true)}
                  >
                    <Check />
                    Autoriser
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {!single && !part.submitted && (
        <div className="mt-2 flex justify-end">
          <Button size="sm" disabled={!complete || disabled} onClick={() => onSubmit(decisions)}>
            Envoyer mes choix
          </Button>
        </div>
      )}
    </section>
  );
}
