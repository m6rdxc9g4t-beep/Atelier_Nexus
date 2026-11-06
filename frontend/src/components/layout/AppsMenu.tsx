"use client";

import { ChevronUp } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { type DotStatus, StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/lib/utils";
import type { AppStatus } from "@/types/api";

/** État d'une application pour la pastille (joignable, en panne, non configurée). */
export const appDot = (app: AppStatus): DotStatus => (app.available ? "up" : app.configured ? "down" : "off");

/** Applications que les agents peuvent utiliser, avec leur état (vérifié par le backend). */
export function AppsMenu({ apps, className }: { apps: AppStatus[]; className?: string }) {
  const up = apps.filter((a) => a.available).length;
  const down = apps.some((a) => a.configured && !a.available);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`Applications : ${up} sur ${apps.length} joignables`}
        title="Applications connectées"
        className={cn(
          "group inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-1.5 text-xs font-medium whitespace-nowrap text-muted-foreground transition-colors hover:bg-accent hover:text-foreground data-[state=open]:bg-accent",
          className,
        )}
      >
        <StatusDot status={up === 0 ? "off" : down ? "warning" : "up"} />
        <span>
          Apps <span className="text-foreground tabular-nums">{up}</span>
          <span className="tabular-nums">/{apps.length}</span>
        </span>
        <ChevronUp className="size-3 text-atelier-faint transition-transform group-data-[state=closed]:rotate-180" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-80">
        <DropdownMenuLabel>Applications connectées</DropdownMenuLabel>
        <ul className="flex flex-col gap-0.5 px-1 pb-1">
          {apps.map((app) => (
            <li key={app.id} className="flex items-start gap-2.5 rounded-md px-1.5 py-1.5">
              {/* Témoin muet : une app joignable n'a pas de pastille, seulement son détail */}
              {app.available ? (
                <span className="mt-1.5 size-2 shrink-0" aria-hidden />
              ) : (
                <StatusDot status={appDot(app)} className="mt-1.5" />
              )}
              <span className="min-w-0 text-sm">
                <span className="block font-medium">{app.label}</span>
                <span
                  className={cn(
                    "block text-xs break-words text-muted-foreground",
                    app.configured && !app.available && "text-destructive-ink",
                  )}
                >
                  {app.available
                    ? app.detail
                    : app.configured
                      ? (app.error ?? "injoignable")
                      : "non configurée (Réglages)"}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
