import { ChevronDown } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

/** Liste déroulante native, habillée comme les champs Shadcn (accessible et légère). */
function NativeSelect({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <div className={cn("relative inline-flex", className)}>
      <select
        data-slot="native-select"
        className="h-8 w-full appearance-none rounded-md border border-input bg-atelier-field py-1 pr-8 pl-2.5 text-sm outline-none transition-colors focus-visible:border-primary focus-visible:shadow-focus disabled:opacity-50"
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
    </div>
  );
}

export { NativeSelect };
