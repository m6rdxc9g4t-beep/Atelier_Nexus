"use client";

import { CircleAlert, PanelRight } from "lucide-react";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";

import { ApprovalCard } from "./ApprovalCard";
import type { ChatTurn } from "./conversation";
import { Markdown } from "./Markdown";
import { ToolCall } from "./ToolCall";

const PROVIDER_LABEL = { anthropic: "Claude", ollama: "Ollama" } as const;

interface MessageListProps {
  turns: ChatTurn[];
  streaming: boolean;
  onDecide: (decisions: Record<string, boolean>) => void;
}

export function MessageList({ turns, streaming, onDecide }: MessageListProps) {
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
          return (
            <div key={turn.id} className="flex justify-end">
              <div className="max-w-[85%] rounded-lg rounded-br-sm border border-atelier-border-soft bg-accent-soft px-3.5 py-2 text-[0.9375rem] whitespace-pre-wrap">
                {turn.parts.map((p) => (p.kind === "text" ? p.text : null))}
              </div>
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
              if (part.kind === "tool") return <ToolCall key={`tool-${part.id}`} part={part} />;
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
                {turn.meta.stop_reason === "max_iterations" && (
                  <Badge variant="warning">Limite d&apos;étapes atteinte</Badge>
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
