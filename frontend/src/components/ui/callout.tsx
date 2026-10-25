import { type VariantProps, cva } from "class-variance-authority";
import { CircleAlert, CircleCheck, Info, type LucideIcon, TriangleAlert } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Message encadré (information, avertissement, erreur, succès) : icône + texte + action
 * facultative. Remplace les paragraphes colorés faits à la main ; texte en encre lisible.
 */
const calloutVariants = cva("flex items-start gap-2.5 rounded-xl border px-3 py-2.5 text-[13px] leading-snug", {
  variants: {
    tone: {
      info: "border-atelier-line bg-card text-muted-foreground [&_[data-icon]]:text-muted-foreground",
      signature: "border-atelier-border-soft bg-signature-faint text-foreground [&_[data-icon]]:text-accent-ink",
      warning: "border-warning/30 bg-warning/8 text-warning-ink [&_[data-icon]]:text-warning",
      destructive: "border-destructive/30 bg-destructive/8 text-destructive-ink [&_[data-icon]]:text-destructive",
      success: "border-success/30 bg-success/8 text-success-ink [&_[data-icon]]:text-success",
    },
  },
  defaultVariants: { tone: "info" },
});

const ICONS: Record<NonNullable<VariantProps<typeof calloutVariants>["tone"]>, LucideIcon> = {
  info: Info,
  signature: Info,
  warning: TriangleAlert,
  destructive: CircleAlert,
  success: CircleCheck,
};

function Callout({
  tone,
  icon,
  title,
  action,
  className,
  children,
  ...props
}: Omit<React.ComponentProps<"div">, "title"> &
  VariantProps<typeof calloutVariants> & {
    icon?: LucideIcon;
    title?: React.ReactNode;
    action?: React.ReactNode;
  }) {
  const Icon = icon ?? ICONS[tone ?? "info"];
  return (
    <div data-slot="callout" className={cn(calloutVariants({ tone }), className)} {...props}>
      <Icon data-icon className="mt-px size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cn(title ? "mt-0.5" : undefined)}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

export { Callout, calloutVariants };
