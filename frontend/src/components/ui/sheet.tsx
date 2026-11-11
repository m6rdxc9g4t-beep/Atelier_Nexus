"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { type VariantProps, cva } from "class-variance-authority";
import { XIcon } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

import { useFocusReturn } from "./focus-return";

const Sheet = DialogPrimitive.Root;
const SheetTitle = DialogPrimitive.Title;
const SheetDescription = DialogPrimitive.Description;

/** Côté d'arrivée du tiroir : gauche (navigation, par défaut) ou droite (panneau Livrables). */
const sheetSide = cva(
  "fixed inset-y-0 z-50 flex flex-col shadow-glow-strong outline-none data-[state=open]:animate-in data-[state=open]:duration-200",
  {
    variants: {
      side: {
        left: "left-0 w-[min(18rem,calc(100vw-3rem))] border-r border-atelier-line bg-sidebar data-[state=open]:slide-in-from-left",
        right: "right-0 w-full border-l border-atelier-line bg-card sm:w-[32rem] data-[state=open]:slide-in-from-right",
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
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & VariantProps<typeof sheetSide> & { closeButton?: boolean }) {
  // Tiroir ouvert par un store (navigation, livrables) : le focus revient à l'élément d'origine
  const focusReturn = useFocusReturn({ onOpenAutoFocus, onCloseAutoFocus });
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[rgb(11_18_32/0.45)] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <DialogPrimitive.Content
        data-slot="sheet-content"
        data-side={side ?? "left"}
        className={cn(sheetSide({ side }), className)}
        {...props}
        {...focusReturn}
      >
        {children}
        {closeButton && (
          <DialogPrimitive.Close className="absolute top-2 right-2 grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <XIcon className="size-4" />
            <span className="sr-only">Fermer</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export { Sheet, SheetContent, SheetDescription, SheetTitle };
