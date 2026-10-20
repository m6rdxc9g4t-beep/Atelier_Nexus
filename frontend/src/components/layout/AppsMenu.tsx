"use client";

import { Plug } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { AppStatus } from "@/types/api";

/** Applications que les agents peuvent utiliser, avec leur état (vérifié par le backend). */
export function AppsMenu({ apps }: { apps: AppStatus[] }) {
  const up = apps.filter((a) => a.available).length;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="hidden md:inline-flex" aria-label={`Applications : ${up} sur ${apps.length} joignables`}>
          <Plug />
          <span className="tabular-nums">
            {up}/{apps.length}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Applications connectées</DropdownMenuLabel>
        <ul className="flex flex-col gap-0.5 px-1 pb-1">
          {apps.map((app) => (
            <li key={app.id} className="flex items-start gap-2.5 rounded-sm px-1.5 py-1.5">
              <span
                aria-hidden
                className={cn(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  app.available ? "bg-success" : app.configured ? "bg-destructive" : "bg-muted-foreground/40",
                )}
              />
              <span className="min-w-0 text-sm">
                <span className="block font-medium">{app.label}</span>
                <span className="block text-xs break-words text-muted-foreground">
                  {app.available
                    ? app.detail
                    : app.configured
                      ? (app.error ?? "injoignable")
                      : "non configurée (backend/.env)"}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
