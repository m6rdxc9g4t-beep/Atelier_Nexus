import type * as React from "react";

import { cn } from "@/lib/utils";

export type DotStatus = "up" | "down" | "off" | "pending" | "warning";

// Pastilles d'état (DESIGN.md « État d'un service ») : vert pour le seul résumé global, rouge et
// ambre quand ça ne va pas, cercle vide pour « vérification », gris pour « non configurée ».
const DOT: Record<DotStatus, string> = {
  up: "bg-success",
  down: "bg-destructive",
  off: "bg-atelier-faint/45",
  pending: "bg-transparent shadow-[inset_0_0_0_1.5px_var(--atelier-faint)]",
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
        <span className={cn("relative inline-flex size-2 rounded-full", DOT[status])} />
      </span>
      {label && <span className="text-[11px] text-muted-foreground">{label}</span>}
    </span>
  );
}

export { StatusDot };
