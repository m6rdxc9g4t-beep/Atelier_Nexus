"use client";

import { CircleCheck, CopyPlus, LibraryBig, ListChecks, RefreshCw, Sparkles, TriangleAlert, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SectionLabel } from "@/components/ui/section-label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { WorkflowTemplate } from "@/types/api";

import { AppChain } from "./AppChain";
import { missingLines, orderTemplates, stepsText, templateTarget } from "./studio";

export type LibraryState =
  | { status: "loading" }
  /** Serveur plus ancien, sans bibliothèque de modèles (404) */
  | { status: "missing" }
  | { status: "error"; message: string }
  | { status: "ready"; templates: WorkflowTemplate[] };

/** Modèles de workflows de la suite (GET /api/workflows/library), relus à la demande. */
export function useWorkflowLibrary(): { state: LibraryState; reload: () => void } {
  const [state, setState] = useState<LibraryState>({ status: "loading" });
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .workflowLibrary(ctrl.signal)
      .then((templates) => setState({ status: "ready", templates }))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) setState({ status: "missing" });
        else setState({ status: "error", message: err instanceof ApiError ? err.message : "Le serveur ne répond pas." });
      });
    return () => ctrl.abort();
  }, [refresh]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setRefresh((r) => r + 1);
  }, []);
  return { state, reload };
}

/** Copie le modèle dans un nouveau brouillon de l'éditeur en graphe (rien n'est enregistré). */
function useStartFromTemplate() {
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  return (template: WorkflowTemplate) => openEditor(templateTarget(template));
}

function AvailabilityBadge({ available }: { available: boolean }) {
  return available ? (
    <Badge variant="success" title="Toutes les étapes sont connues et leurs applications répondent">
      <CircleCheck aria-hidden />
      Disponible
    </Badge>
  ) : (
    <Badge variant="warning" title="Une application ou une étape manque sur cette machine">
      <TriangleAlert aria-hidden />
      Indisponible
    </Badge>
  );
}

/**
 * Carte d'un modèle : titre, chaîne d'applications, description, bénéfice, déclencheur conseillé,
 * prérequis, ce qui manque, « Utiliser ce modèle ». `compact` (accueil) : titre, chaîne, bénéfice.
 */
