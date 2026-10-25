import { ShieldQuestion } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Anatomie unique d'une validation humaine (conversation, éditeur de workflows, « À valider ») :
 * surtitre « Votre accord est nécessaire », puis une ligne par action (résumé, nature, détails
 * repliés, Refuser / Autoriser). Purement présentationnel : aucune décision n'est prise ici, et
 * aucun bouton ne reçoit le focus tout seul.
 */
function DecisionCard({
  heading = "Votre accord est nécessaire",
  submitted = false,
  footer,
  className,
  children,
  ...props
}: React.ComponentProps<"section"> & {
  heading?: React.ReactNode;
  /** Décision déjà envoyée : carte apaisée (reçu) */
  submitted?: boolean;
  footer?: React.ReactNode;
}) {
  return (
    <section
      data-slot="decision-card"
      className={cn(
        "overflow-hidden rounded-xl border bg-card",
        submitted ? "border-atelier-line" : "decision-card border-atelier-border",
        className,
      )}
      {...props}
    >
      <header
        className={cn(
          "flex items-center gap-2 px-3.5 pt-3 pb-1 text-xs font-semibold",
          submitted ? "text-muted-foreground" : "text-warning-ink",
        )}
      >
        <ShieldQuestion className={cn("size-4 shrink-0", !submitted && "text-warning")} aria-hidden />
        {heading}
      </header>
      <ul className="flex flex-col divide-y divide-atelier-line">{children}</ul>
      {footer && <div className="flex items-center justify-end gap-2 border-t border-atelier-line px-3.5 py-2.5">{footer}</div>}
    </section>
  );
}

/** Une action à décider : résumé (information principale), ligne de nature, détails, boutons. */
function DecisionRow({
  summary,
  summaryId,
  meta,
  details,
  actions,
  className,
}: {
  summary: React.ReactNode;
  /** id du résumé, cité par aria-describedby des boutons */
  summaryId?: string;
  meta?: React.ReactNode;
  details?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <li className={cn("grid grid-cols-[minmax(0,1fr)] gap-2 px-3.5 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start", className)}>
      <div className="min-w-0">
        <p id={summaryId} className="text-sm font-medium break-words">
          {summary}
        </p>
        {meta && <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">{meta}</div>}
        {details && <div className="mt-2">{details}</div>}
      </div>
      {actions && <div className="flex gap-1.5 justify-self-end">{actions}</div>}
    </li>
  );
}

/** Détails repliés (paramètres, entrée résolue) : JSON creusé, défilement interne. */
function DecisionDetails({ label, children }: { label: string; children: string }) {
  return (
    <details className="group rounded-lg border border-atelier-line bg-sunken">
      <summary className="cursor-pointer px-2.5 py-1.5 text-xs text-muted-foreground select-none hover:text-foreground">
        {label}
      </summary>
      <pre className="max-h-56 overflow-auto border-t border-atelier-line p-2.5 font-mono text-xs leading-snug whitespace-pre-wrap">
        {children}
      </pre>
    </details>
  );
}

export { DecisionCard, DecisionDetails, DecisionRow };
