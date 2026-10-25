import { ChevronRight } from "lucide-react";

import { AppChip } from "@/components/layout/AppChip";
import { appShort } from "@/components/layout/appIcons";
import { cn } from "@/lib/utils";

import { chainLabel, chainView } from "./chain";

/**
 * Chaîne d'applications d'un workflow ou d'un modèle : puces dans la couleur de chaque app,
 * reliées par des chevrons (« Convert › Tab › Viz »), le reste en « +n ». Les lecteurs d'écran
 * reçoivent la phrase « Applications : Convert, puis Tab… ».
 */
export function AppChain({
  apps,
  max = 4,
  colors,
  className,
}: {
  apps: string[];
  max?: number;
  /** Couleur reçue du backend pour une app que la marque ne connaît pas (extensions) */
  colors?: Record<string, string | null | undefined>;
  className?: string;
}) {
  if (apps.length === 0) return null;
  const { shown, hidden, rest } = chainView(apps, max);
  return (
    <div className={cn("min-w-0", className)}>
      <span className="sr-only">{chainLabel(apps, appShort)}</span>
      <span aria-hidden className="flex flex-wrap items-center gap-1">
        {shown.map((app, i) => (
          <span key={app} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />}
            <AppChip app={app} color={colors?.[app]} />
          </span>
        ))}
        {hidden > 0 && (
          <span className="text-xs text-muted-foreground tabular-nums" title={rest.map(appShort).join(", ")}>
            +{hidden}
          </span>
        )}
      </span>
    </div>
  );
}
