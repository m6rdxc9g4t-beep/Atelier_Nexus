import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex h-5 w-fit shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 text-xs font-medium tabular-nums [&>svg]:size-3",
  {
    variants: {
      variant: {
        // Charte v2 : étiquettes neutres ; seuls les états anormaux sont en couleur
        default: "border-atelier-line bg-atelier-hover text-muted-foreground",
        signature: "border-atelier-line bg-atelier-hover text-muted-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-atelier-border-soft text-muted-foreground",
        // Succès : neutre (un état nominal ne se colore pas), l'icône ou le texte portent le sens
        success: "border-atelier-line text-muted-foreground",
        // Texte en encre lisible, fond et trait en transparence
        destructive: "border-destructive-ink/30 bg-destructive-ink/8 text-destructive-ink",
        warning: "border-warning-ink/30 bg-warning-ink/8 text-warning-ink",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
