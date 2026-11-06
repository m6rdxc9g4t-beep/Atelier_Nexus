import type * as React from "react";

import { cn } from "@/lib/utils";

/** Intitulé de section (Meta, casse de phrase, discret) : barres latérales, groupes de l'accueil. */
function SectionLabel({ className, as: Tag = "h2", ...props }: React.ComponentProps<"h2"> & { as?: "h2" | "h3" | "p" }) {
  return (
    <Tag
      data-slot="section-label"
      className={cn("text-[11.5px] font-medium text-atelier-faint", className)}
      {...props}
    />
  );
}

export { SectionLabel };
