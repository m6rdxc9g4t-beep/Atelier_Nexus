"use client";

import { RefreshCw, ServerOff } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { AgentEditor } from "@/features/agent-editor/AgentEditor";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";
import { AgentSidebar } from "@/features/chat-agent/AgentSidebar";
import { ChatPanel } from "@/features/chat-agent/ChatPanel";
import { useBackend } from "@/hooks/useBackend";
import { API_URL } from "@/lib/api";
import { useChatStore } from "@/stores/useChatStore";

import { AppHeader } from "./AppHeader";

/** Écran principal : agents · conversation · artefacts. */
export function Workspace() {
  const { agents, providers, apps, loading, error, reload } = useBackend();
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
      ? `${chosen.name === "anthropic" ? "Claude" : "Ollama"} n'est pas configuré : choisissez un autre moteur ou complétez backend/.env.`
      : null;

  return (
    <div className="flex h-dvh flex-col">
      <AppHeader agents={agents} providers={providers} apps={apps} />
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-60 shrink-0 overflow-y-auto border-r bg-card lg:block">
          <AgentSidebar
            agents={agents}
            active={agent}
            disabled={streaming}
            onSelect={setAgent}
            onCreate={() => setEditor({ open: true, editing: null })}
            onEdit={(name) => setEditor({ open: true, editing: name })}
          />
        </aside>

        {error && !agents.length && !loading ? (
          <div className="mx-auto flex max-w-md flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
            <ServerOff className="size-8 text-muted-foreground" aria-hidden />
            <div>
              <h1 className="text-lg font-semibold">Le serveur Atelier Nexus ne répond pas</h1>
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
          <ChatPanel agent={current} blocked={blocked} />
        )}

        <ArtifactPanel />
      </div>

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
