import type * as React from "react";

import { cn } from "@/lib/utils";

/** Petite étiquette de section (barres latérales, groupes de l'accueil). */
function SectionLabel({ className, as: Tag = "h2", ...props }: React.ComponentProps<"h2"> & { as?: "h2" | "h3" | "p" }) {
  return (
    <Tag
      data-slot="section-label"
      className={cn("text-[11px] font-semibold tracking-[0.08em] text-atelier-muted uppercase", className)}
      {...props}
    />
  );
}

export { SectionLabel };
