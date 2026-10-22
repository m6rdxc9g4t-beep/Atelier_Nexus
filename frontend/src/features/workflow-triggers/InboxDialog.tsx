"use client";

import { Inbox, RefreshCw, ShieldCheck, Waypoints } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ApprovalCard } from "@/features/workflows-graph/ApprovalCard";
import { usesLabel } from "@/features/workflows-graph/catalog";
import { previousStep } from "@/features/workflows-graph/run";
import { ApiError, api } from "@/lib/api";
import { decisionText, inboxTexts } from "@/lib/approval";
import { cn } from "@/lib/utils";
import { useApprovalMode } from "@/stores/useApprovalModeStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { PendingApproval, WorkflowRun } from "@/types/api";

import { OriginBadge } from "./OriginBadge";
import { badgeText, inboxLabel, inboxOrder, originText } from "./origin";
import { timeAgo } from "./summary";
import { useInboxCount } from "./useInboxCount";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Bouton de l'en-tête « À valider », avec le nombre d'exécutions en attente. */
export function InboxButton() {
  const count = useInboxCount();
  const setOpen = useWorkflowStudioStore((s) => s.setInboxOpen);
  const texts = inboxTexts(useApprovalMode());
  const pending = count ?? 0;
  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn("relative", pending > 0 && "text-foreground")}
      aria-label={count === null ? "À valider" : inboxLabel(pending)}
      title={texts.title}
      onClick={() => setOpen(true)}
    >
      <Inbox />
      <span className="hidden xl:inline">À valider</span>
      {pending > 0 && (
        <span
          aria-hidden
          className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] leading-none font-semibold text-primary-foreground tabular-nums shadow-signature-glow"
        >
          {badgeText(pending)}
        </span>
      )}
    </Button>
  );
}

type Loaded = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; runs: WorkflowRun[] };

/**
 * Boîte « À valider » : toutes les exécutions arrêtées sur une validation (chaque étape en
 * APPROVAL_MODE=every_step, les écritures sinon ; lancées à la main, par un horaire ou un
 * événement), avec la carte de validation de l'éditeur. Rien ne s'exécute sans accord.
 */
export function InboxDialog() {
  const open = useWorkflowStudioStore((s) => s.inboxOpen);
  const setOpen = useWorkflowStudioStore((s) => s.setInboxOpen);
  const texts = inboxTexts(useApprovalMode());
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] max-w-2xl flex-col gap-3">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Inbox className="size-5 text-accent-ink" aria-hidden />À valider
          </DialogTitle>
          <DialogDescription>{texts.description}</DialogDescription>
        </DialogHeader>
        {open && <InboxBody empty={texts.empty} />}
      </DialogContent>
    </Dialog>
  );
}

