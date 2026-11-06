import { type VariantProps, cva } from "class-variance-authority";
import { CircleAlert, CircleCheck, Info, type LucideIcon, TriangleAlert } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Message encadré (information, avertissement, erreur, succès) : icône + texte + action
 * facultative. Remplace les paragraphes colorés faits à la main ; texte en encre lisible.
 */
const calloutVariants = cva("flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-sm leading-snug", {
  variants: {
    tone: {
      info: "border-atelier-line bg-card text-muted-foreground [&_[data-icon]]:text-atelier-faint",
      // Charte v2 : plus de fond teinté de la signature ; information mise en avant = neutre, texte plein
      signature: "border-atelier-line bg-card text-foreground [&_[data-icon]]:text-muted-foreground",
      // États anormaux : encre lisible, fond à 9 %, trait à 30 % (DESIGN.md « Error »)
      warning: "border-warning-ink/30 bg-warning-ink/9 text-warning-ink [&_[data-icon]]:text-warning-ink",
      destructive: "border-destructive-ink/30 bg-destructive-ink/9 text-destructive-ink [&_[data-icon]]:text-destructive-ink",
      // Succès : nominal, donc neutre ; l'icône de validation porte le sens
      success: "border-atelier-line bg-card text-foreground [&_[data-icon]]:text-muted-foreground",
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
