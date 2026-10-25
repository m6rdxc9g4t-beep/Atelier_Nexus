"use client";

import type * as React from "react";

import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> {
  value: T;
  label: React.ReactNode;
  /** Nom accessible quand le libellé est une icône */
  ariaLabel?: string;
}

/**
 * Choix exclusif compact (filtres, portée, vue) : groupe de boutons `aria-pressed`, dans le style
 * du sélecteur de thème.
 */
function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
  size = "sm",
}: {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  /** Nom accessible du groupe */
  label: string;
  className?: string;
  size?: "sm" | "xs";
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "inline-flex w-fit items-center gap-0.5 rounded-full border border-atelier-border-soft bg-atelier-surface/70 p-0.5",
        className,
      )}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
            aria-label={o.ariaLabel}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap transition-colors focus-visible:shadow-focus focus-visible:outline-none [&_svg]:size-3.5",
              size === "sm" ? "h-7 px-3 text-xs" : "h-6 px-2.5 text-[11px]",
              active ? "bg-signature-soft text-atelier-ink" : "text-atelier-muted hover:bg-signature-faint hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export { Segmented };
