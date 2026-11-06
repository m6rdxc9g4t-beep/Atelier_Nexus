"use client";

import { Check, Globe, LayoutGrid } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { appTheme } from "@/features/workflows-graph/catalog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  CURRENT_APP,
  ONLINE_LABEL,
  type SuiteAppId,
  type SuiteStatus,
  checkHealth,
  statusLabel,
  suiteApps,
} from "@/lib/suite";
import { openExternal } from "@/lib/desktop";
import { cn } from "@/lib/utils";

import { AppIcon } from "./appIcons";

/** Sélecteur « Suite Atelier » (SUITE.md §3) : état vérifié à l'ouverture, sans bloquer le menu. */
export function SuiteSwitcher() {
  const [apps] = useState(suiteApps);
  const [status, setStatus] = useState<Partial<Record<SuiteAppId, SuiteStatus>>>({});

  const refresh = () => {
    for (const app of apps) {
      // Les apps en ligne (Cuisine) ne sont jamais sondées
      if (!app.healthUrl || app.online) continue;
      setStatus((s) => ({ ...s, [app.id]: "unknown" }));
      void checkHealth(app.healthUrl).then((st) => setStatus((s) => ({ ...s, [app.id]: st })));
    }
  };

  return (
    <DropdownMenu onOpenChange={(open) => open && refresh()}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Suite Atelier" title="Suite Atelier">
          <LayoutGrid />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-76">
        <DropdownMenuLabel>Suite Atelier</DropdownMenuLabel>
        {apps.map((app) => {
          const current = app.id === CURRENT_APP;
          const st = app.healthUrl && !app.online ? (status[app.id] ?? "unknown") : null;
          const state = app.online ? ONLINE_LABEL : st ? statusLabel(st) : null;
          return (
            <DropdownMenuItem
              key={app.id}
              aria-label={`${app.name}${state ? ` (${state})` : ""}`}
              title={app.url}
              aria-current={current ? "true" : undefined}
              className={cn("gap-2.5 py-1.5", current && "bg-atelier-selected")}
              onSelect={() => {
                if (!current) openExternal(app.url);
              }}
            >
              {/* Chaque icône dans la couleur signature de SON application (seul endroit coloré) */}
              <span className="atelier-brand__tile atelier-brand__tile--sm" {...appTheme(app.id)} aria-hidden>
                <AppIcon app={app.id} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span className="atelier-brand__name atelier-brand__name--sm">
                    <span className="atelier-brand__prefix">Atelier </span>
                    {app.short}
                  </span>
                  {st && st !== "up" && <StatusDot status={st} />}
                  {app.online && <OnlineBadge />}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {app.description}
                </span>
              </span>
              {current && <Check className="text-muted-foreground" aria-hidden />}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** App hébergée en ligne : pas d'état vérifié, seulement l'indication « en ligne ». */
function OnlineBadge() {
  return (
    <span className="flex items-center gap-1 text-[11.5px] text-atelier-faint" aria-hidden>
      <Globe className="size-3!" />
      {ONLINE_LABEL}
    </span>
  );
}

/**
 * Pastille + libellé, seulement quand l'app ne répond pas (ou pendant la vérification) : une app en
 * marche reste muette (DESIGN.md « témoin muet »). La couleur n'est jamais seule porteuse de sens.
 */
function StatusDot({ status }: { status: SuiteStatus }) {
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 text-[11.5px]",
        status === "down" ? "font-medium text-destructive-ink" : "text-atelier-faint",
      )}
      aria-hidden
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          status === "down" && "bg-destructive",
          status === "unknown" && "shadow-[inset_0_0_0_1.25px_var(--atelier-faint)]",
        )}
      />
      {statusLabel(status)}
    </span>
  );
}
