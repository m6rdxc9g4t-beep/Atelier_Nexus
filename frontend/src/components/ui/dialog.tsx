"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { type VariantProps, cva } from "class-variance-authority";
import { XIcon } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;

/** Largeurs des fenêtres (une échelle fermée plutôt que des max-w au cas par cas). */
const dialogSize = cva("", {
  variants: {
    size: {
      sm: "max-w-md",
      md: "max-w-xl",
      lg: "max-w-3xl",
      xl: "max-w-6xl",
    },
  },
});

/**
 * Défilement : `content` (défaut) fait défiler toute la fenêtre ; `body` garde l'en-tête
 * (DialogHeader) et le pied (DialogFooter) en place, en bandeaux séparés par un trait, et ne fait
 * défiler que DialogBody (long formulaire : « Enregistrer » toujours visible).
 */
const dialogScroll = cva("", {
  variants: {
    scroll: {
      content: "",
      body: "flex flex-col gap-0 overflow-hidden p-0",
    },
  },
});

function DialogContent({
  className,
  children,
  size,
  scroll,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> &
  VariantProps<typeof dialogSize> &
  VariantProps<typeof dialogScroll>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/70 backdrop-blur-[3px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        data-scroll={scroll ?? "content"}
        className={cn(
          "group/dialog fixed top-1/2 left-1/2 z-50 grid max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-2xl border border-atelier-border bg-card p-6 shadow-glow-strong data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
          dialogSize({ size }),
          dialogScroll({ scroll }),
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="absolute top-4 right-4 grid size-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring">
          <XIcon className="size-4" />
          <span className="sr-only">Fermer</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/** En-tête ; dans une fenêtre `scroll="body"`, bandeau fixe au-dessus du contenu qui défile. */
function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn(
        "flex flex-col gap-1.5 pr-6",
        "group-data-[scroll=body]/dialog:shrink-0 group-data-[scroll=body]/dialog:border-b group-data-[scroll=body]/dialog:border-atelier-line group-data-[scroll=body]/dialog:px-6 group-data-[scroll=body]/dialog:pt-5 group-data-[scroll=body]/dialog:pr-12 group-data-[scroll=body]/dialog:pb-4",
        className,
      )}
      {...props}
    />
  );
}

/** Contenu qui défile d'une fenêtre `scroll="body"`, entre l'en-tête et le pied. */
function DialogBody({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-body"
      className={cn("grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-4 overflow-y-auto px-6 py-5", className)}
      {...props}
    />
  );
}

/** Pied ; dans une fenêtre `scroll="body"`, bandeau fixe sous le contenu qui défile. */
function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        "group-data-[scroll=body]/dialog:shrink-0 group-data-[scroll=body]/dialog:border-t group-data-[scroll=body]/dialog:border-atelier-line group-data-[scroll=body]/dialog:px-6 group-data-[scroll=body]/dialog:py-3",
        className,
      )}
      {...props}
    />
  );
}

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title className={cn("text-lg font-semibold tracking-tight", className)} {...props} />
  );
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
};
