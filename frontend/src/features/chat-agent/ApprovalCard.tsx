"use client";

import { Check, Eye, PenLine, Users, X } from "lucide-react";
import { useId, useState } from "react";

import { AppChip } from "@/components/layout/AppChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DecisionCard, DecisionDetails, DecisionRow } from "@/components/ui/decision-card";
import { CALL_KIND_LABEL, callKind } from "@/lib/approval";
import type { CallKind, PendingCall } from "@/types/api";

import { toolApp } from "./agentApps";
import type { ApprovalPart } from "./conversation";
import { formatParams } from "./thread";
import { actionLabel } from "./ToolActivity";

interface ApprovalCardProps {
  /** Validation en attente (une fois envoyée, elle rejoint la ligne d'activité du tour) */
  part: ApprovalPart;
  disabled: boolean;
  onSubmit: (decisions: Record<string, boolean>) => void;
  agentLabel: (name: string) => string;
  /** Élément de la carte, suivi par le dock de décision (visibilité, « Voir ») */
  anchorRef?: (el: HTMLElement | null) => void;
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
 * Validation humaine des actions d'un agent : une ligne par appel (résumé, nature, application,
 * paramètres dans « Détails »), chacune avec son « Refuser » / « Autoriser » — jamais de « tout
 * autoriser », jamais de focus automatique. Un seul appel : la décision part directement.
 * Plusieurs : on décide de chacun, puis « Envoyer mes choix ». Le titre reçoit le focus quand le
 * dock de décision y ramène (« Voir »).
 */
export function ApprovalCard({ part, disabled, onSubmit, agentLabel, anchorRef }: ApprovalCardProps) {
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const titleId = useId();
  const total = part.calls.length;
  const single = total === 1;
  const count = part.calls.filter((c) => decisions[c.id] !== undefined).length;
  const complete = count === total;

  const choose = (id: string, value: boolean) => {
    if (single) {
      onSubmit({ [id]: value });
      return;
    }
    setDecisions((d) => ({ ...d, [id]: value }));
  };

  return (
    <DecisionCard
      ref={anchorRef}
      aria-label={single ? "Action à valider" : "Actions à valider"}
      heading={
        <span id={titleId} data-decision-title tabIndex={-1} className="rounded-sm">
          Votre accord est nécessaire
          {!single && <span className="font-normal text-muted-foreground"> · {total} actions, décidez de chacune</span>}
        </span>
      }
      footer={
        single ? undefined : (
          <>
            <span className="mr-auto text-xs text-muted-foreground" aria-live="polite">
              {count} / {total} décidée{count >= 2 ? "s" : ""}
            </span>
            <Button size="sm" disabled={!complete || disabled} onClick={() => onSubmit(decisions)}>
              Envoyer mes choix
            </Button>
          </>
        )
      }
    >
      {part.calls.map((call) => (
        <CallRow
          key={call.id}
          call={call}
          label={actionLabel(call, agentLabel)}
          choice={decisions[call.id]}
          single={single}
          disabled={disabled}
          onChoose={(value) => choose(call.id, value)}
        />
      ))}
    </DecisionCard>
  );
}

function CallRow({
  call,
  label,
  choice,
  single,
  disabled,
  onChoose,
}: {
  call: PendingCall;
  label: string;
  choice: boolean | undefined;
  single: boolean;
  disabled: boolean;
  onChoose: (value: boolean) => void;
}) {
  const summaryId = useId();
  const app = toolApp(call.name);
  return (
    <DecisionRow
      summary={call.summary}
      summaryId={summaryId}
      meta={
        <>
          <CallKindBadge kind={callKind(call.kind)} />
          {app && <AppChip app={app} />}
          <span className="min-w-0 truncate">{label}</span>
        </>
      }
      details={<DecisionDetails label="Détails">{formatParams(call.input)}</DecisionDetails>}
      actions={
        <>
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
        </>
      }
    />
  );
}
