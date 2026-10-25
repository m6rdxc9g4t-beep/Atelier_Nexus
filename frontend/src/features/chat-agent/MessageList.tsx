"use client";

import { ChevronRight, Info, Workflow } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { KIND_LABELS } from "@/features/artifacts/panel";
import { PROVIDER_SHORT } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";
import type { AgentInfo } from "@/types/api";

import { AgentIcon } from "./agentMeta";
import { ApprovalCard } from "./ApprovalCard";
import { MessageAttachments } from "./AttachmentView";
import { type ArtifactRefPart, type ChatTurn, canSaveAsWorkflow, replayableCount } from "./conversation";
import { Markdown } from "./Markdown";
import { groupParts } from "./thread";
import { ToolActivity } from "./ToolActivity";

interface MessageListProps {
  turns: ChatTurn[];
  streaming: boolean;
  /** Agent de la conversation : son icône et son nom signent les réponses */
  agent?: AgentInfo;
  /** Nom affiché d'un agent (délégations) */
  agentLabel: (name: string) => string;
  onDecide: (decisions: Record<string, boolean>) => void;
  /** « Enregistrer en workflow » sous le dernier tour réussi qui a utilisé des outils. */
  onSaveWorkflow?: () => void;
  /** Carte de validation en attente du dernier tour (dock de décision) */
  pendingRef?: (el: HTMLElement | null) => void;
  /** Conteneur qui défile : le fil ne suit la réponse que si l'on est resté en bas */
  scroller?: HTMLElement | null;
}

export function MessageList({
  turns,
  streaming,
  agent,
  agentLabel,
  onDecide,
  onSaveWorkflow,
  pendingRef,
  scroller,
}: MessageListProps) {
  const end = useRef<HTMLDivElement>(null);
  // Suivre la réponse tant que l'on est en bas ; remonter lire un passage arrête le suivi
  const stick = useRef(true);
  // Conversation affichée (premier tour) et nombre de tours : l'un ou l'autre change → retour en bas
  const seen = useRef({ first: turns[0]?.id, count: turns.length });

  useEffect(() => {
    if (!scroller) return;
    const onScroll = () => {
      stick.current = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    return () => scroller.removeEventListener("scroll", onScroll);
  }, [scroller]);

  useEffect(() => {
    // Nouveau message ou autre conversation (rouverte depuis l'historique) : on revient en bas
    const now = { first: turns[0]?.id, count: turns.length };
    if (now.first !== seen.current.first || now.count !== seen.current.count) {
      seen.current = now;
      stick.current = true;
    }
    if (!stick.current) return;
    // Seul le fil défile (jamais la page autour, ni sous le clavier d'un téléphone)
    if (scroller) scroller.scrollTo({ top: scroller.scrollHeight });
    else end.current?.scrollIntoView({ block: "end" });
  }, [turns, scroller]);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-8">
      {turns.map((turn, index) => {
        const last = index === turns.length - 1;
        if (turn.role === "user") return <UserTurn key={turn.id} turn={turn} />;
        return (
          <AgentTurn
            key={turn.id}
            turn={turn}
            live={last && streaming}
            streaming={streaming}
            agent={agent}
            agentLabel={agentLabel}
            onDecide={onDecide}
            onSaveWorkflow={last && !streaming ? onSaveWorkflow : undefined}
            pendingRef={last ? pendingRef : undefined}
          />
        );
      })}
      <div ref={end} />
    </div>
  );
}