export function TemplateCard({ template, compact = false }: { template: WorkflowTemplate; compact?: boolean }) {
  const startFrom = useStartFromTemplate();
  const missing = missingLines(template.missing);
  return (
    <Card variant="interactive" className="h-full gap-3 p-4">
      <div className="flex items-start gap-2">
        <h3 className="min-w-0 flex-1 text-sm leading-snug font-semibold">{template.title}</h3>
        <AvailabilityBadge available={template.available} />
      </div>
      <AppChain apps={template.apps} max={compact ? 4 : 5} />
      {compact ? (
        <p className="line-clamp-3 text-[13px] text-muted-foreground">{template.value || template.description}</p>
      ) : (
        <>
          {template.description && <p className="text-[13px] text-muted-foreground">{template.description}</p>}
          {template.value && (
            <p className="flex items-start gap-1.5 text-[13px]">
              <Sparkles className="mt-0.5 size-3.5 shrink-0 text-accent-ink" aria-hidden />
              <span className="min-w-0">{template.value}</span>
            </p>
          )}
          {template.trigger_hint && (
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Zap className="mt-px size-3.5 shrink-0" aria-hidden />
              <span className="min-w-0">Déclencheur conseillé : {template.trigger_hint}</span>
            </p>
          )}
          {template.requirements.length > 0 && (
            // Repliés : la carte reste lisible, le détail est à un clic
            <details className="group/req grid gap-1">
              <summary className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground select-none hover:text-foreground">
                <ListChecks className="size-3.5 shrink-0" aria-hidden />
                <SectionLabel as="p" className="text-inherit">
                  Prérequis ({template.requirements.length})
                </SectionLabel>
              </summary>
              <ul className="mt-1 grid gap-0.5 pl-5 text-xs text-muted-foreground">
                {template.requirements.map((req) => (
                  <li key={req} className="list-disc">
                    {req}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {!template.available && missing.length > 0 && (
            <Callout tone="warning" title="Ce qui manque sur cette machine" className="text-xs">
              <ul className="grid gap-0.5">
                {missing.map((m) => (
                  <li key={m.text} title={m.detail ?? undefined}>
                    {m.text}
                  </li>
                ))}
              </ul>
            </Callout>
          )}
        </>
      )}
      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-1">
        <Button
          size="sm"
          variant={template.available ? "soft" : "outline"}
          title={template.available ? undefined : "Le brouillon s'ouvre quand même : l'éditeur signale les étapes à corriger"}
          onClick={() => startFrom(template)}
        >
          <CopyPlus />
          Utiliser ce modèle
        </Button>
        {!compact && (
          <span className="text-xs text-muted-foreground">{stepsText(template.steps.length, template.params.length)}</span>
        )}
      </div>
    </Card>
  );
}

/** Cartes fantômes pendant la lecture des modèles (la grille ne saute pas). */
export function TemplateSkeletons({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div role="status" aria-label="Lecture des modèles de la suite" className={className}>
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-56 rounded-xl" />
      ))}
    </div>
  );
}

/** Message d'un serveur sans modèles ou en erreur (galerie et accueil). */
export function LibraryProblem({ state, onRetry }: { state: LibraryState; onRetry: () => void }) {
  if (state.status === "missing")
    return (
      <Callout tone="info" title="Pas encore de modèles sur ce serveur">
        Cette version du serveur Atelier Nexus ne propose pas de modèles de workflows. Mettez-le à jour, ou composez un
        workflow vous-même.
      </Callout>
    );
  if (state.status === "error")
    return (
      <Callout
        tone="destructive"
        title="Modèles indisponibles"
        action={
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RefreshCw />
            Réessayer
          </Button>
        }
      >
        {state.message}
      </Callout>
    );
  return null;
}

const GRID = "grid gap-3 md:grid-cols-2 2xl:grid-cols-3";

/**
 * Galerie « Modèles de la suite » : des enchaînements prêts à l'emploi entre Convert, Tab, Viz et
 * Projets. Un modèle n'est jamais exécuté tel quel : il est copié dans un brouillon que
 * l'utilisateur relit, enregistre puis lance, chaque étape attendant sa validation.
 */
export function TemplateGallery() {
  const { state, reload } = useWorkflowLibrary();
  const ready = state.status === "ready" ? orderTemplates(state.templates) : [];
  const available = ready.filter((t) => t.available).length;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
        <p className="max-w-3xl min-w-0 flex-1 text-[13px] text-muted-foreground">
          Des enchaînements prêts à l&apos;emploi entre vos applications. Le modèle est copié dans un brouillon que vous
          relisez et enregistrez ; à l&apos;exécution, chaque étape attend votre accord.
        </p>
        {state.status === "ready" && ready.length > 0 && (
          <p className="text-xs text-muted-foreground tabular-nums" aria-live="polite">
            {ready.length} modèle{ready.length >= 2 ? "s" : ""} · {available} disponible{available >= 2 ? "s" : ""}
          </p>
        )}
      </div>
      {state.status === "loading" && <TemplateSkeletons className={GRID} />}
      <LibraryProblem state={state} onRetry={reload} />
      {state.status === "ready" &&
        (ready.length === 0 ? (
          <EmptyState icon={LibraryBig} title="Aucun modèle pour l'instant">
            Le serveur ne publie aucun modèle de workflow de suite.
          </EmptyState>
        ) : (
          <ul className={GRID}>
            {ready.map((template) => (
              <li key={template.slug} className="min-w-0">
                <TemplateCard template={template} />
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}
