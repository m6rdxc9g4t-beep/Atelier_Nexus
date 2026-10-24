import type * as React from "react";

import { cn } from "@/lib/utils";

/** Touche du clavier (raccourcis, aide du composer). */
function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] border border-atelier-border-soft bg-atelier-surface-2 px-1 font-sans text-[10.5px] font-medium leading-none text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { Kbd };
