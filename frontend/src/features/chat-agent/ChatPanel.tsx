"use client";

import { Lock, Settings, SquarePen } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { emptyConversation, pendingApproval } from "@/features/chat-agent/conversation";
import { WorkflowEditor } from "@/features/workflows/WorkflowEditor";
import { WorkflowsDialog } from "@/features/workflows/WorkflowsDialog";
import { PROVIDER_SHORT, effectiveProvider } from "@/lib/labels";
import { useChatStore } from "@/stores/useChatStore";
import { useUiStore } from "@/stores/useUiStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, AttachmentBlock, ProviderStatus } from "@/types/api";

import { AgentTile } from "./AgentTile";
import { AgentWelcome, ThreadSkeleton } from "./AgentWelcome";
import { Composer } from "./Composer";
import { ConversationHistory } from "./ConversationHistory";
import { DecisionDock } from "./DecisionDock";
import { MessageList } from "./MessageList";
import { ProviderPicker } from "./ProviderPicker";
import { type LiveSnapshot, liveMessage } from "./thread";

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
  /** Catalogue : noms affichés des agents (recherche, délégations) */
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
  const choice = useChatStore((s) => s.provider);
  const conversationId = useChatStore((s) => s.conversationIds[agentName] ?? null);
  const openSettings = useUiStore((s) => s.openSettings);
  // Workflows : fenêtre d'enregistrement du dernier tour ; les listes se rechargent après un ajout
  const [capturing, setCapturing] = useState(false);
  const bumpWorkflows = useWorkflowStudioStore((s) => s.bump);
  // Dock de décision : conteneur qui défile et carte de validation en attente
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const [pendingCard, setPendingCard] = useState<HTMLElement | null>(null);

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
  const agentLabel = (name: string) => agents.find((a) => a.name === name)?.display_name ?? name;
  const pending = pendingApproval(conversation);
  const pendingKey = pending ? pending.calls.map((c) => c.id).join("-") : null;
  // Blocage dû au moteur choisi (et non au serveur) : on propose les Réglages
  const engine = providers.find((p) => p.name === effectiveProvider(agent, choice, providers));
  const engineMissing = !!blocked && !!engine && !engine.configured;

  return (
    <section aria-label={`Conversation avec ${label}`} className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* Sous lg, la barre mobile (AppHeader) montre déjà l'agent : ici, seulement ses badges et
          les actions de la conversation (le titre reste pour les lecteurs d'écran) */}
      <header className="flex h-11 shrink-0 items-center gap-3 border-b border-atelier-line px-4 lg:h-14">
        <AgentTile icon={agent?.icon} className="hidden lg:grid" />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="sr-only min-w-0 text-[15px] font-semibold tracking-tight lg:not-sr-only">
              <span className="block truncate">{label}</span>
            </h1>
            {localOnly && (
              <Badge variant="signature" title="Données traitées uniquement par le modèle local (Ollama)">
                <Lock aria-hidden />
                100 % local
              </Badge>
            )}
          </div>
          {agent?.description && (
            <p className="hidden truncate text-xs text-muted-foreground lg:block">{agent.description}</p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
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

      <div className="relative flex min-h-0 flex-1 flex-col">
        <div ref={setScroller} aria-busy={opening} className="min-h-0 flex-1 overflow-y-auto">
          {opening && empty ? (
            <ThreadSkeleton />
          ) : empty ? (
            <AgentWelcome
              agent={agent}
              label={label}
              starters={starters}
              disabled={!!blocked}
              onStart={(text) => void send(text)}
            />
          ) : (
            <MessageList
              turns={conversation.turns}
              streaming={streaming}
              agent={agent}
              agentLabel={agentLabel}
              onDecide={decide}
              onSaveWorkflow={agent ? () => setCapturing(true) : undefined}
              pendingRef={setPendingCard}
              scroller={scroller}
            />
          )}
        </div>
        {/* Validation en attente hors de vue : rappel au-dessus du composer (jamais d'« Autoriser » ici) */}
        {pending && !empty && (
          <div className="pointer-events-none absolute inset-x-0 bottom-3 z-10">
            <div className="mx-auto w-full max-w-3xl px-4">
              <DecisionDock key={pendingKey} target={pendingCard} root={scroller} count={pending.calls.length} />
            </div>
          </div>
        )}
      </div>

      {(blocked || saveError) && (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-2 px-4 pb-2">
          {blocked && engineMissing && engine ? (
            <Callout
              tone="warning"
              role="status"
              action={
                <Button size="sm" variant="outline" onClick={openSettings}>
                  <Settings />
                  Ouvrir les réglages
                </Button>
              }
            >
              {localOnly
                ? `${PROVIDER_SHORT[engine.name]} n'est pas configuré : cet agent n'utilise que le modèle local, renseignez-le dans les Réglages.`
                : `${PROVIDER_SHORT[engine.name]} n'est pas configuré : choisissez un autre moteur en bas de la zone de saisie, ou renseignez-le dans les Réglages.`}
            </Callout>
          ) : blocked ? (
            <Callout tone="destructive" role="status">
              {blocked}
            </Callout>
          ) : (
            <p role="status" className="text-xs text-muted-foreground">
              {saveError}
            </p>
          )}
        </div>
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
        engine={<ProviderPicker agent={agent} providers={providers} />}
      />
      <LiveRegion
        streaming={streaming}
        pending={pendingKey}
        failed={!!conversation.turns.at(-1)?.error}
      />
    </section>
  );
}

/**
 * Région lue par les lecteurs d'écran : « Réponse terminée », « Validation demandée »…
 * L'état précédent est gardé d'un rendu à l'autre (mise à jour pendant le rendu, sans effet) ;
 * chaque annonce est un nouveau nœud, pour qu'un même texte soit relu. La région reste montée
 * d'un agent et d'une conversation à l'autre : une validation en attente dans une conversation
 * rouverte depuis l'historique (même d'un autre agent) est annoncée comme en direct.
 */
function LiveRegion(snapshot: LiveSnapshot) {
  const { streaming, pending, failed } = snapshot;
  const [state, setState] = useState({ before: snapshot, message: "", seq: 0 });
  const { before } = state;
  if (before.streaming !== streaming || before.pending !== pending || before.failed !== failed) {
    const message = liveMessage(before, snapshot);
    setState({
      before: { streaming, pending, failed },
      message: message ?? state.message,
      seq: message ? state.seq + 1 : state.seq,
    });
  }
  return (
    <div role="status" aria-live="polite" className="sr-only">
      <span key={state.seq}>{state.message}</span>
    </div>
  );
}
