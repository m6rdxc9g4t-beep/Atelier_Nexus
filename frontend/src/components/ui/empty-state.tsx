import type { LucideIcon } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

/** État vide : icône dans une tuile, titre, explication et actions. */
function EmptyState({
  icon: Icon,
  title,
  children,
  actions,
  className,
}: {
  icon: LucideIcon;
  title: string;
  children?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-3 px-6 py-10 text-center", className)}>
      <span className="grid size-11 place-items-center rounded-xl border border-atelier-border-soft bg-signature-faint text-accent-ink">
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="max-w-sm">
        <p className="text-base font-semibold">{title}</p>
        {children && <div className="mt-1 text-sm text-muted-foreground">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

export { EmptyState };