function UserTurn({ turn }: { turn: ChatTurn }) {
  const files = turn.parts.flatMap((p) => (p.kind === "attachment" ? [p.attachment] : []));
  const text = turn.parts.map((p) => (p.kind === "text" ? p.text : "")).join("");
  return (
    <div className="flex flex-col items-end gap-2">
      {files.length > 0 && <MessageAttachments items={files} />}
      {text && (
        <div className="prose-chat max-w-[85%] rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 break-words whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  );
}

function AgentTurn({
  turn,
  live,
  streaming,
  agent,
  agentLabel,
  onDecide,
  onSaveWorkflow,
  pendingRef,
}: {
  turn: ChatTurn;
  /** Réponse en cours (dernier tour, flux ouvert) */
  live: boolean;
  streaming: boolean;
  agent?: AgentInfo;
  agentLabel: (name: string) => string;
  onDecide: (decisions: Record<string, boolean>) => void;
  onSaveWorkflow?: () => void;
  pendingRef?: (el: HTMLElement | null) => void;
}) {
  const name = agent?.display_name ?? "Agent";
  const thinking = live && turn.parts.length === 0;
  const replayable = onSaveWorkflow && canSaveAsWorkflow(turn) ? replayableCount(turn) : 0;
  const stop = turn.meta?.stop_reason;
  // « En attente de votre validation » : plus vrai dès que la décision est envoyée (reprise en
  // cours, ou reprise en échec), même si la méta du tour n'a pas encore été remplacée
  const lastApproval = turn.parts.findLast((p) => p.kind === "approval");
  const awaiting = stop === "awaiting_approval" && !(lastApproval?.kind === "approval" && lastApproval.submitted);

  return (
    <article aria-label={`Réponse de ${name}`} aria-busy={live} className="group/turn flex min-w-0 flex-col gap-2.5">
      <header className="flex min-h-7 items-center gap-2">
        {/* Pastille de l'agent : néon seulement pendant qu'il répond (élément « vivant ») */}
        <span
          aria-hidden
          className={cn(
            "grid size-6 shrink-0 place-items-center rounded-md border bg-signature-faint text-accent-ink transition-shadow",
            live ? "border-atelier-border shadow-glow" : "border-atelier-line",
          )}
        >
          <AgentIcon icon={agent?.icon} className="size-3.5" />
        </span>
        <span className="text-xs font-medium">{name}</span>
        {turn.meta && <TurnInfo meta={turn.meta} />}
      </header>

      <div className="flex min-w-0 flex-col gap-3">
        {thinking && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="flex gap-1" aria-hidden>
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="size-1.5 animate-pulse rounded-full bg-primary"
                  style={{ animationDelay: `${i * 160}ms` }}
                />
              ))}
            </span>
            L&apos;agent réfléchit…
          </p>
        )}
        {groupParts(turn.parts, { live }).map((segment) => {
          switch (segment.kind) {
            case "text":
              return <Markdown key={segment.key}>{segment.part.text}</Markdown>;
            case "activity":
              return <ToolActivity key={segment.key} entries={segment.entries} agentLabel={agentLabel} />;
            case "approval":
              return (
                <ApprovalCard
                  key={segment.key}
                  part={segment.part}
                  disabled={streaming}
                  onSubmit={onDecide}
                  agentLabel={agentLabel}
                  anchorRef={pendingRef}
                />
              );
            case "artifact":
              return <ArtifactLink key={segment.key} part={segment.part} />;
            case "attachment":
              return null;
          }
        })}
        {turn.error && (
          <Callout tone="destructive" role="alert">
            {turn.error}
          </Callout>
        )}
        {/* Alertes de fin de tour : toujours visibles (le reste de la méta est derrière « Infos ») */}
        {(stop === "max_tokens" || awaiting || stop === "max_iterations") && (
          <div className="flex flex-wrap gap-1.5">
            {stop === "max_tokens" && <Badge variant="warning">Réponse tronquée</Badge>}
            {awaiting && <Badge variant="warning">En attente de votre validation</Badge>}
            {stop === "max_iterations" && <Badge variant="warning">Limite d&apos;étapes atteinte</Badge>}
          </div>
        )}
        {replayable > 0 && onSaveWorkflow && <SaveSuggestion count={replayable} onSave={onSaveWorkflow} />}
      </div>
    </article>
  );
}

/** Moteur, modèle et jetons d'une réponse : derrière un bouton discret (au survol ou au clavier). */
function TurnInfo({ meta }: { meta: NonNullable<ChatTurn["meta"]> }) {
  const [open, setOpen] = useState(false);
  const tokens = (meta.usage.input_tokens + meta.usage.output_tokens).toLocaleString("fr-FR");
  // Moteur inconnu ou modèle absent (reprise sans appel au modèle) : rien de vide affiché
  const details = [PROVIDER_SHORT[meta.provider] ?? meta.provider, meta.model, `${tokens} jetons`]
    .filter(Boolean)
    .join(" · ");
  return (
    <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        aria-expanded={open}
        aria-label="Détails de la réponse"
        title={details}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "transition-opacity",
          // Pointeur fin : visible au survol du tour ou au focus ; écran tactile : toujours visible
          !open && "[@media(hover:hover)]:opacity-0 group-hover/turn:opacity-100 focus-visible:opacity-100",
        )}
      >
        <Info />
      </Button>
      {open && <span className="min-w-0 truncate">{details}</span>}
    </span>
  );
}

/** Lien vers un livrable du panneau latéral : nature, titre, « Ouvrir ». Surface calme, sans halo. */
function ArtifactLink({ part }: { part: ArtifactRefPart }) {
  const select = useArtifactStore((s) => s.select);
  const kind = useArtifactStore((s) => s.artifacts.find((a) => a.id === part.artifactId)?.kind);
  return (
    <button
      type="button"
      onClick={() => select(part.artifactId)}
      aria-label={`Ouvrir « ${part.title} »`}
      className="group/art flex w-full max-w-md items-center gap-3 rounded-xl border border-atelier-border-soft bg-card px-3 py-2.5 text-left transition-colors hover:border-atelier-border hover:bg-atelier-surface-2"
    >
      {kind && <Badge variant="signature">{KIND_LABELS[kind]}</Badge>}
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{part.title}</span>
      <span className="flex shrink-0 items-center gap-0.5 text-xs font-medium text-muted-foreground group-hover/art:text-foreground">
        Ouvrir
        <ChevronRight className="size-4 transition-transform group-hover/art:translate-x-0.5" aria-hidden />
      </span>
    </button>
  );
}

/** Suggestion après un tour réussi : enregistrer ses actions en workflow pour les rejouer sans modèle. */
function SaveSuggestion({ count, onSave }: { count: number; onSave: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-dashed border-atelier-border-soft bg-signature-faint px-3.5 py-2.5">
      <Workflow className="size-4 shrink-0 text-accent-ink" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          Rejouer {count > 1 ? `ces ${count} actions` : "cette action"} sans modèle
        </p>
        <p className="text-xs text-muted-foreground">
          Même résultat, tout de suite, avec d&apos;autres valeurs si besoin.
        </p>
      </div>
      <Button size="sm" variant="outline" onClick={onSave}>
        Enregistrer en workflow
      </Button>
    </div>
  );
}
