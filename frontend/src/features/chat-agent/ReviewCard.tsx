"use client";

import { ArrowRight, Footprints, PenLine, Square } from "lucide-react";
import { useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { ReviewDecision, ReviewPart } from "./conversation";

interface ReviewCardProps {
  part: ReviewPart;
  disabled: boolean;
  onSubmit: (decision: ReviewDecision) => void;
}

const DONE_LABEL = {
  continue: "Résultat validé : l'agent a continué",
  correct: "Corrigé",
  stop: "Arrêté après ce résultat",
} as const;

/**
 * Mode pas à pas : le résultat ci-dessus est montré AVANT que l'agent ne l'interprète.
 * Continuer, corriger (consigne lue par l'agent avec le résultat) ou arrêter le tour.
 */
export function ReviewCard({ part, disabled, onSubmit }: ReviewCardProps) {
  const [correcting, setCorrecting] = useState(false);
  const [instruction, setInstruction] = useState("");
  const id = useId();
  const decision = part.decision;
  const count = part.callIds.length;

  if (decision) {
    return (
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant={decision.action === "stop" ? "outline" : "success"}>
          <Footprints aria-hidden />
          {DONE_LABEL[decision.action]}
        </Badge>
        {decision.action === "correct" && <span className="italic">« {decision.instruction} »</span>}
      </p>
    );
  }

  return (
    <section aria-label="Résultat à valider" className="rounded-lg border border-primary/40 bg-accent-soft p-3">
      <header className="mb-2 flex items-center gap-2 text-sm font-medium">
        <Footprints className="size-4 text-accent-ink" aria-hidden />
        {count > 1 ? `Vérifiez ces ${count} résultats` : "Vérifiez ce résultat"} avant que l&apos;agent ne continue
      </header>
      <p className="mb-3 text-xs text-muted-foreground">
        Dépliez l&apos;étape ci-dessus pour voir le résultat complet. L&apos;agent ne l&apos;a pas encore lu.
      </p>
      {correcting && (
        <div className="mb-3 grid gap-1.5">
          <label htmlFor={id} className="text-xs text-muted-foreground">
            Votre consigne (l&apos;agent la lira avec le résultat)
          </label>
          <Textarea
            id={id}
            autoFocus
            rows={2}
            maxLength={2000}
            value={instruction}
            placeholder="Ex. : filtre sur 2026 seulement, ou utilise la colonne « cout »."
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && instruction.trim()) {
                e.preventDefault();
                onSubmit({ action: "correct", instruction });
              }
            }}
          />
        </div>
      )}
      <div className={cn("flex flex-wrap gap-1.5", correcting ? "justify-end" : "justify-start")}>
        {correcting ? (
          <>
            <Button size="sm" variant="ghost" disabled={disabled} onClick={() => setCorrecting(false)}>
              Annuler
            </Button>
            <Button
              size="sm"
              disabled={disabled || !instruction.trim()}
              onClick={() => onSubmit({ action: "correct", instruction })}
            >
              <ArrowRight />
              Envoyer la consigne
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" disabled={disabled} onClick={() => onSubmit({ action: "continue" })}>
              <ArrowRight />
              Continuer
            </Button>
            <Button size="sm" variant="outline" disabled={disabled} onClick={() => setCorrecting(true)}>
              <PenLine />
              Corriger
            </Button>
            <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onSubmit({ action: "stop" })}>
              <Square />
              Arrêter
            </Button>
          </>
        )}
      </div>
    </section>
  );
}
