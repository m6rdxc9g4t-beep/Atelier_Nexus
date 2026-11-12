import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Précision d'une ligne (identifiant technique, format…), montrée au survol ou au focus de
 * l'élément `group/hint` qui la contient. Elle se pose sous son ancêtre `relative` et ne dépasse
 * jamais sa largeur : contrairement à une info-bulle du navigateur (`title`), elle ne recouvre
 * pas la colonne voisine. Reliée par `aria-describedby` au contrôle de la ligne quand il y en a un.
 */
function Hint({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      role="tooltip"
      data-slot="hint"
      className={cn(
        "pointer-events-none invisible absolute top-full left-0 z-20 mt-0.5 grid w-max max-w-full gap-0.5 rounded-md border border-atelier-border-soft bg-popover px-2 py-1 text-left text-xs leading-snug font-normal break-words whitespace-normal text-popover-foreground opacity-0 shadow-glow-strong transition-opacity delay-300",
        "group-hover/hint:visible group-hover/hint:opacity-100 group-focus-within/hint:visible group-focus-within/hint:opacity-100",
        className,
      )}
      {...props}
    />
  );
}

export { Hint };
