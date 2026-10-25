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
    <header className="relative z-10 flex h-14 shrink-0 items-center gap-1 border-b border-atelier-line bg-sidebar/85 px-2 backdrop-blur-md lg:hidden">
      <span className="flex shrink-0 pr-0.5 pl-1">
        <AtelierBrand />
      </span>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={drawerOpen}
        onClick={() => setDrawerOpen(true)}
        className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 text-left transition-colors hover:bg-accent focus-visible:shadow-focus focus-visible:outline-none"
      >
        {ContextIcon ? (
          <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-lg border border-atelier-line bg-signature-faint text-accent-ink">
            <ContextIcon className="size-3.5" />
          </span>
        ) : (
          <AgentTile icon={ctx.icon} size="sm" />
        )}
        <span className="sr-only">Ouvrir la navigation : </span>
        <span className="min-w-0 truncate text-sm font-semibold">{ctx.label}</span>
        {ctx.localOnly && (
          <>
            <Lock className="size-3 shrink-0 text-muted-foreground" aria-hidden />
            <span className="sr-only">, 100 % local</span>
          </>
        )}
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      </button>
      <div className="flex shrink-0 items-center gap-0.5">
        <InboxButton />
        <SuiteSwitcher />
      </div>
    </header>
  );
}
