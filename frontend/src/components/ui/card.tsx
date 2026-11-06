import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Carte de la charte v2 : surface, trait de 1 px, plate au repos (jamais d'ombre ni de halo).
 * `interactive` : le trait s'appuie au survol ; `highlight` : trait appuyé (ce qui demande l'attention).
 */
const cardVariants = cva("flex flex-col rounded-lg border bg-card text-card-foreground", {
  variants: {
    variant: {
      default: "border-atelier-border",
      interactive:
        "border-atelier-border transition-[border-color,background-color] hover:border-atelier-border-soft focus-within:border-atelier-border-soft",
      highlight: "border-atelier-border-soft",
      sunken: "border-atelier-line bg-sunken",
    },
  },
  defaultVariants: { variant: "default" },
});

function Card({ className, variant, ...props }: React.ComponentProps<"div"> & VariantProps<typeof cardVariants>) {
  return <div data-slot="card" className={cn(cardVariants({ variant }), className)} {...props} />;
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-header" className={cn("flex flex-col gap-1 px-4 pt-3.5", className)} {...props} />;
}

function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return <h3 data-slot="card-title" className={cn("text-sm font-semibold leading-snug", className)} {...props} />;
}

function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return <p data-slot="card-description" className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn("px-4 py-3", className)} {...props} />;
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center gap-2 border-t border-atelier-line px-4 py-2.5", className)}
      {...props}
    />
  );
}

export { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, cardVariants };
