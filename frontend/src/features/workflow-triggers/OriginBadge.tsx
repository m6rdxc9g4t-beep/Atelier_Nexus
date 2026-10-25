"use client";

import { CalendarClock, FlaskConical, Hand, Zap } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { originLabel } from "./origin";

const ICON = { manual: Hand, schedule: CalendarClock, event: Zap, test: FlaskConical } as const;

/**
 * Étiquette d'origine d'une exécution (icône + texte : la couleur n'est jamais seule).
 * `compact` (listes étroites) : icône seule, libellé lu par les lecteurs d'écran et en info-bulle.
 */
export function OriginBadge({
  trigger,
  compact = false,
  className,
}: {
  trigger: string | null | undefined;
  compact?: boolean;
  className?: string;
}) {
  const Icon = ICON[(trigger ?? "manual") as keyof typeof ICON] ?? Hand;
  const label = originLabel(trigger);
  const automatic = !!trigger && trigger !== "manual";
  return (
    <Badge
      variant={automatic ? "signature" : "outline"}
      className={cn(compact && "px-1", className)}
      title={`Origine : ${label}`}
    >
      <Icon aria-hidden />
      {compact ? <span className="sr-only">{label}</span> : label}
    </Badge>
  );
}
