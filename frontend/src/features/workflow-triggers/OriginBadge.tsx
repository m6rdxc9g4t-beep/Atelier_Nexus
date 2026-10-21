"use client";

import { CalendarClock, FlaskConical, Hand, Zap } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import { originLabel } from "./origin";

const ICON = { manual: Hand, schedule: CalendarClock, event: Zap, test: FlaskConical } as const;

/** Étiquette d'origine d'une exécution (icône + texte : la couleur n'est jamais seule). */
export function OriginBadge({ trigger, className }: { trigger: string | null | undefined; className?: string }) {
  const Icon = ICON[(trigger ?? "manual") as keyof typeof ICON] ?? Hand;
  return (
    <Badge variant={trigger && trigger !== "manual" ? "default" : "outline"} className={className} title={`Origine : ${originLabel(trigger)}`}>
      <Icon aria-hidden />
      {originLabel(trigger)}
    </Badge>
  );
}
