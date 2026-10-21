"use client";

import { Check, ShieldQuestion, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PendingApproval } from "@/types/api";

import { KindBadge } from "./StepBadges";

/**
 * Carte de validation d'une écriture : résumé, entrée résolue (valeurs réelles), Autoriser / Refuser.
 * Partagée par le suivi d'exécution de l'éditeur et la boîte « À valider ».
 */
export function ApprovalCard({
  pending,
  label,
  busy,
  onDecide,
}: {
  pending: PendingApproval;
  label: string;
  busy: boolean;
  onDecide: (pending: PendingApproval, allow: boolean) => void;
}) {
  return (
    <section aria-label="Action à valider" className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-lg border border-warning/50 bg-warning/8 p-3">
      <header className="flex items-center gap-2 text-sm font-medium">
        <ShieldQuestion className="size-4 shrink-0 text-warning" aria-hidden />
        <span className="min-w-0 flex-1">{pending.summary}</span>
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
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onDecide(pending, false)}>
          <X />
          Refuser
        </Button>
        <Button type="button" size="sm" disabled={busy} onClick={() => onDecide(pending, true)}>
          <Check />
          Autoriser
        </Button>
      </div>
    </section>
  );
}
