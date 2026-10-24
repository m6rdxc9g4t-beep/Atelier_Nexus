"use client";

import { RefreshCw, ServerOff } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { AgentEditor } from "@/features/agent-editor/AgentEditor";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";
import { ChatPanel } from "@/features/chat-agent/ChatPanel";
import { HomeView } from "@/features/home/HomeView";
import { SettingsDialog } from "@/features/settings/SettingsDialog";
import { SuiteMapDialog } from "@/features/suite-map/SuiteMapDialog";
import { InboxDialog } from "@/features/workflow-triggers/InboxDialog";
import { WorkflowListDialog } from "@/features/workflows/WorkflowsDialog";
import { WorkflowGraphDialog } from "@/features/workflows-graph/WorkflowGraphEditor";
import { useBackend } from "@/hooks/useBackend";
import { API_URL } from "@/lib/api";
import { useChatStore } from "@/stores/useChatStore";
import { useNavStore } from "@/stores/useNavStore";

import { AppHeader } from "./AppHeader";
import { AppSidebar } from "./AppSidebar";

/** Écran principal : barre latérale (navigation + agents) · accueil ou conversation · artefacts. */
export function Workspace() {
  const { agents, providers, apps, loading, error, reload } = useBackend();
  const [editor, setEditor] = useState<{ open: boolean; editing: string | null }>({
    open: false,
    editing: null,
  });
  const agent = useChatStore((s) => s.agent);
  const setAgent = useChatStore((s) => s.setAgent);
  const provider = useChatStore((s) => s.provider);
  const view = useNavStore((s) => s.view);
  const setView = useNavStore((s) => s.setView);
  const drawerOpen = useNavStore((s) => s.drawerOpen);
  const setDrawerOpen = useNavStore((s) => s.setDrawerOpen);

  // Agent inexistant (supprimé, catalogue changé) : on revient au premier disponible
  useEffect(() => {
    if (agents.length && !agents.some((a) => a.name === agent)) setAgent(agents[0]!.name);
  }, [agents, agent, setAgent]);

  const current = agents.find((a) => a.name === agent);
  const wanted = current?.local_only
    ? "ollama"
    : (provider ?? current?.default_provider ?? providers.find((x) => x.is_default)?.name);
  const chosen = providers.find((p) => p.name === wanted);
  const blocked = error
    ? error
    : chosen && !chosen.configured
      ? `${chosen.name === "anthropic" ? "Claude" : "Ollama"} n'est pas configuré : choisissez un autre moteur ou ouvrez les Réglages (roue dentée en bas de la barre latérale).`
      : null;

  const openAgent = (name: string) => {
    setAgent(name);
    setView("agents");
  };
  const sidebar = (
    <AppSidebar
      agents={agents}
      apps={apps}
      onCreateAgent={() => setEditor({ open: true, editing: null })}
      onEditAgent={(name) => setEditor({ open: true, editing: name })}
    />
  );

  return (
    <div className="flex h-dvh">
      {/* Grand écran : barre latérale fixe. Toujours montée (le choix du thème s'y applique). */}
      <aside className="hidden w-[17rem] shrink-0 border-r border-atelier-line bg-sidebar lg:block">{sidebar}</aside>
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent aria-describedby={undefined} className="lg:hidden">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Accueil, workflows, carte de la suite, agents et réglages</SheetDescription>
          {sidebar}
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader />
        <div className="flex min-h-0 flex-1">
          {error && !agents.length && !loading ? (
            <EmptyState
              icon={ServerOff}
              title="Le serveur Atelier Nexus ne répond pas"
              className="m-auto max-w-md"
              actions={
                <Button variant="outline" onClick={() => void reload()}>
                  <RefreshCw />
                  Réessayer
                </Button>
              }
            >
              L&apos;interface attend l&apos;API sur <code className="font-mono">{API_URL}</code>. Lancez-la avec{" "}
              <code className="font-mono">uvicorn main:app --port 8100</code> dans le dossier backend.
            </EmptyState>
          ) : view === "home" ? (
            <HomeView agents={agents} apps={apps} loading={loading} onOpenAgent={openAgent} />
          ) : (
            <ChatPanel agent={current} agents={agents} providers={providers} blocked={blocked} />
          )}

          <ArtifactPanel />
        </div>
      </div>

      {/* Workflows (liste, éditeur en graphe), carte de la suite, « À valider » : une fenêtre à la fois */}
      <WorkflowListDialog agents={agents} />
      <SuiteMapDialog />
      <InboxDialog />
      <WorkflowGraphDialog agents={agents} />
      <SettingsDialog onSaved={reload} />

      {editor.open && (
        <AgentEditor
          key={editor.editing ?? "nouvel-agent"}
          open
          editing={editor.editing}
          onOpenChange={(open) => setEditor((e) => ({ ...e, open }))}
          onSaved={async (name) => {
            // Sélection une fois le catalogue rechargé (sinon l'agent serait jugé inexistant)
            await reload();
            if (name) openAgent(name);
          }}
        />
      )}
    </div>
  );
}
