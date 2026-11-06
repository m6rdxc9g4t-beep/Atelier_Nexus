import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-sm font-medium leading-none transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        // Charte v2 : bouton principal plein dans les deux thèmes, un seul par écran
        // Désactivé : neutre (un orange pâli se lirait comme un état)
        default:
          "border border-transparent bg-primary text-primary-foreground hover:bg-primary-hover disabled:border-atelier-line disabled:bg-atelier-hover disabled:text-atelier-faint disabled:opacity-100",
        destructive: "border border-transparent bg-atelier-down text-white hover:bg-atelier-down/90 dark:text-background",
        outline: "border border-input bg-card text-foreground hover:bg-accent active:bg-atelier-selected",
        secondary: "bg-secondary text-secondary-foreground hover:bg-atelier-selected",
        // Action secondaire : neutre, sans trait (n'entre pas en concurrence avec le principal)
        soft: "bg-atelier-hover text-foreground hover:bg-atelier-selected",
        ghost: "text-muted-foreground hover:bg-accent hover:text-foreground",
        link: "h-auto px-0 text-accent-ink underline-offset-4 hover:underline",
      },
      size: {
        default: "h-[30px] px-3",
        sm: "h-7 px-2.5",
        lg: "h-[38px] px-4 text-[14px]",
        icon: "size-[30px]",
        "icon-sm": "size-7",
        "icon-xs": "size-6 rounded-sm [&_svg:not([class*='size-'])]:size-3.5",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      data-variant={variant ?? "default"}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
