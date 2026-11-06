"use client";

import { ChevronDown, House, Inbox, Lock, type LucideIcon, Map as MapIcon, Waypoints } from "lucide-react";

import { AgentTile } from "@/features/chat-agent/AgentTile";
import { InboxButton } from "@/features/workflow-triggers/InboxDialog";
import { studioTab } from "@/features/workflows/studio";
import { useChatStore } from "@/stores/useChatStore";
import { useNavStore } from "@/stores/useNavStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo } from "@/types/api";

import { AtelierBrand } from "./AtelierBrand";
import { SuiteSwitcher } from "./SuiteSwitcher";
import { type HeaderContext, headerContext } from "./headerContext";

/** Icône des contextes sans agent (mêmes icônes que la navigation de la barre latérale). */
const CONTEXT_ICON: Record<Exclude<HeaderContext["kind"], "agent">, LucideIcon> = {
  home: House,
  workflows: Waypoints,
  map: MapIcon,
  inbox: Inbox,
};

/**
 * Barre des petits écrans (sous lg), une seule ligne qui tient à 375 px : marque, bouton du
 * contexte courant (accueil, onglet du Studio ou agent, nom tronqué) qui ouvre la navigation en
 * tiroir (agents, workflows, carte, thème, réglages), « À valider » et la suite.
 * `agents` : catalogue, pour le nom et l'icône de l'agent (sinon son identifiant rendu lisible).
 */
export function AppHeader({ agents = [] }: { agents?: AgentInfo[] }) {
  const view = useNavStore((s) => s.view);
  const drawerOpen = useNavStore((s) => s.drawerOpen);
  const setDrawerOpen = useNavStore((s) => s.setDrawerOpen);
  const agent = useChatStore((s) => s.agent);
  const studio = useWorkflowStudioStore((s) => studioTab(s));
  const ctx = headerContext(view, agent, agents, studio);
  const ContextIcon = ctx.kind === "agent" ? null : CONTEXT_ICON[ctx.kind];

  return (
    <header className="relative z-10 flex h-11 shrink-0 items-center gap-1 border-b border-atelier-line bg-sidebar px-2 lg:hidden">
      <span className="flex shrink-0 pr-0.5 pl-1">
        <AtelierBrand compact />
      </span>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={drawerOpen}
        onClick={() => setDrawerOpen(true)}
        className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 text-left transition-colors hover:bg-accent"
      >
        {ContextIcon ? (
          <ContextIcon className="size-4 shrink-0 text-atelier-faint" aria-hidden />
        ) : (
          <AgentTile icon={ctx.icon} variant="bare" />
        )}
        <span className="sr-only">Ouvrir la navigation : </span>
        <span className="min-w-0 truncate text-sm font-semibold">{ctx.label}</span>
        {ctx.localOnly && (
          <>
            <Lock className="size-3 shrink-0 text-atelier-faint" aria-hidden />
            <span className="sr-only">, 100 % local</span>
          </>
        )}
        <ChevronDown className="size-3.5 shrink-0 text-atelier-faint" aria-hidden />
      </button>
      <div className="flex shrink-0 items-center gap-0.5">
        <InboxButton />
        <SuiteSwitcher />
      </div>
    </header>
  );
}
