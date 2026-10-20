"use client";

import { Lock, Pencil, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AgentInfo } from "@/types/api";

import { AgentIcon } from "./agentMeta";

interface AgentSidebarProps {
  agents: AgentInfo[];
  active: string;
  disabled: boolean;
  onSelect: (name: string) => void;
  onCreate: () => void;
  onEdit: (name: string) => void;
}

/** Agents regroupés par catégorie ; les agents personnalisés se modifient au survol. */
export function AgentSidebar({ agents, active, disabled, onSelect, onCreate, onEdit }: AgentSidebarProps) {
  const groups = new Map<string, AgentInfo[]>();
  for (const agent of agents) {
    const key = agent.category ?? "Agents";
    groups.set(key, [...(groups.get(key) ?? []), agent]);
  }

  return (
    <nav aria-label="Agents" className="flex min-h-full flex-col gap-5 px-3 pt-3">
      {[...groups].map(([category, list]) => (
        <section key={category} aria-label={category}>
          <h2 className="px-2 pb-1.5 text-xs font-medium text-muted-foreground">{category}</h2>
          <ul className="flex flex-col gap-0.5">
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
                      "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors disabled:opacity-50",
                      agent.source === "custom" && "pr-8",
                      current
                        ? "bg-accent-soft font-medium text-accent-ink"
                        : "text-foreground hover:bg-accent",
                    )}
                  >
                    <AgentIcon
                      icon={agent.icon}
                      className={cn("size-4 shrink-0", !current && "text-muted-foreground")}
                      aria-hidden
                    />
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
                      className="absolute top-1/2 right-1 grid size-6 -translate-y-1/2 place-items-center rounded-sm text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-background hover:text-foreground focus-visible:opacity-100"
                    >
                      <Pencil className="size-3.5" aria-hidden />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      {/* Toujours visible, même quand la liste défile */}
      <div className="sticky bottom-0 mt-auto -mx-3 border-t bg-card px-3 py-3">
        <Button variant="outline" className="w-full justify-start" onClick={onCreate} disabled={disabled}>
          <Plus />
          Créer un agent
        </Button>
      </div>
    </nav>
  );
}
