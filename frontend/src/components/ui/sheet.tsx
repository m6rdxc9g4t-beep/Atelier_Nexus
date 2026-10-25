"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { type VariantProps, cva } from "class-variance-authority";
import { XIcon } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

const Sheet = DialogPrimitive.Root;
const SheetTitle = DialogPrimitive.Title;
const SheetDescription = DialogPrimitive.Description;

/** Côté d'arrivée du tiroir : gauche (navigation, par défaut) ou droite (panneau Livrables). */
const sheetSide = cva(
  "fixed inset-y-0 z-50 flex flex-col shadow-glow-strong outline-none data-[state=open]:animate-in",
  {
    variants: {
      side: {
        left: "left-0 w-[min(20rem,calc(100vw-3rem))] border-r border-atelier-border bg-sidebar data-[state=open]:slide-in-from-left",
        right: "right-0 w-full border-l border-atelier-border bg-card sm:w-[32rem] data-[state=open]:slide-in-from-right",
      },
    },
    defaultVariants: { side: "left" },
  },
);

/**
 * Tiroir latéral modal (voile, Échap, focus piégé), sur la même base que les fenêtres.
 * `closeButton={false}` : l'appelant place lui-même son bouton de fermeture (en-tête du panneau).
 */
function SheetContent({
  className,
  children,
  side,
  closeButton = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & VariantProps<typeof sheetSide> & { closeButton?: boolean }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/70 backdrop-blur-[3px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <DialogPrimitive.Content
        data-slot="sheet-content"
        data-side={side ?? "left"}
        className={cn(sheetSide({ side }), className)}
        {...props}
      >
        {children}
        {closeButton && (
          <DialogPrimitive.Close className="absolute top-3 right-3 grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring">
            <XIcon className="size-4" />
            <span className="sr-only">Fermer</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export { Sheet, SheetContent, SheetDescription, SheetTitle };
