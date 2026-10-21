"use client";

import { ChevronRight, Plus, Search } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { ActionKind, Catalog, CatalogEntry } from "@/types/api";

import { type GroupOptions, groupCatalog } from "./catalog";
import { AppStatusDot, AppTile, KindBadge } from "./StepBadges";

/** Type MIME du glisser-déposer palette → graphe. */
export const DRAG_MIME = "application/x-atelier-step";

type KindFilter = "all" | "read" | "write";

const KIND_FILTERS: Record<KindFilter, ActionKind[] | undefined> = {
  all: undefined,
  read: ["read"],
  write: ["write", "destructive"],
};

/**
 * Palette des étapes, groupées par application : on glisse une entrée sur le graphe, ou on
 * clique « Ajouter » (à la suite de l'étape sélectionnée). Entrées indisponibles grisées.
 */
export function Palette({
  catalog,
  error,
  onAdd,
}: {
  catalog: Catalog | null;
  error: string | null;
  onAdd: (entry: CatalogEntry) => void;
}) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const ids = useId();

  const groups = useMemo(() => {
    if (!catalog) return [];
    const options: GroupOptions = { kinds: KIND_FILTERS[kind] };
    return groupCatalog(catalog, query, options);
  }, [catalog, query, kind]);
  const filtering = query.trim() !== "" || kind !== "all";

  return (
    <aside aria-label="Étapes disponibles" className="flex min-h-0 w-72 shrink-0 flex-col border-r border-atelier-border-soft bg-sidebar">
      <div className="grid gap-2 border-b border-atelier-line p-3">
        <label htmlFor={`${ids}-q`} className="sr-only">
          Filtrer les étapes
        </label>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            id={`${ids}-q`}
            type="search"
            className="h-8 pl-8"
            placeholder="Filtrer (ex. créer tâche)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <label htmlFor={`${ids}-kind`} className="sr-only">
          Nature des actions
        </label>
        <NativeSelect id={`${ids}-kind`} value={kind} onChange={(e) => setKind(e.target.value as KindFilter)}>
          <option value="all">Toutes les actions</option>
          <option value="read">Lecture seule</option>
          <option value="write">Écriture et destructif</option>
        </NativeSelect>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {error && (
          <p role="alert" className="p-2 text-sm text-destructive">
            Catalogue indisponible : {error}
          </p>
        )}
        {!catalog && !error && (
          <p role="status" className="p-2 text-sm text-muted-foreground">
            Chargement du catalogue…
          </p>
        )}
        {catalog && groups.length === 0 && (
          <p className="p-2 text-sm text-muted-foreground">Aucune étape ne correspond.</p>
        )}
        <ul className="grid gap-1.5">
          {groups.map((group) => {
            const open = filtering || !closed.has(group.key);
            const toggle = () =>
              setClosed((c) => {
                const next = new Set(c);
                if (next.has(group.key)) next.delete(group.key);
                else next.add(group.key);
                return next;
              });
            return (
              <li key={group.key}>
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={toggle}
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left hover:bg-accent focus-visible:shadow-focus"
                >
                  <AppTile app={group.app} color={group.color} size="xs" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{group.name}</span>
                    <AppStatusDot status={group.status} />
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {filtering ? `${group.entries.length}/${group.total}` : group.total}
                  </span>
                  <ChevronRight className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden />
                </button>
                {open && (
                  <ul className="mt-1 grid gap-1 pl-1">
                    {group.entries.length === 0 && (
                      <li className="px-2 py-1 text-xs text-muted-foreground">
                        {group.status === "no_contract"
                          ? "Cette application ne publie pas encore de manifeste."
                          : group.status === "ok"
                            ? "Aucune action."
                            : "Application indisponible."}
                      </li>
                    )}
                    {group.entries.map((entry) => (
                      <PaletteEntry key={entry.uses} entry={entry} onAdd={onAdd} />
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      <p className="border-t border-atelier-line px-3 py-2 text-[11px] text-muted-foreground">
        Glissez une étape sur le graphe, ou « + » pour l&apos;ajouter après l&apos;étape sélectionnée.
      </p>
    </aside>
  );
}

function PaletteEntry({ entry, onAdd }: { entry: CatalogEntry; onAdd: (entry: CatalogEntry) => void }) {
  const disabled = !entry.available;
  return (
    <li
      draggable={!disabled}
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAG_MIME, entry.uses);
        e.dataTransfer.effectAllowed = "copy";
      }}
      title={disabled ? (entry.unavailable_reason ?? "Indisponible") : entry.description || entry.uses}
      className={cn(
        "group flex items-start gap-2 rounded-md border border-atelier-line bg-card px-2 py-1.5",
        disabled ? "cursor-not-allowed opacity-55" : "cursor-grab hover:border-atelier-border active:cursor-grabbing",
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">{entry.label}</p>
        <div className="mt-0.5 flex flex-wrap items-center gap-1">
          <KindBadge kind={entry.kind} />
          {entry.output_format === "atelier-table/1" && (
            <span className="text-[10px] text-muted-foreground">table</span>
          )}
        </div>
        {disabled && entry.unavailable_reason && (
          <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{entry.unavailable_reason}</p>
        )}
      </div>
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        className="size-7"
        disabled={disabled}
        aria-label={`Ajouter l'étape ${entry.label}`}
        onClick={() => onAdd(entry)}
      >
        <Plus />
      </Button>
    </li>
  );
}