function InboxBody({ empty }: { empty: string }) {
  const [state, setState] = useState<Loaded>({ status: "loading" });
  const [titles, setTitles] = useState<Map<string, string>>(new Map());
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [done, setDone] = useState<{ id: string; text: string } | null>(null);
  const bumpInbox = useWorkflowStudioStore((s) => s.bumpInbox);
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);

  const load = useCallback((signal?: AbortSignal) => {
    api
      .workflowRunsByStatus("awaiting_approval", signal)
      .then((runs) => setState({ status: "ready", runs: inboxOrder(runs) }))
      .catch((err: unknown) => !signal?.aborted && setState({ status: "error", message: errorText(err, "Le serveur ne répond pas.") }));
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    return () => ctrl.abort();
  }, [load, refresh]);

  // Titres des workflows (une lecture) : l'exécution ne porte que l'identifiant
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .workflows(null, ctrl.signal)
      .then((items) => setTitles(new Map(items.map((w) => [w.id, w.title]))))
      .catch(() => undefined);
    return () => ctrl.abort();
  }, []);

  const decide = async (run: WorkflowRun, pending: PendingApproval, allow: boolean) => {
    setBusy(run.id);
    setErrors((e) => Object.fromEntries(Object.entries(e).filter(([id]) => id !== run.id)));
    try {
      const next = await api.resumeWorkflowRun(run.id, { [pending.token]: allow });
      setDone({ id: run.id, text: decisionText(allow, next.status === "awaiting_approval") });
      setState((s) =>
        s.status === "ready"
          ? { status: "ready", runs: inboxOrder(s.runs.map((r) => (r.id === run.id ? next : r))) }
          : s,
      );
      bumpInbox();
    } catch (err) {
      setErrors((e) => ({ ...e, [run.id]: errorText(err, "Reprise impossible.") }));
    } finally {
      setBusy(null);
    }
  };

  if (state.status === "loading")
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Lecture des exécutions en attente…
      </p>
    );
  if (state.status === "error")
    return (
      <div role="alert" className="flex items-center gap-2 text-sm text-destructive">
        <span className="flex-1">{state.message}</span>
        <Button size="sm" variant="outline" onClick={() => setRefresh((r) => r + 1)}>
          <RefreshCw />
          Réessayer
        </Button>
      </div>
    );

  return (
    <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] gap-2">
      <div className="flex items-center gap-2">
        <p className="flex-1 text-xs text-muted-foreground" aria-live="polite">
          {state.runs.length === 0
            ? "Rien à valider."
            : `${state.runs.length} exécution${state.runs.length >= 2 ? "s" : ""} en attente.`}
        </p>
        <Button size="sm" variant="ghost" onClick={() => setRefresh((r) => r + 1)}>
          <RefreshCw />
          Actualiser
        </Button>
      </div>
      {done && (
        <p role="status" className="rounded-md border border-success/30 bg-success/8 px-2 py-1.5 text-sm">
          {done.text}
        </p>
      )}
      {state.runs.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center text-sm text-muted-foreground">
          <ShieldCheck className="size-7 text-accent-ink" aria-hidden />
          {empty}
        </div>
      ) : (
        <ul className="grid min-h-0 grid-cols-[minmax(0,1fr)] gap-3 overflow-y-auto pr-1">
          {state.runs.map((run) => {
            const title = titles.get(run.workflow_id) ?? run.workflow_id;
            const stepLabel = (id: string) => {
              const step = run.steps.find((s) => s.id === id);
              return step ? step.label || usesLabel(step.uses) : id;
            };
            return (
              <li key={run.id} className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-lg border border-atelier-border bg-card p-3 shadow-glow">
                <header className="flex flex-wrap items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold break-words">{title}</p>
                    <p className="flex min-w-0 items-start gap-1.5 text-xs text-muted-foreground">
                      <OriginBadge trigger={run.trigger} />
                      <span className="min-w-0 break-words">{originText(run)}</span>
                    </p>
                  </div>
                  <time dateTime={run.updated_at} title={new Date(run.updated_at).toLocaleString("fr-FR")} className="shrink-0 text-xs text-muted-foreground">
                    {timeAgo(run.updated_at)}
                  </time>
                </header>
                {run.pending.map((pending) => {
                  const before = previousStep(run, pending.step_id);
                  return (
                    <ApprovalCard
                      key={pending.token}
                      pending={pending}
                      label={stepLabel(pending.step_id)}
                      previous={before && { step: before, label: stepLabel(before.id) }}
                      busy={busy !== null}
                      onDecide={(p, allow) => void decide(run, p, allow)}
                    />
                  );
                })}
                {run.pending.length === 0 && (
                  <p className="text-xs text-muted-foreground">L&apos;étape en attente n&apos;est plus disponible : ouvrez le suivi.</p>
                )}
                {errors[run.id] && (
                  <p role="alert" className="text-xs text-destructive">
                    {errors[run.id]}
                  </p>
                )}
                <div className="flex justify-end">
                  <Button size="sm" variant="ghost" onClick={() => openEditor({ kind: "open", id: run.workflow_id, panel: "run", runId: run.id })}>
                    <Waypoints />
                    Ouvrir dans l&apos;éditeur
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
