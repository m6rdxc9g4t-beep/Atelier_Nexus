"use client";

import {
  BarChart3,
  CalendarCheck,
  Check,
  Clapperboard,
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
  type SuiteAppId,
  type SuiteStatus,
  checkHealth,
  statusLabel,
  suiteApps,
} from "@/lib/suite";
import { cn } from "@/lib/utils";

const ICONS: Record<SuiteAppId, LucideIcon> = {
  nexus: Network,
  viz: BarChart3,
  tab: Table2,
  projets: CalendarCheck,
  tresorerie: Landmark,
  cine: Clapperboard,
  savoir: GraduationCap,
};

/** Sélecteur « Suite Atelier » (SUITE.md §3) : état vérifié à l'ouverture, sans bloquer le menu. */
export function SuiteSwitcher() {
  const [apps] = useState(suiteApps);
  const [status, setStatus] = useState<Partial<Record<SuiteAppId, SuiteStatus>>>({});

  const refresh = () => {
    for (const app of apps) {
      if (!app.healthUrl) continue;
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
          const st = app.healthUrl ? (status[app.id] ?? "unknown") : null;
          return (
            <DropdownMenuItem
              key={app.id}
              aria-label={`${app.name}${st ? ` (${statusLabel(st)})` : ""}`}
              title={app.url}
              className={cn("gap-2.5 py-2", current && "bg-accent-soft")}
              onSelect={() => {
                if (!current) window.open(app.url, "_blank", "noopener");
              }}
            >
              <span className="atelier-brand__tile atelier-brand__tile--sm" aria-hidden>
                <Icon />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span className="atelier-brand__name atelier-brand__name--sm">
                    <span className="atelier-brand__prefix">atelier_</span>
                    {app.short}
                  </span>
                  {st && <StatusDot status={st} />}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {app.description}
                </span>
              </span>
              {current && <Check className="text-primary" aria-hidden />}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
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
