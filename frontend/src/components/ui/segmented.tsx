"use client";

import type * as React from "react";

import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string> {
  value: T;
  label: React.ReactNode;
  /** Nom accessible quand le libellé est une icône */
  ariaLabel?: string;
}

/** Rail du contrôle segmenté (DESIGN.md « Contrôles compacts ») : fond de survol, 2 px de marge. */
export const segmentedRail = "inline-flex w-fit items-center gap-0.5 rounded-md bg-atelier-hover p-0.5";

/** Option : 24 px, Label-sm atténué ; pressée (`aria-pressed`) = surface + micro-ombre, encre. */
export const segmentedItem = cn(
  "inline-flex h-6 items-center justify-center gap-1.5 rounded-sm px-2 text-xs font-medium whitespace-nowrap text-atelier-muted transition-colors [&_svg]:size-3.5 [&_svg]:shrink-0",
  "hover:text-foreground",
  "aria-pressed:bg-atelier-surface aria-pressed:text-foreground aria-pressed:shadow-[0_1px_2px_rgb(0_0_0/0.08),0_0_0_1px_var(--atelier-line)]",
);

/**
 * Choix exclusif compact (filtres, portée, vue) : groupe de boutons `aria-pressed`, même style que
 * le sélecteur de thème.
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
    <div role="group" aria-label={label} className={cn(segmentedRail, className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          aria-label={o.ariaLabel}
          onClick={() => onChange(o.value)}
          className={cn(segmentedItem, size === "sm" ? "px-2.5" : "h-[22px] px-2 text-[11.5px]")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export { Segmented };
