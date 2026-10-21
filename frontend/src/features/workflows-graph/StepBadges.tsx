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

/** Badge Lecture / Écriture / Destructif (icône + texte : la couleur n'est jamais seule). */
export function KindBadge({ kind, className }: { kind: ActionKind; className?: string }) {
  const Icon = KIND_ICON[kind];
  return (
    <Badge
      variant={KIND_VARIANT[kind]}
      className={className}
      title={kind === "read" ? "Aucun effet sur les données" : "Validation demandée à chaque exécution"}
    >
      <Icon aria-hidden />
      {KIND_LABEL[kind]}
    </Badge>
  );
}

/** Tuile d'application dans SA couleur signature (marque de la suite). */
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

const APP_STATUS_DOT: Record<NodeAppStatus, string> = {
  ok: "bg-success",
  unreachable: "bg-destructive",
  no_contract: "bg-warning",
  not_configured: "bg-muted-foreground/50",
};

/** Pastille + libellé de l'état d'une application. */
export function AppStatusDot({ status, className }: { status: CatalogApp["status"]; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 text-[11px] text-muted-foreground", className)}>
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", APP_STATUS_DOT[status])} />
      {APP_STATUS_LABEL[status]}
    </span>
  );
}

const RUN_ICON = {
  pending: { Icon: CircleDashed, className: "text-muted-foreground" },
  running: { Icon: LoaderCircle, className: "animate-spin text-accent-ink" },
  ok: { Icon: CircleCheck, className: "text-success" },
  error: { Icon: CircleAlert, className: "text-destructive" },
  refused: { Icon: CircleSlash, className: "text-warning" },
  skipped: { Icon: CircleSlash, className: "text-muted-foreground" },
  awaiting_approval: { Icon: ShieldQuestion, className: "text-warning" },
} as const;

/** Icône d'état d'exécution d'une étape, avec son libellé accessible. */
export function StepStatusIcon({ status, className }: { status: StepDisplayStatus; className?: string }) {
  const { Icon, className: tone } = RUN_ICON[status];
  return <Icon role="img" aria-label={STEP_STATUS_LABEL[status]} className={cn("size-3.5 shrink-0", tone, className)} />;
}

export function ErrorIcon({ className, label }: { className?: string; label: string }) {
  return <TriangleAlert role="img" aria-label={label} className={cn("size-3.5 shrink-0 text-destructive", className)} />;
}
