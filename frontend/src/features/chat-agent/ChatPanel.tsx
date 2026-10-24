"use client";

import { ArrowUpRight, Lock, SquarePen, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { AppChip } from "@/components/layout/AppChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { emptyConversation } from "@/features/chat-agent/conversation";
import { WorkflowEditor } from "@/features/workflows/WorkflowEditor";
import { WorkflowsDialog } from "@/features/workflows/WorkflowsDialog";
import { useChatStore } from "@/stores/useChatStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, AttachmentBlock, ProviderStatus } from "@/types/api";

import { AgentTile } from "./AgentTile";
import { agentApps } from "./agentApps";
import { Composer } from "./Composer";
import { ConversationHistory } from "./ConversationHistory";
import { MessageList } from "./MessageList";
import { ProviderPicker } from "./ProviderPicker";
import { toolLabel } from "./ToolCall";

/** Exemples proposés quand l'agent n'en fournit pas. */
const FALLBACK_STARTERS = [
  "Que sais-tu faire ?",
  "Quel jour sommes-nous, et combien de semaines reste-t-il avant la fin de l'année ?",
];

export function ChatPanel({
  agent,
  agents,
  providers,
  blocked,
}: {
  agent: AgentInfo | undefined;
  /** Catalogue : noms affichés des agents dans les résultats de recherche */
  agents: AgentInfo[];
  providers: ProviderStatus[];
  blocked: string | null;
}) {
  const agentName = useChatStore((s) => s.agent);
  const conversation = useChatStore((s) => s.conversations[agentName]) ?? emptyConversation();
  const streaming = useChatStore((s) => s.streaming);
  const sendText = useChatStore((s) => s.send);
  const decideStore = useChatStore((s) => s.decide);
  const stop = useChatStore((s) => s.stop);
  const reset = useChatStore((s) => s.reset);
  const restore = useChatStore((s) => s.restore);
  const opening = useChatStore((s) => s.opening);
  const saveError = useChatStore((s) => s.saveError);
  const conversationId = useChatStore((s) => s.conversationIds[agentName] ?? null);
  // Workflows : fenêtre d'enregistrement du dernier tour ; les listes se rechargent après un ajout
  const [capturing, setCapturing] = useState(false);
  const bumpWorkflows = useWorkflowStudioStore((s) => s.bump);

  // Premier passage sur l'agent : rouvrir sa dernière conversation enregistrée
  useEffect(() => {
    void restore(agentName);
  }, [agentName, restore]);

  const label = agent?.display_name ?? agentName;
  const localOnly = agent?.local_only ?? false;
  const send = (text: string, attachments: AttachmentBlock[] = []) => sendText(text, { localOnly, attachments });
  const decide = (decisions: Record<string, boolean>) => void decideStore(decisions, { localOnly });
  const empty = conversation.turns.length === 0;
  const starters = agent?.starters?.length ? agent.starters : FALLBACK_STARTERS;
  const apps = agent ? agentApps(agent) : [];

  return (
    <section aria-label={`Conversation avec ${label}`} className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-atelier-line px-4">
        <AgentTile icon={agent?.icon} variant="glass" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-[15px] font-semibold">{label}</h1>
            {localOnly && (
              <Badge variant="secondary" title="Données traitées uniquement par le modèle local (Ollama)">
                <Lock aria-hidden />
                100 % local
              </Badge>
            )}
          </div>
          {agent?.description && (
            <p className="hidden truncate text-xs text-muted-foreground md:block">{agent.description}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <ProviderPicker agent={agent} providers={providers} className="w-28 sm:w-44" />
          {agent && <WorkflowsDialog agent={agent} />}
          <ConversationHistory agent={agentName} label={label} agents={agents} />
          {!empty && (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={reset}
              disabled={streaming}
              aria-label="Nouvelle conversation"
              title="Nouvelle conversation"
            >
              <SquarePen />
            </Button>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {opening && empty ? (
          <p role="status" className="px-6 py-10 text-center text-sm text-muted-foreground">
            Ouverture de la conversation…
          </p>
        ) : empty ? (
          <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center gap-8 px-6 py-10">
            <div className="flex flex-col items-start gap-4">
              <AgentTile icon={agent?.icon} size="lg" variant="glass" />
              <div>
                <h2 className="text-2xl font-bold tracking-tight">{label}</h2>
                <p className="mt-1.5 text-[15px] text-muted-foreground">{agent?.description}</p>
              </div>
              {apps.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">Travaille avec</span>
                  {apps.map((app) => (
                    <AppChip key={app} app={app} />
                  ))}
                </div>
              )}
              {agent && agent.tools.length > 0 && (
                <details className="group w-full text-[13px] text-muted-foreground">
                  <summary className="cursor-pointer select-none hover:text-foreground">
                    {agent.tools.length} outil{agent.tools.length >= 2 ? "s" : ""} disponible
                    {agent.tools.length >= 2 ? "s" : ""}
                  </summary>
                  <p className="mt-1.5">{agent.tools.map((t) => toolLabel(t.name)).join(", ")}.</p>
                </details>
              )}
              {localOnly && (
                <p className="flex items-start gap-2 rounded-lg border border-atelier-line bg-signature-faint px-3 py-2 text-[13px] text-muted-foreground">
                  <Lock className="mt-0.5 size-4 shrink-0 text-accent-ink" aria-hidden />
                  Cet agent travaille sur des données qui ne quittent pas la machine : il utilise uniquement le modèle
                  local (Ollama).
                </p>
              )}
              {agent?.unavailable_toolsets?.length ? (
                <p className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/8 px-3 py-2 text-[13px] text-warning">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  Non configuré : {agent.unavailable_toolsets.join(", ")}. Renseignez l&apos;adresse de
                  l&apos;application dans les Réglages (roue dentée en bas de la barre latérale).
                </p>
              ) : null}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {starters.map((starter) => (
                <button
                  key={starter}
                  type="button"
                  disabled={!!blocked}
                  onClick={() => void send(starter)}
                  className="group flex items-start gap-3 rounded-xl border border-atelier-line bg-card px-3.5 py-3 text-left text-[13px] leading-snug transition-[border-color,box-shadow,background-color] hover:border-atelier-border hover:shadow-glow disabled:opacity-50"
                >
                  <span className="min-w-0 flex-1">{starter}</span>
                  <ArrowUpRight
                    className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-accent-ink"
                    aria-hidden
                  />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <MessageList
            turns={conversation.turns}
            streaming={streaming}
            agent={agent}
            onDecide={decide}
            onSaveWorkflow={agent ? () => setCapturing(true) : undefined}
          />
        )}
      </div>

      {saveError && !blocked && (
        <p role="status" className="mx-auto w-full max-w-3xl px-4 pb-2 text-xs text-muted-foreground">
          {saveError}
        </p>
      )}
      {blocked && (
        <p role="status" className="mx-auto w-full max-w-3xl px-4 pb-2 text-sm text-destructive">
          {blocked}
        </p>
      )}
      {capturing && agent && (
        <WorkflowEditor
          agent={agent}
          source={{ kind: "capture", messages: conversation.history, conversationId }}
          onOpenChange={setCapturing}
          onSaved={bumpWorkflows}
        />
      )}
      <Composer
        agentName={label}
        streaming={streaming}
        disabled={!!blocked}
        onSend={(text, attachments) => void send(text, attachments)}
        onStop={stop}
      />
    </section>
  );
}
