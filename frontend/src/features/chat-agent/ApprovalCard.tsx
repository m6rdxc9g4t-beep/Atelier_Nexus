"use client";

import { Check, Eye, PenLine, ShieldQuestion, Users, X } from "lucide-react";
import { useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CALL_KIND_LABEL, callKind } from "@/lib/approval";
import { cn } from "@/lib/utils";
import type { CallKind, PendingCall } from "@/types/api";

import type { ApprovalPart } from "./conversation";
import { toolLabel } from "./ToolCall";

interface ApprovalCardProps {
  part: ApprovalPart;
  disabled: boolean;
  onSubmit: (decisions: Record<string, boolean>) => void;
}

const KIND_ICON = { read: Eye, write: PenLine, delegation: Users } as const;
const KIND_VARIANT = { read: "outline", write: "warning", delegation: "secondary" } as const;
const KIND_TITLE: Record<CallKind, string> = {
  read: "Lit des données sans les modifier",
  write: "Modifie des données",
  delegation: "Confie une sous-tâche à un autre agent",
};

/** Badge Lecture / Écriture / Délégation (icône + texte : la couleur n'est jamais seule). */
function CallKindBadge({ kind }: { kind: CallKind }) {
  const Icon = KIND_ICON[kind];
  return (
    <Badge variant={KIND_VARIANT[kind]} title={KIND_TITLE[kind]}>
      <Icon aria-hidden />
      {CALL_KIND_LABEL[kind]}
    </Badge>
  );
}

/**
 * Validation humaine des actions d'un agent : une carte par appel, chacune avec son « Autoriser » /
 * « Refuser » (jamais de « tout autoriser »). Un seul appel : la décision part directement.
 * Plusieurs : on décide de chacun, puis on envoie.
 */
export function ApprovalCard({ part, disabled, onSubmit }: ApprovalCardProps) {
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const single = part.calls.length === 1;
  const decided = part.submitted ? part.decisions : decisions;
  const count = part.calls.filter((c) => decided[c.id] !== undefined).length;
  const complete = count === part.calls.length;

  const choose = (id: string, value: boolean) => {
    if (single) {
      onSubmit({ [id]: value });
      return;
    }
    setDecisions((d) => ({ ...d, [id]: value }));
  };

  return (
    <section
      aria-label={single ? "Action à valider" : "Actions à valider"}
      className={cn(
        "rounded-lg border p-3",
        part.submitted ? "border-atelier-border bg-card shadow-glow" : "border-warning/50 bg-warning/8",
      )}
    >
      <header className="mb-2 flex items-center gap-2 text-sm font-medium">
        <ShieldQuestion className="size-4 text-warning" aria-hidden />
        {part.submitted
          ? "Votre décision"
          : single
            ? "L'agent veut effectuer cette action"
            : `L'agent veut effectuer ${part.calls.length} actions : décidez de chacune`}
      </header>
      <ul className="flex flex-col gap-2">
        {part.calls.map((call) => (
          <CallCard
            key={call.id}
            call={call}
            choice={decided[call.id]}
            submitted={part.submitted}
            single={single}
            disabled={disabled}
            onChoose={(value) => choose(call.id, value)}
          />
        ))}
      </ul>
      {!single && !part.submitted && (
        <div className="mt-2 flex items-center justify-end gap-2">
          <span className="text-xs text-muted-foreground" aria-live="polite">
            {count} / {part.calls.length} décidée{count >= 2 ? "s" : ""}
          </span>
          <Button size="sm" disabled={!complete || disabled} onClick={() => onSubmit(decisions)}>
            Envoyer mes choix
          </Button>
        </div>
      )}
    </section>
  );
}

function CallCard({
  call,
  choice,
  submitted,
  single,
  disabled,
  onChoose,
}: {
  call: PendingCall;
  choice: boolean | undefined;
  submitted: boolean;
  single: boolean;
  disabled: boolean;
  onChoose: (value: boolean) => void;
}) {
  const summaryId = useId();
  const kind = callKind(call.kind);
  return (
    <li className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-md border border-atelier-line bg-card px-3 py-2 shadow-glow sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        <p className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <CallKindBadge kind={kind} />
          <span className="min-w-0 truncate">{toolLabel(call.name)}</span>
        </p>
        <p id={summaryId} className="text-sm break-words">
          {call.summary}
        </p>
      </div>
      {submitted ? (
        <Badge variant={choice ? "success" : "destructive"} className="justify-self-start sm:justify-self-end">
          {choice ? "Autorisée" : "Refusée"}
        </Badge>
      ) : (
        <div className="flex gap-1.5 justify-self-end">
          <Button
            type="button"
            size="sm"
            variant={choice === false ? "secondary" : "outline"}
            disabled={disabled}
            aria-pressed={single ? undefined : choice === false}
            aria-describedby={summaryId}
            onClick={() => onChoose(false)}
          >
            <X />
            Refuser
          </Button>
          <Button
            type="button"
            size="sm"
            variant={choice === true || single ? "default" : "outline"}
            disabled={disabled}
            aria-pressed={single ? undefined : choice === true}
            aria-describedby={summaryId}
            onClick={() => onChoose(true)}
          >
            <Check />
            Autoriser
          </Button>
        </div>
      )}
    </li>
  );
}
