"use client";

import { Lock, RotateCcw, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { emptyConversation } from "@/features/chat-agent/conversation";
import { useChatStore } from "@/stores/useChatStore";
import type { AgentInfo } from "@/types/api";

import { AgentIcon } from "./agentMeta";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { toolLabel } from "./ToolCall";

/** Exemples proposés quand l'agent n'en fournit pas. */
const FALLBACK_STARTERS = [
  "Que sais-tu faire ?",
  "Quel jour sommes-nous, et combien de semaines reste-t-il avant la fin de l'année ?",
];

export function ChatPanel({ agent, blocked }: { agent: AgentInfo | undefined; blocked: string | null }) {
  const agentName = useChatStore((s) => s.agent);
  const conversation = useChatStore((s) => s.conversations[agentName]) ?? emptyConversation();
  const streaming = useChatStore((s) => s.streaming);
  const sendText = useChatStore((s) => s.send);
  const decideStore = useChatStore((s) => s.decide);
  const stop = useChatStore((s) => s.stop);
  const reset = useChatStore((s) => s.reset);

  const label = agent?.display_name ?? agentName;
  const localOnly = agent?.local_only ?? false;
  const send = (text: string) => sendText(text, { localOnly });
  const decide = (decisions: Record<string, boolean>) => void decideStore(decisions, { localOnly });
  const empty = conversation.turns.length === 0;
  const starters = agent?.starters?.length ? agent.starters : FALLBACK_STARTERS;

  return (
    <section aria-label={`Conversation avec ${label}`} className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
        <AgentIcon icon={agent?.icon} className="size-4 text-primary" aria-hidden />
        <h1 className="truncate text-sm font-semibold">{label}</h1>
        {localOnly && (
          <Badge variant="secondary" title="Données traitées uniquement par le modèle local (Ollama)">
            <Lock aria-hidden />
            100 % local
          </Badge>
        )}
        <div className="ml-auto">
          {!empty && (
            <Button variant="ghost" size="sm" onClick={reset} disabled={streaming}>
              <RotateCcw />
              Nouvelle conversation
            </Button>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {empty ? (
          <div className="mx-auto flex h-full max-w-xl flex-col justify-center gap-6 px-6 py-10">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">{label}</h2>
              <p className="mt-1.5 text-muted-foreground">{agent?.description}</p>
              {agent && agent.tools.length > 0 && (
                <p className="mt-3 text-sm text-muted-foreground">
                  Outils : {agent.tools.map((t) => toolLabel(t.name)).join(", ")}.
                </p>
              )}
              {localOnly && (
                <p className="mt-3 flex items-start gap-2 text-sm text-muted-foreground">
                  <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
                  Cet agent travaille sur des données qui ne quittent pas la machine : il utilise
                  uniquement le modèle local (Ollama).
                </p>
              )}
              {agent?.unavailable_toolsets?.length ? (
                <p className="mt-3 flex items-start gap-2 text-sm text-warning">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  Non configuré : {agent.unavailable_toolsets.join(", ")}. Renseignez l&apos;adresse
                  correspondante dans backend/.env.
                </p>
              ) : null}
            </div>
            <div className="flex flex-col gap-2">
              {starters.map((starter) => (
                <button
                  key={starter}
                  type="button"
                  disabled={!!blocked}
                  onClick={() => void send(starter)}
                  className="rounded-md border bg-card px-3.5 py-2.5 text-left text-sm transition-colors hover:border-primary/50 hover:bg-accent disabled:opacity-50"
                >
                  {starter}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <MessageList turns={conversation.turns} streaming={streaming} onDecide={decide} />
        )}
      </div>

      {blocked && (
        <p role="status" className="mx-auto w-full max-w-3xl px-4 pb-2 text-sm text-destructive">
          {blocked}
        </p>
      )}
      <Composer
        agentName={label}
        streaming={streaming}
        disabled={!!blocked}
        onSend={(text) => void send(text)}
        onStop={stop}
      />
    </section>
  );
}
