"use client";

import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleSlash,
  Eye,
  LoaderCircle,
  PenLine,
  ShieldAlert,
  ShieldQuestion,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { AppIcon } from "@/components/layout/appIcons";
import { cn } from "@/lib/utils";
import type { ActionKind, CatalogApp, NodeAppStatus } from "@/types/api";

import { APP_STATUS_LABEL, KIND_LABEL, appTheme } from "./catalog";
import type { StepDisplayStatus } from "./graph";
import { STEP_STATUS_LABEL } from "./run";

const KIND_ICON = { read: Eye, write: PenLine, destructive: ShieldAlert } as const;
const KIND_VARIANT = { read: "outline", write: "warning", destructive: "destructive" } as const;

const KIND_HINT = { read: "Aucun effet sur les données", write: "Validation demandée à chaque exécution" } as const;

/**
 * Badge Lecture / Écriture / Destructif (icône + texte : la couleur n'est jamais seule).
 * `compact` : la lecture, sans effet, se réduit à son icône (nom lu par les lecteurs d'écran) ;
 * l'écriture et le destructif gardent toujours leur badge complet.
 */
export function KindBadge({ kind, compact = false, className }: { kind: ActionKind; compact?: boolean; className?: string }) {
  const Icon = KIND_ICON[kind];
  const hint = kind === "read" ? KIND_HINT.read : KIND_HINT.write;
  if (compact && kind === "read")
    return (
      <span className={cn("inline-flex shrink-0 items-center text-muted-foreground", className)} title={`${KIND_LABEL.read} : ${hint.toLowerCase()}`}>
        <Icon className="size-3.5" aria-hidden />
        <span className="sr-only">{KIND_LABEL.read}</span>
      </span>
    );
  return (
    <Badge variant={KIND_VARIANT[kind]} className={className} title={hint}>
      <Icon aria-hidden />
      {KIND_LABEL[kind]}
    </Badge>
  );
}

/** Icône d'application dans SA couleur signature (marque de la suite) : seul élément coloré par app. */
export function AppTile({
  app,
  color,
  size = "sm",
  className,
}: {
  app: string | null;
  color?: string | null;
  size?: "sm" | "xs";
  className?: string;
}) {
  const theme = appTheme(app, color);
  return (
    <span
      aria-hidden
      {...theme}
      className={cn(
        "atelier-brand__tile atelier-brand__tile--sm",
        size === "xs" && "size-6! rounded-sm! [&_svg]:size-3.5!",
        className,
      )}
    >
      <AppIcon app={app} />
    </span>
  );
}

// Témoin muet : une app joignable n'a ni pastille ni couleur ; rouge ou ambre seulement si ça ne va pas.
const APP_STATUS_DOT: Record<NodeAppStatus, string> = {
  ok: "hidden",
  unreachable: "bg-destructive",
  no_contract: "bg-warning",
  not_configured: "bg-atelier-faint/50",
};

const APP_STATUS_TEXT: Record<NodeAppStatus, string> = {
  ok: "text-atelier-faint",
  unreachable: "font-medium text-destructive-ink",
  no_contract: "text-warning-ink",
  not_configured: "text-atelier-faint",
};

/** Pastille + libellé de l'état d'une application. */
export function AppStatusDot({ status, className }: { status: CatalogApp["status"]; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", APP_STATUS_TEXT[status], className)}>
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", APP_STATUS_DOT[status])} />
      {APP_STATUS_LABEL[status]}
    </span>
  );
}

// États de run : neutres quand tout va bien (l'icône suffit), colorés seulement s'ils sont anormaux
// (échec, refus, validation attendue).
const RUN_ICON = {
  pending: { Icon: CircleDashed, className: "text-atelier-faint" },
  running: { Icon: LoaderCircle, className: "animate-spin text-muted-foreground motion-reduce:animate-none" },
  ok: { Icon: CircleCheck, className: "text-muted-foreground" },
  error: { Icon: CircleAlert, className: "text-destructive-ink" },
  refused: { Icon: CircleSlash, className: "text-warning-ink" },
  skipped: { Icon: CircleSlash, className: "text-atelier-faint" },
  awaiting_approval: { Icon: ShieldQuestion, className: "text-warning-ink" },
} as const;

/** Icône d'état d'exécution d'une étape, avec son libellé accessible. */
export function StepStatusIcon({ status, className }: { status: StepDisplayStatus; className?: string }) {
  const { Icon, className: tone } = RUN_ICON[status];
  return <Icon role="img" aria-label={STEP_STATUS_LABEL[status]} className={cn("size-3.5 shrink-0", tone, className)} />;
}

export function ErrorIcon({ className, label }: { className?: string; label: string }) {
  return <TriangleAlert role="img" aria-label={label} className={cn("size-3.5 shrink-0 text-destructive-ink", className)} />;
}
