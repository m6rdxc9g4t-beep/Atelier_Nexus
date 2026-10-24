import type * as React from "react";

import { cn } from "@/lib/utils";

export type DotStatus = "up" | "down" | "off" | "pending" | "warning";

const DOT: Record<DotStatus, string> = {
  up: "bg-success",
  down: "bg-destructive",
  off: "bg-muted-foreground/40",
  pending: "animate-pulse bg-muted-foreground/60",
  warning: "bg-warning",
};

/**
 * Pastille d'état. La couleur n'est jamais seule porteuse de sens : passer `label` (affiché) ou
 * donner le sens par le texte voisin.
 */
function StatusDot({
  status,
  label,
  className,
  ...props
}: React.ComponentProps<"span"> & { status: DotStatus; label?: string }) {
  return (
    <span data-slot="status-dot" className={cn("inline-flex items-center gap-1.5", className)} {...props}>
      <span className="relative inline-flex size-2 shrink-0" aria-hidden>
        {status === "up" && <span className="absolute inset-0 rounded-full bg-success/40 motion-safe:animate-ping [animation-duration:2.4s]" />}
        <span className={cn("relative inline-flex size-2 rounded-full", DOT[status])} />
      </span>
      {label && <span className="text-[11px] text-muted-foreground">{label}</span>}
    </span>
  );
}

export { StatusDot };
