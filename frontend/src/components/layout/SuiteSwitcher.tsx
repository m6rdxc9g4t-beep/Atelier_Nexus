"use client";

import {
  BarChart3,
  CalendarCheck,
  Check,
  Clapperboard,
  CookingPot,
  Globe,
  GraduationCap,
  Landmark,
  LayoutGrid,
  type LucideIcon,
  Network,
  Table2,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
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

const ICONS: Record<SuiteAppId, LucideIcon> = {
  nexus: Network,
  viz: BarChart3,
  tab: Table2,
  projets: CalendarCheck,
  tresorerie: Landmark,
  cine: Clapperboard,
  savoir: GraduationCap,
  cuisine: CookingPot,
};

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
      <DropdownMenuContent align="start" className="w-76">
        <DropdownMenuLabel>Suite Atelier</DropdownMenuLabel>
        {apps.map((app) => {
          const Icon = ICONS[app.id];
          const current = app.id === CURRENT_APP;
          const st = app.healthUrl && !app.online ? (status[app.id] ?? "unknown") : null;
          const state = app.online ? ONLINE_LABEL : st ? statusLabel(st) : null;
          return (
            <DropdownMenuItem
              key={app.id}
              aria-label={`${app.name}${state ? ` (${state})` : ""}`}
              title={app.url}
              className={cn("gap-2.5 py-2", current && "bg-signature-soft")}
              onSelect={() => {
                if (!current) openExternal(app.url);
              }}
            >
              {/* Chaque tuile dans la couleur signature de SON application */}
              <span
                className="atelier-brand__tile atelier-brand__tile--sm"
                data-atelier-app={app.id}
                aria-hidden
              >
                <Icon />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span className="atelier-brand__name atelier-brand__name--sm">
                    <span className="atelier-brand__prefix">atelier_</span>
                    {app.short}
                  </span>
                  {st && <StatusDot status={st} />}
                  {app.online && <OnlineBadge />}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {app.description}
                </span>
              </span>
              {current && <Check className="text-accent-ink" aria-hidden />}
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
    <span className="flex items-center gap-1 text-[11px] text-muted-foreground" aria-hidden>
      <Globe className="size-3!" />
      {ONLINE_LABEL}
    </span>
  );
}

/** Pastille + libellé : la couleur n'est jamais seule porteuse de sens. */
function StatusDot({ status }: { status: SuiteStatus }) {
  return (
    <span className="flex items-center gap-1 text-[11px] text-muted-foreground" aria-hidden>
      <span
        className={cn(
          "size-1.5 rounded-full",
          status === "up" && "bg-success",
          status === "down" && "bg-destructive",
          status === "unknown" && "animate-pulse bg-muted-foreground/60",
        )}
      />
      {statusLabel(status)}
    </span>
  );
}
