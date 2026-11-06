import type * as React from "react";

import { cn } from "@/lib/utils";

/** Touche du clavier (raccourcis, aide du composer). */
function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-xs border border-b-2 border-atelier-line bg-atelier-surface px-[5px] font-sans text-[11px] font-medium leading-none text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { Kbd };
