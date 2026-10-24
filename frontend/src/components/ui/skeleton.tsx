import type * as React from "react";

import { cn } from "@/lib/utils";

/** Bloc de chargement : garde la place du contenu attendu (la mise en page ne saute pas). */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="skeleton" aria-hidden className={cn("animate-pulse rounded-md bg-signature-faint", className)} {...props} />
  );
}

export { Skeleton };
