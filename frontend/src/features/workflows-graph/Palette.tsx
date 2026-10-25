"use client";

import { ChevronRight, GripVertical, Plus, Search, Table2 } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Input } from "@/components/ui/input";
import { Segmented, type SegmentedOption } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/skeleton";
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

const KIND_OPTIONS: SegmentedOption<KindFilter>[] = [
  { value: "all", label: "Tout", ariaLabel: "Toutes les actions" },
  { value: "read", label: "Lecture", ariaLabel: "Lecture seule" },
  { value: "write", label: "Écriture", ariaLabel: "Écriture et destructif" },
];

/**
 * Palette des étapes, groupées par application : on glisse une entrée sur le graphe, ou on
 * clique « + » (à la suite de l'étape sélectionnée). Entrées indisponibles grisées.
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
    <aside aria-label="Étapes disponibles" className="flex min-h-0 w-72 shrink-0 flex-col border-r border-atelier-line bg-sidebar">
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
        <Segmented label="Nature des actions" value={kind} onChange={setKind} options={KIND_OPTIONS} className="w-full [&>button]:flex-1 [&>button]:justify-center" />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {error && (
          <Callout tone="destructive" role="alert" className="m-1">
            Catalogue indisponible : {error}
          </Callout>
        )}
        {!catalog && !error && (
          <div role="status" className="grid gap-2 p-1">
            <span className="sr-only">Chargement du catalogue…</span>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        )}
        {catalog && groups.length === 0 && <p className="p-2 text-sm text-muted-foreground">Aucune étape ne correspond.</p>}
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-1">
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
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left hover:bg-accent focus-visible:shadow-focus focus-visible:outline-none"
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
                  <ul className="mt-0.5 mb-1.5 ml-[1.1rem] grid grid-cols-[minmax(0,1fr)] border-l border-atelier-line pl-1.5">
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
      <p className="border-t border-atelier-line px-3 py-2 text-xs text-muted-foreground">
        Glissez une étape sur le graphe, ou « + » pour l&apos;ajouter après l&apos;étape sélectionnée.
      </p>
    </aside>
  );
}

/** Entrée sans boîte : survol en fond, poignée au survol, « + » pour l'ajouter au clavier. */
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
        "group relative flex min-w-0 items-start gap-1 rounded-md py-1.5 pr-1 pl-4",
        disabled ? "cursor-not-allowed opacity-55" : "cursor-grab hover:bg-accent active:cursor-grabbing",
      )}
    >
      {!disabled && (
        <GripVertical
          className="absolute top-2 left-0 size-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
          aria-hidden
        />
      )}
      <div className="min-w-0 flex-1">
        <p className="flex min-w-0 items-center gap-1.5 text-sm">
          <span className="min-w-0 truncate">{entry.label}</span>
          {entry.output_format === "atelier-table/1" && (
            <Table2 className="size-3.5 shrink-0 text-muted-foreground" role="img" aria-label="sortie en table" />
          )}
        </p>
        {entry.kind !== "read" && <KindBadge kind={entry.kind} className="mt-1" />}
        {disabled && entry.unavailable_reason && (
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{entry.unavailable_reason}</p>
        )}
      </div>
      {entry.kind === "read" && <KindBadge kind="read" compact className="mt-1" />}
      <Button
        type="button"
        size="icon-xs"
        variant="ghost"
        className="-my-0.5"
        disabled={disabled}
        aria-label={`Ajouter l'étape ${entry.label}`}
        onClick={() => onAdd(entry)}
      >
        <Plus />
      </Button>
    </li>
  );
}
