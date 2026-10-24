"use client";

import { House, Inbox, Map as MapIcon, Waypoints, type LucideIcon } from "lucide-react";

import { ThemeToggle } from "@/components/theme/theme-toggle";
import { AgentSidebar } from "@/features/chat-agent/AgentSidebar";
import { SettingsButton } from "@/features/settings/SettingsDialog";
import { badgeText, inboxLabel } from "@/features/workflow-triggers/origin";
import { useInboxCount } from "@/features/workflow-triggers/useInboxCount";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/useChatStore";
import { useNavStore } from "@/stores/useNavStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, AppStatus } from "@/types/api";

import { AppsMenu } from "./AppsMenu";
import { AtelierBrand } from "./AtelierBrand";
import { SuiteSwitcher } from "./SuiteSwitcher";

interface AppSidebarProps {
  agents: AgentInfo[];
  apps: AppStatus[];
  onCreateAgent: () => void;
  onEditAgent: (name: string) => void;
}

/**
 * Barre latérale unique : marque et suite, navigation (accueil, workflows de suite, carte,
 * « À valider »), agents, puis état des applications, thème et réglages.
 * Fixe sur grand écran, en tiroir en dessous (même contenu).
 */
export function AppSidebar({ agents, apps, onCreateAgent, onEditAgent }: AppSidebarProps) {
  const view = useNavStore((s) => s.view);
  const setView = useNavStore((s) => s.setView);
  const agent = useChatStore((s) => s.agent);
  const setAgent = useChatStore((s) => s.setAgent);
  const streaming = useChatStore((s) => s.streaming);
  const openList = useWorkflowStudioStore((s) => s.openList);
  const listOpen = useWorkflowStudioStore((s) => s.listOpen && s.listAgent === null);
  const mapOpen = useWorkflowStudioStore((s) => s.mapOpen);
  const setMapOpen = useWorkflowStudioStore((s) => s.setMapOpen);
  const inboxOpen = useWorkflowStudioStore((s) => s.inboxOpen);
  const setInboxOpen = useWorkflowStudioStore((s) => s.setInboxOpen);
  const count = useInboxCount();
  const pending = count ?? 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center gap-1.5 px-3">
        <SuiteSwitcher />
        <AtelierBrand />
      </div>

      <nav aria-label="Navigation principale" className="flex flex-col gap-px px-3 pb-3">
        <NavItem icon={House} label="Accueil" active={view === "home"} onClick={() => setView("home")} />
        <NavItem
          icon={Waypoints}
          label="Workflows"
          ariaLabel="Workflows de suite"
          title="Workflows de suite : enchaîner Convert, Tab, Viz, Projets… en graphe"
          active={listOpen}
          onClick={() => openList(null)}
        />
        <NavItem
          icon={MapIcon}
          label="Carte de la suite"
          title="Carte de la suite : entrées, sorties, agents"
          active={mapOpen}
          onClick={() => setMapOpen(true)}
        />
        <NavItem
          icon={Inbox}
          label="À valider"
          ariaLabel={count === null ? "À valider" : inboxLabel(pending)}
          title="Étapes des workflows en attente de votre accord"
          active={inboxOpen}
          onClick={() => setInboxOpen(true)}
          badge={pending > 0 ? badgeText(pending) : undefined}
        />
      </nav>

      <div className="mx-3 border-t border-atelier-line" />

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pt-3 pb-4">
        <AgentSidebar
          agents={agents}
          active={view === "agents" ? agent : null}
          disabled={streaming}
          onSelect={(name) => {
            setAgent(name);
            setView("agents");
          }}
          onCreate={onCreateAgent}
          onEdit={onEditAgent}
        />
      </div>

      <div className="flex shrink-0 items-center gap-1 border-t border-atelier-line px-2 py-2">
        {apps.length > 0 && <AppsMenu apps={apps} />}
        <ThemeToggle className="ml-auto scale-90" />
        <SettingsButton />
      </div>
    </div>
  );
}

function NavItem({
  icon: Icon,
  label,
  ariaLabel,
  title,
  active,
  badge,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  ariaLabel?: string;
  title?: string;
  active?: boolean;
  badge?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-current={active ? "page" : undefined}
      title={title}
      onClick={onClick}
      className={cn(
        "flex h-8 w-full items-center gap-2.5 rounded-lg px-2 text-left text-[13px] font-medium transition-colors",
        active ? "atelier-nav-active" : "text-foreground/85 hover:bg-accent hover:text-foreground",
      )}
    >
      <Icon className={cn("size-4 shrink-0", active ? "text-accent-ink" : "text-muted-foreground")} aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {badge && (
        <span
          aria-hidden
          className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1.5 text-[10px] leading-none font-semibold text-primary-foreground tabular-nums shadow-signature-glow"
        >
          {badge}
        </span>
      )}
    </button>
  );
}
