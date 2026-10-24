"use client";

import { ChevronRight, Lock, Pencil, Plus, Search, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { Kbd } from "@/components/ui/kbd";
import { SectionLabel } from "@/components/ui/section-label";
import { cn } from "@/lib/utils";
import type { AgentInfo } from "@/types/api";

import { AgentTile } from "./AgentTile";
import { filterAgents, groupAgents, parseCollapsed } from "./agentList";

/** Catégories repliées, mémorisées sur cet appareil (simple confort : rien ne casse sans stockage). */
const COLLAPSED_KEY = "atelier-nexus-agents-replies";

function readCollapsed(): string[] {
  try {
    return typeof window === "undefined" ? [] : parseCollapsed(localStorage.getItem(COLLAPSED_KEY));
  } catch {
    return []; // stockage indisponible : tout est déplié
  }
}

interface AgentSidebarProps {
  agents: AgentInfo[];
  /** Agent sélectionné, null quand l'accueil est affiché */
  active: string | null;
  disabled: boolean;
  onSelect: (name: string) => void;
  onCreate: () => void;
  onEdit: (name: string) => void;
}

/**
 * Agents de la barre latérale : recherche (« / » pour y aller), catégories repliables, tuile de
 * chaque agent ; les agents personnalisés se modifient au survol.
 */
export function AgentSidebar({ agents, active, disabled, onSelect, onCreate, onEdit }: AgentSidebarProps) {
  const [query, setQuery] = useState("");
  // Lu au premier rendu côté client (au rendu serveur, la liste des agents est encore vide)
  const [collapsed, setCollapsed] = useState<string[]>(readCollapsed);
  const search = useRef<HTMLInputElement>(null);
  // Identifiants propres à chaque exemplaire (barre fixe et tiroir peuvent coexister)
  const uid = useId();

  // « / » ou ⌘K / Ctrl+K : aller à la recherche, sauf pendant une saisie
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = !!target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
      const shortcut = (e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey);
      if ((e.key === "/" && !typing) || shortcut) {
        const field = search.current;
        if (!field || field.offsetParent === null) return; // barre masquée (petit écran)
        e.preventDefault();
        field.focus();
        field.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggle = (category: string) => {
    setCollapsed((current) => {
      const next = current.includes(category) ? current.filter((c) => c !== category) : [...current, category];
      try {
        localStorage.setItem(COLLAPSED_KEY, JSON.stringify(next));
      } catch {
        /* le choix vaut pour cette visite */
      }
      return next;
    });
  };

  const searching = query.trim() !== "";
  const groups = useMemo(() => groupAgents(filterAgents(agents, query)), [agents, query]);

  return (
    <nav aria-label="Agents" className="flex flex-col gap-2">
      <div className="flex items-center justify-between px-2">
        <SectionLabel>Agents</SectionLabel>
        <button
          type="button"
          onClick={onCreate}
          disabled={disabled}
          aria-label="Nouvel agent"
          title="Créer un agent"
          className="grid size-6 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-50"
        >
          <Plus className="size-4" aria-hidden />
        </button>
      </div>

      <div className="relative px-1">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <label htmlFor={`${uid}-search`} className="sr-only">
          Rechercher un agent
        </label>
        <input
          ref={search}
          id={`${uid}-search`}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setQuery("");
              e.currentTarget.blur();
            }
            // Entrée : premier agent trouvé
            if (e.key === "Enter" && groups[0]?.[1][0]) onSelect(groups[0][1][0].name);
          }}
          placeholder="Rechercher un agent"
          className="h-8 w-full rounded-lg border border-atelier-line bg-atelier-field pr-8 pl-8 text-[13px] outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-atelier-border focus-visible:shadow-focus [&::-webkit-search-cancel-button]:hidden"
        />
        {searching ? (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Effacer la recherche"
            className="absolute top-1/2 right-2.5 grid size-5 -translate-y-1/2 place-items-center rounded-sm text-muted-foreground hover:text-foreground"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        ) : (
          <Kbd className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2" aria-hidden>
            /
          </Kbd>
        )}
      </div>

      {searching && groups.length === 0 && (
        <p role="status" className="px-2 py-3 text-[13px] text-muted-foreground">
          Aucun agent ne correspond à « {query.trim()} ».
        </p>
      )}

      <div className="flex flex-col gap-1">
        {groups.map(([category, list]) => {
          const open = searching || !collapsed.includes(category);
          const listId = `${uid}-${category.replace(/\W+/g, "-")}`;
          return (
            <section key={category} aria-label={category}>
              <h2>
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={listId}
                  onClick={() => toggle(category)}
                  disabled={searching}
                  className="group/cat flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-[11px] font-semibold tracking-[0.08em] text-atelier-muted uppercase transition-colors hover:text-foreground disabled:cursor-default disabled:hover:text-atelier-muted"
                >
                  <ChevronRight
                    className={cn("size-3 shrink-0 transition-transform", open && "rotate-90", searching && "opacity-0")}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate">{category}</span>
                  <span className="font-medium tabular-nums opacity-0 transition-opacity group-hover/cat:opacity-100">
                    {list.length}
                  </span>
                </button>
              </h2>
              {open && (
                <ul id={listId} className="flex flex-col gap-px pb-1">
                  {list.map((agent) => {
                    const current = agent.name === active;
                    return (
                      <li key={agent.name} className="group relative">
                        <button
                          type="button"
                          disabled={disabled && !current}
                          aria-current={current ? "page" : undefined}
                          onClick={() => onSelect(agent.name)}
                          title={agent.description}
                          className={cn(
                            "flex w-full items-center gap-2.5 rounded-lg px-1.5 py-1 text-left text-[13px] transition-colors disabled:opacity-50",
                            agent.source === "custom" && "pr-8",
                            current ? "atelier-nav-active font-semibold" : "text-foreground/90 hover:bg-accent hover:text-foreground",
                          )}
                        >
                          <AgentTile icon={agent.icon} size="sm" variant={current ? "glass" : "plain"} />
                          <span className="min-w-0 flex-1 truncate">{agent.display_name}</span>
                          {agent.local_only && (
                            <Lock className="size-3 shrink-0 text-muted-foreground" aria-label="100 % local" />
                          )}
                        </button>
                        {agent.source === "custom" && (
                          <button
                            type="button"
                            onClick={() => onEdit(agent.name)}
                            aria-label={`Modifier ${agent.display_name}`}
                            className="absolute top-1/2 right-1 grid size-6 -translate-y-1/2 place-items-center rounded-sm text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-signature-soft hover:text-foreground focus-visible:opacity-100"
                          >
                            <Pencil className="size-3.5" aria-hidden />
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          );
        })}
      </div>

      <button
        type="button"
        onClick={onCreate}
        disabled={disabled}
        className="mx-1 mt-1 flex items-center gap-2.5 rounded-lg border border-dashed border-atelier-border-soft px-2 py-1.5 text-[13px] text-muted-foreground transition-colors hover:border-atelier-border hover:bg-accent hover:text-foreground disabled:opacity-50"
      >
        <span className="grid size-7 place-items-center rounded-lg bg-signature-faint text-accent-ink" aria-hidden>
          <Plus className="size-3.5" />
        </span>
        Créer un agent
      </button>
    </nav>
  );
}
