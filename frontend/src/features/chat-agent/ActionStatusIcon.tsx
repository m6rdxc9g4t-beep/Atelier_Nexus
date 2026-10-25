import { Ban, CircleAlert, CircleCheck, CircleDashed, CircleSlash, LoaderCircle, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import type { ActionStatus } from "./thread";

/** État d'une action, en mots : nom accessible de l'icône (la couleur n'est jamais seule). */
export const ACTION_STATE: Record<ActionStatus, string> = {
  queued: "autorisée, en attente",
  running: "en cours",
  done: "terminée",
  error: "en erreur",
  refused: "refusée",
  interrupted: "autorisée, non exécutée",
};

const ICON: Record<ActionStatus, LucideIcon> = {
  queued: CircleDashed,
  running: LoaderCircle,
  done: CircleCheck,
  error: CircleAlert,
  refused: Ban,
  interrupted: CircleSlash,
};

const TONE: Record<ActionStatus, string> = {
  queued: "text-muted-foreground",
  running: "animate-spin text-accent-ink motion-reduce:animate-none",
  done: "text-success",
  error: "text-destructive",
  refused: "text-muted-foreground",
  interrupted: "text-warning",
};

/** Icône d'état d'une action ou d'une ligne d'activité (role="img", nommée). */
export function ActionStatusIcon({ status, className }: { status: ActionStatus; className?: string }) {
  const Icon = ICON[status];
  return <Icon role="img" aria-label={ACTION_STATE[status]} className={cn("size-4 shrink-0", TONE[status], className)} />;
}
