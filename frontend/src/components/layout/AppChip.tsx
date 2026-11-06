import { appTheme } from "@/features/workflows-graph/catalog";
import { cn } from "@/lib/utils";

import { AppIcon, appShort } from "./appIcons";

/**
 * Puce d'une application de la suite (accueil, fiches d'agents, outils, modèles de workflows).
 * Charte v2 : puce neutre ; seule la petite icône carrée est dans la couleur signature de SON
 * application (`data-atelier-app` recalcule la signature dans l'icône).
 */
export function AppChip({
  app,
  color,
  label,
  className,
  iconOnly = false,
}: {
  app: string;
  /** Couleur reçue du backend pour une application que la marque ne connaît pas */
  color?: string | null;
  label?: string;
  className?: string;
  iconOnly?: boolean;
}) {
  const text = label ?? appShort(app);
  const icon = (
    <span
      {...appTheme(app, color)}
      aria-hidden
      className={cn(
        "atelier-brand__tile shrink-0 [&_svg]:stroke-[2.2]",
        iconOnly ? "size-5 rounded-sm [&_svg]:size-3" : "size-3.5 rounded-[3.5px] [&_svg]:size-[9px]",
      )}
    >
      <AppIcon app={app} />
    </span>
  );
  if (iconOnly)
    return (
      <span title={text} className={cn("inline-flex shrink-0", className)}>
        {icon}
        <span className="sr-only">{text}</span>
      </span>
    );
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1.5 rounded-sm border border-atelier-line pr-1.5 pl-[3px] text-xs font-medium text-muted-foreground",
        className,
      )}
    >
      {icon}
      {text}
    </span>
  );
}
