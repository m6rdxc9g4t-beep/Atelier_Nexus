"use client";

import { cn } from "@/lib/utils";
import type { AgentInfo } from "@/types/api";

import { AgentIcon } from "./agentMeta";

interface AgentSidebarProps {
  agents: AgentInfo[];
  active: string;
  disabled: boolean;
  onSelect: (name: string) => void;
}

/** Liste des agents, regroupés par catégorie quand le catalogue en fournit. */
export function AgentSidebar({ agents, active, disabled, onSelect }: AgentSidebarProps) {
  const groups = new Map<string, AgentInfo[]>();
  for (const agent of agents) {
    const key = agent.category ?? "Agents";
    groups.set(key, [...(groups.get(key) ?? []), agent]);
  }

  return (
    <nav aria-label="Agents" className="flex flex-col gap-5 p-3">
      {[...groups].map(([category, list]) => (
        <section key={category} aria-label={category}>
          <h2 className="px-2 pb-1.5 text-xs font-medium text-muted-foreground">{category}</h2>
          <ul className="flex flex-col gap-0.5">
            {list.map((agent) => {
              const current = agent.name === active;
              return (
                <li key={agent.name}>
                  <button
                    type="button"
                    disabled={disabled && !current}
                    aria-current={current ? "page" : undefined}
                    onClick={() => onSelect(agent.name)}
                    title={agent.description}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors disabled:opacity-50",
                      current
                        ? "bg-accent-soft font-medium text-accent-ink"
                        : "text-foreground hover:bg-accent",
                    )}
                  >
                    <AgentIcon icon={agent.icon} className={cn("size-4 shrink-0", !current && "text-muted-foreground")} aria-hidden />
                    <span className="truncate">{agent.display_name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </nav>
  );
}
