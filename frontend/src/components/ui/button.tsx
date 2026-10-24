import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        // Charte néon : plein en clair ; contour néon en sombre (fond en transparence, texte lumineux)
        default:
          "border border-primary bg-primary text-primary-foreground shadow-signature-glow hover:bg-primary/90 dark:bg-signature-soft dark:text-accent-ink dark:hover:bg-primary/30",
        destructive: "bg-destructive text-white hover:bg-destructive/90",
        outline: "border border-input bg-card hover:border-atelier-border hover:bg-accent",
        secondary: "bg-secondary text-secondary-foreground hover:bg-atelier-surface-3",
        // Action secondaire mise en avant : signature en transparence, sans trait
        soft: "bg-signature-faint text-accent-ink hover:bg-signature-soft",
        ghost: "text-muted-foreground hover:bg-accent hover:text-foreground",
        link: "text-accent-ink underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 gap-1.5 px-3",
        lg: "h-10 px-6",
        icon: "size-9",
        "icon-sm": "size-8",
        "icon-xs": "size-7 rounded-md [&_svg:not([class*='size-'])]:size-3.5",
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
