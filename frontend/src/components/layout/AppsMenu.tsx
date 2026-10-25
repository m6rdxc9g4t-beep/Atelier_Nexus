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
          "group inline-flex h-8 shrink-0 items-center gap-2 rounded-lg px-2 text-[13px] whitespace-nowrap text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring data-[state=open]:bg-accent",
          className,
        )}
      >
        <StatusDot status={up === 0 ? "off" : down ? "warning" : "up"} />
        <span>
          Apps <span className="font-semibold text-foreground tabular-nums">{up}</span>
          <span className="tabular-nums">/{apps.length}</span>
        </span>
        <ChevronUp className="size-3.5 transition-transform group-data-[state=closed]:rotate-180" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-80">
        <DropdownMenuLabel>Applications connectées</DropdownMenuLabel>
        <ul className="flex flex-col gap-0.5 px-1 pb-1">
          {apps.map((app) => (
            <li key={app.id} className="flex items-start gap-2.5 rounded-sm px-1.5 py-1.5">
              <StatusDot status={appDot(app)} className="mt-1.5" />
              <span className="min-w-0 text-sm">
                <span className="block font-medium">{app.label}</span>
                <span className="block text-xs break-words text-muted-foreground">
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
