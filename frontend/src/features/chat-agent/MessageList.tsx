"use client";

import { CircleAlert, PanelRight, Workflow } from "lucide-react";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";

import { ApprovalCard } from "./ApprovalCard";
import { MessageAttachments } from "./AttachmentView";
import { type ChatTurn, type ReviewDecision, canSaveAsWorkflow } from "./conversation";
import { Markdown } from "./Markdown";
import { ReviewCard } from "./ReviewCard";
import { ToolCall } from "./ToolCall";

const PROVIDER_LABEL = { anthropic: "Claude", ollama: "Ollama" } as const;

interface MessageListProps {
  turns: ChatTurn[];
  streaming: boolean;
  onDecide: (decisions: Record<string, boolean>) => void;
  /** Mode pas à pas : réponse à la revue d'un résultat. */
  onReview: (decision: ReviewDecision) => void;
  /** « Enregistrer en workflow » sous le dernier tour réussi qui a utilisé des outils. */
  onSaveWorkflow?: () => void;
}

export function MessageList({ turns, streaming, onDecide, onReview, onSaveWorkflow }: MessageListProps) {
  const end = useRef<HTMLDivElement>(null);
  const select = useArtifactStore((s) => s.select);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
      {turns.map((turn, index) => {
        const last = index === turns.length - 1;
        if (turn.role === "user") {
          const files = turn.parts.flatMap((p) => (p.kind === "attachment" ? [p.attachment] : []));
          const text = turn.parts.map((p) => (p.kind === "text" ? p.text : "")).join("");
          return (
            <div key={turn.id} className="flex flex-col items-end gap-2">
              {files.length > 0 && <MessageAttachments items={files} />}
              {text && (
                <div className="max-w-[85%] rounded-lg rounded-br-sm border border-atelier-border-soft bg-accent-soft px-3.5 py-2 text-[0.9375rem] whitespace-pre-wrap">
                  {text}
                </div>
              )}
            </div>
          );
        }
        const thinking = last && streaming && turn.parts.length === 0;
        return (
          <article key={turn.id} className="flex flex-col gap-3" aria-busy={last && streaming}>
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
            {turn.parts.map((part, i) => {
              if (part.kind === "text") return <Markdown key={i}>{part.text}</Markdown>;
              if (part.kind === "tool") {
                // Résultat en attente de revue : déplié pour être lu avant de continuer
                const underReview = turn.parts.some(
                  (p) => p.kind === "review" && !p.decision && p.callIds.includes(part.id),
                );
                return <ToolCall key={`tool-${part.id}`} part={part} defaultOpen={underReview} />;
              }
              if (part.kind === "review")
                return (
                  <ReviewCard
                    key={`review-${part.callIds.join("-")}`}
                    part={part}
                    disabled={streaming}
                    onSubmit={onReview}
                  />
                );
              if (part.kind === "attachment") return null;
              if (part.kind === "approval")
                return (
                  <ApprovalCard
                    key={`approval-${part.calls.map((c) => c.id).join("-")}`}
                    part={part}
                    disabled={streaming}
                    onSubmit={onDecide}
                  />
                );
              return (
                <button
                  key={`artifact-${part.artifactId}`}
                  type="button"
                  onClick={() => select(part.artifactId)}
                  className="flex w-fit items-center gap-2 rounded-md border border-atelier-border bg-accent-soft px-3 py-2 text-sm text-accent-ink shadow-glow hover:border-primary"
                >
                  <PanelRight className="size-4" aria-hidden />
                  <span>{part.title}</span>
                </button>
              );
            })}
            {turn.error && (
              <p
                role="alert"
                className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/8 px-3 py-2 text-sm text-destructive"
              >
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                {turn.error}
              </p>
            )}
            {turn.meta && (
              <div className={cn("flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground")}>
                <Badge variant="outline">{PROVIDER_LABEL[turn.meta.provider]}</Badge>
                <span>{turn.meta.model}</span>
                <span aria-hidden>·</span>
                <span>
                  {turn.meta.usage.input_tokens + turn.meta.usage.output_tokens} jetons
                </span>
                {turn.meta.stop_reason === "max_tokens" && (
                  <Badge variant="warning">Réponse tronquée</Badge>
                )}
                {turn.meta.stop_reason === "awaiting_approval" && (
                  <Badge variant="warning">En attente de votre validation</Badge>
                )}
                {turn.meta.stop_reason === "awaiting_review" && (
                  <Badge variant="warning">Résultat à vérifier</Badge>
                )}
                {turn.meta.stop_reason === "stopped_by_user" && (
                  <Badge variant="outline">Arrêté à votre demande</Badge>
                )}
                {turn.meta.stop_reason === "max_iterations" && (
                  <Badge variant="warning">Limite d&apos;étapes atteinte</Badge>
                )}
                {last && !streaming && onSaveWorkflow && canSaveAsWorkflow(turn) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto h-7 px-2 text-xs"
                    title="Relancer ces actions sans modèle, avec d'autres valeurs si besoin"
                    onClick={onSaveWorkflow}
                  >
                    <Workflow />
                    Enregistrer en workflow
                  </Button>
                )}
              </div>
            )}
          </article>
        );
      })}
      <div ref={end} />
    </div>
  );
}
