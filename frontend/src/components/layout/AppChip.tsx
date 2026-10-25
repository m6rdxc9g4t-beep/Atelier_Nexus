import { appTheme } from "@/features/workflows-graph/catalog";
import { cn } from "@/lib/utils";

import { AppIcon, appShort } from "./appIcons";

/**
 * Puce d'une application de la suite, dans SA couleur signature (`data-atelier-app` recalcule les
 * jetons --atelier-* dans la puce) : accueil, fiches d'agents, outils, modèles de workflows.
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
  return (
    <span
      {...appTheme(app, color)}
      title={iconOnly ? text : undefined}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-atelier-border-soft bg-signature-faint font-medium text-atelier-ink",
        iconOnly ? "size-6 justify-center [&_svg]:size-3.5" : "h-5 px-2 text-[11px] [&_svg]:size-3",
        className,
      )}
    >
      <AppIcon app={app} aria-hidden />
      {iconOnly ? <span className="sr-only">{text}</span> : text}
    </span>
  );
}
