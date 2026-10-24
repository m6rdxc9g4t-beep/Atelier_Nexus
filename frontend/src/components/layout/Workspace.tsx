"use client";

import { RefreshCw, ServerOff } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { AgentEditor } from "@/features/agent-editor/AgentEditor";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";
import { AgentSidebar } from "@/features/chat-agent/AgentSidebar";
import { ChainsDialog } from "@/features/chains/ChainsDialog";
import { ChatPanel } from "@/features/chat-agent/ChatPanel";
import { SuiteMapDialog } from "@/features/suite-map/SuiteMapDialog";
import { InboxDialog } from "@/features/workflow-triggers/InboxDialog";
import { WorkflowListDialog } from "@/features/workflows/WorkflowsDialog";
import { WorkflowGraphDialog } from "@/features/workflows-graph/WorkflowGraphEditor";
import { useBackend } from "@/hooks/useBackend";
import { useChains } from "@/hooks/useChains";
import { API_URL } from "@/lib/api";
import { useChainStore } from "@/stores/useChainStore";
import { useChatStore } from "@/stores/useChatStore";

import { AppHeader } from "./AppHeader";

/** Écran principal : agents · conversation · artefacts. */
export function Workspace() {
  const { agents, providers, apps, loading, error, reload } = useBackend();
  const chains = useChains(agents.length);
  const restoreChain = useChainStore((s) => s.restore);
  const openChains = useChainStore((s) => s.openLauncher);
  // Chaîne suivie au dernier passage : on la retrouve (bandeau au-dessus de la conversation)
  useEffect(() => {
    void restoreChain();
  }, [restoreChain]);
  const [editor, setEditor] = useState<{ open: boolean; editing: string | null }>({
    open: false,
    editing: null,
  });
  const agent = useChatStore((s) => s.agent);
  const setAgent = useChatStore((s) => s.setAgent);
  const streaming = useChatStore((s) => s.streaming);
  const provider = useChatStore((s) => s.provider);

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
      ? `${chosen.name === "anthropic" ? "Claude" : "Ollama"} n'est pas configuré : choisissez un autre moteur ou ouvrez les Réglages (roue dentée en haut à droite).`
      : null;

  return (
    <div className="flex h-dvh flex-col">
      <AppHeader agents={agents} providers={providers} apps={apps} onSettingsSaved={reload} />
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-60 shrink-0 overflow-y-auto border-r border-atelier-border-soft bg-sidebar lg:block">
          <AgentSidebar
            agents={agents}
            active={agent}
            disabled={streaming}
            onSelect={setAgent}
            onCreate={() => setEditor({ open: true, editing: null })}
            onEdit={(name) => setEditor({ open: true, editing: name })}
            chains={chains}
            onOpenChain={openChains}
          />
        </aside>

        {error && !agents.length && !loading ? (
          <div className="mx-auto flex max-w-md flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
            <ServerOff className="size-8 text-accent-ink" aria-hidden />
            <div>
              <h1 className="text-lg font-semibold text-shadow-glow">Le serveur Atelier Nexus ne répond pas</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                L&apos;interface attend l&apos;API sur <code className="font-mono">{API_URL}</code>. Lancez-la avec{" "}
                <code className="font-mono">uvicorn main:app --port 8100</code> dans le dossier backend.
              </p>
            </div>
            <Button variant="outline" onClick={() => void reload()}>
              <RefreshCw />
              Réessayer
            </Button>
          </div>
        ) : (
          <ChatPanel agent={current} agents={agents} blocked={blocked} chains={chains} />
        )}

        <ArtifactPanel />
      </div>

      {/* Workflows (liste, éditeur en graphe), carte de la suite, « À valider » : une fenêtre à la fois */}
      <WorkflowListDialog agents={agents} />
      <SuiteMapDialog />
      <ChainsDialog chains={chains} agents={agents} />
      <InboxDialog />
      <WorkflowGraphDialog agents={agents} />

      {editor.open && (
        <AgentEditor
          key={editor.editing ?? "nouvel-agent"}
          open
          editing={editor.editing}
          onOpenChange={(open) => setEditor((e) => ({ ...e, open }))}
          onSaved={async (name) => {
            // Sélection une fois le catalogue rechargé (sinon l'agent serait jugé inexistant)
            await reload();
            if (name) setAgent(name);
          }}
        />
      )}
    </div>
  );
}
