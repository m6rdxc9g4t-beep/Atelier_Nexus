"use client";

import { Check, X } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { DecisionCard, DecisionDetails, DecisionRow } from "@/components/ui/decision-card";
import type { PendingApproval, StepRun } from "@/types/api";

import { parseUses } from "./catalog";
import { STEP_STATUS_LABEL, resultExcerpt } from "./run";
import { AppTile, KindBadge, StepStatusIcon } from "./StepBadges";

/**
 * Carte de validation d'une étape (lecture, écriture ou action destructive), dans l'anatomie
 * commune des décisions (components/ui/decision-card) : résultat de l'étape précédente juste
 * au-dessus, résumé, nature et application, entrée résolue (valeurs réelles) dans « Détails »,
 * Refuser puis Autoriser. Aucun bouton ne prend le focus tout seul.
 * Partagée par le suivi d'exécution de l'éditeur et la boîte « À valider ».
 */
export function ApprovalCard({
  pending,
  label,
  app,
  previous,
  busy,
  stacked = false,
  onDecide,
}: {
  pending: PendingApproval;
  label: string;
  /** Application de l'étape d'après le catalogue (un outil appartient à sa boîte) ; sinon lue dans `uses` */
  app?: string | null;
  /** Dernière étape exécutée avant celle-ci, et son libellé */
  previous?: { step: StepRun; label: string } | null;
  busy: boolean;
  /** Panneau étroit (inspecteur) : boutons sous le résumé plutôt qu'à côté */
  stacked?: boolean;
  onDecide: (pending: PendingApproval, allow: boolean) => void;
}) {
  const summaryId = useId();
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
      {previous && <PreviousResult step={previous.step} label={previous.label} />}
      <DecisionCard aria-label="Étape à valider">
        <DecisionRow
          summary={pending.summary}
          summaryId={summaryId}
          className={stacked ? "sm:grid-cols-[minmax(0,1fr)]" : undefined}
          meta={
            <>
              <KindBadge kind={pending.kind} />
              <AppTile app={app === undefined ? parseUses(pending.uses).app : app} size="xs" className="size-5! [&_svg]:size-3!" />
              <span className="min-w-0 truncate">{label}</span>
              <span aria-hidden>·</span>
              <span>
                étape <code className="font-mono">{pending.step_id}</code>
              </span>
            </>
          }
          details={<DecisionDetails label="Détails : entrée résolue (valeurs réelles)">{JSON.stringify(pending.input, null, 2)}</DecisionDetails>}
          actions={
            <>
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
            </>
          }
        />
      </DecisionCard>
    </div>
  );
}

/** Résultat de l'étape précédente, pour juger avant d'autoriser la suivante. */
function PreviousResult({ step, label }: { step: StepRun; label: string }) {
  const excerpt = resultExcerpt(step);
  return (
    <section aria-label="Résultat de l'étape précédente" className="rounded-xl border border-atelier-line bg-sunken px-3 py-2 text-xs">
      <p className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
        <StepStatusIcon status={step.status} />
        <span className="min-w-0 truncate">
          Étape précédente · <span className="text-foreground">{label}</span> ({STEP_STATUS_LABEL[step.status]})
        </span>
      </p>
      {excerpt && (
        <pre className="mt-1.5 max-h-32 overflow-auto rounded-md border border-atelier-line bg-card p-2 font-mono text-xs leading-snug whitespace-pre-wrap">
          {excerpt}
        </pre>
      )}
    </section>
  );
}
