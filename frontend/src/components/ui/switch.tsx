import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Interrupteur (rôle `switch`), habillé comme les champs Shadcn : trait doux, activé = signature.
 * Espace ou Entrée le basculent (bouton natif).
 */
function Switch({
  checked,
  onCheckedChange,
  className,
  ...props
}: Omit<React.ComponentProps<"button">, "onChange" | "role"> & {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  const state = checked ? "checked" : "unchecked";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      data-slot="switch"
      data-state={state}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-input bg-atelier-field outline-none transition-colors focus-visible:border-primary focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-primary data-[state=checked]:bg-primary",
        className,
      )}
      {...props}
    >
      <span
        aria-hidden
        data-state={state}
        className="pointer-events-none block size-3.5 translate-x-0.5 rounded-full bg-muted-foreground shadow-sm transition-transform data-[state=checked]:translate-x-[1.05rem] data-[state=checked]:bg-primary-foreground"
      />
    </button>
  );
}

export { Switch };
