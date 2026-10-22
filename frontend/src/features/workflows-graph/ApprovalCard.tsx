"use client";

import { Check, ShieldQuestion, X } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import type { PendingApproval, StepRun } from "@/types/api";

import { STEP_STATUS_LABEL, resultExcerpt } from "./run";
import { KindBadge, StepStatusIcon } from "./StepBadges";

/**
 * Carte de validation d'une étape (lecture, écriture ou action destructive) : résultat de l'étape
 * précédente juste au-dessus, résumé, entrée résolue (valeurs réelles), Autoriser / Refuser.
 * Partagée par le suivi d'exécution de l'éditeur et la boîte « À valider ».
 */
export function ApprovalCard({
  pending,
  label,
  previous,
  busy,
  onDecide,
}: {
  pending: PendingApproval;
  label: string;
  /** Dernière étape exécutée avant celle-ci, et son libellé */
  previous?: { step: StepRun; label: string } | null;
  busy: boolean;
  onDecide: (pending: PendingApproval, allow: boolean) => void;
}) {
  const summaryId = useId();
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
      {previous && <PreviousResult step={previous.step} label={previous.label} />}
      <section
        aria-label="Étape à valider"
        className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-lg border border-warning/50 bg-warning/8 p-3"
      >
        <header className="flex items-center gap-2 text-sm font-medium">
          <ShieldQuestion className="size-4 shrink-0 text-warning" aria-hidden />
          <span id={summaryId} className="min-w-0 flex-1 break-words">
            {pending.summary}
          </span>
          <KindBadge kind={pending.kind} />
        </header>
        <p className="text-xs text-muted-foreground">
          Étape <code className="font-mono">{pending.step_id}</code> · {label}
        </p>
        <details className="rounded-md border border-atelier-line bg-card">
          <summary className="cursor-pointer px-2 py-1 text-xs text-muted-foreground">Entrée résolue (valeurs réelles)</summary>
          <pre className="max-h-48 overflow-auto border-t border-atelier-line p-2 font-mono text-[11px] whitespace-pre-wrap">
            {JSON.stringify(pending.input, null, 2)}
          </pre>
        </details>
        <div className="flex justify-end gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            aria-describedby={summaryId}
            onClick={() => onDecide(pending, false)}
          >
            <X />
            Refuser
          </Button>
          <Button type="button" size="sm" disabled={busy} aria-describedby={summaryId} onClick={() => onDecide(pending, true)}>
            <Check />
            Autoriser
          </Button>
        </div>
      </section>
    </div>
  );
}

/** Résultat de l'étape précédente, pour juger avant d'autoriser la suivante. */
function PreviousResult({ step, label }: { step: StepRun; label: string }) {
  const excerpt = resultExcerpt(step);
  return (
    <section aria-label="Résultat de l'étape précédente" className="rounded-md border border-atelier-border-soft bg-sunken px-2.5 py-2 text-xs">
      <p className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
        <StepStatusIcon status={step.status} />
        <span className="min-w-0 truncate">
          Étape précédente · <span className="text-foreground">{label}</span> ({STEP_STATUS_LABEL[step.status]})
        </span>
      </p>
      {excerpt && (
        <pre className="mt-1 max-h-32 overflow-auto rounded-sm border border-atelier-line bg-card p-1.5 font-mono text-[11px] whitespace-pre-wrap">
          {excerpt}
        </pre>
      )}
    </section>
  );
}
