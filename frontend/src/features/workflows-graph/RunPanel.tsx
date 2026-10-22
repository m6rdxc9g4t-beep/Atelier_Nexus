"use client";

import { Check, ChevronRight, History, Layers, Play, RefreshCw, Save, ShieldQuestion, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatWhen } from "@/features/chat-agent/formatWhen";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";
import type { CatalogEntry, PendingApproval, StepRun, WorkflowParam, WorkflowRun, WorkflowStepV2 } from "@/types/api";

import { usesLabel } from "./catalog";
import { isRunActive } from "./graph";
import { RUN_STATUS, duration, launchValues, newArtifacts, pollDelay, shouldPoll } from "./run";
import { KindBadge, StepStatusIcon } from "./StepBadges";

const message = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/**
 * Lancement et suivi d'une exécution : paramètres, interrogation tant que le moteur avance,
 * carte de validation des écritures, détail des étapes, livrables et historique.
 */
export function RunPanel({
  workflowId,
  dirty,
  params,
  steps,
  catalog,
  run,
  onRun,
  onSave,
  onShowArtifacts,
}: {
  /** null : pas encore enregistré */
  workflowId: string | null;
  dirty: boolean;
  params: WorkflowParam[];
  steps: WorkflowStepV2[];
  catalog: Map<string, CatalogEntry>;
  run: WorkflowRun | null;
  onRun: (run: WorkflowRun) => void;
  /** Enregistre le brouillon ; renvoie l'identifiant (null si refusé) */
  onSave: () => Promise<string | null>;
  onShowArtifacts: () => void;
}) {
  const ids = useId();
  const [typed, setValues] = useState<Record<string, string>>({});
  // Paramètres ajoutés ou retirés pendant l'édition : défauts à jour, saisie conservée
  const values = launchValues(params, typed);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<WorkflowRun[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const attempt = useRef(0);
  const seen = useRef(new Set<string>());
  const addArtifact = useArtifactStore((s) => s.add);
  const runStatus = run?.status;

  /** Toute exécution reçue : affichée sur le graphe, livrables envoyés au panneau Artefacts. */
  const receive = (next: WorkflowRun) => {
    onRun(next);
    for (const artifact of newArtifacts(next, seen.current)) addArtifact(artifact, `workflow:${next.workflow_id}`, false);
  };

  // Interrogation tant que le moteur avance (pas pendant une validation)
  useEffect(() => {
    if (!run || !shouldPoll(run)) return;
    let alive = true;
    const timer = setTimeout(() => {
      api
        .workflowRun(run.id)
        .then((next) => {
          if (!alive) return;
          attempt.current += 1;
          receive(next);
        })
        .catch((err: unknown) => alive && setError(message(err, "Suivi de l'exécution interrompu.")));
    }, pollDelay(attempt.current));
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // `receive` change à chaque rendu ; seule l'exécution relance l'interrogation
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  // Historique : rechargé au changement de workflow et à chaque fin d'exécution
  useEffect(() => {
    if (!workflowId) return;
    const ctrl = new AbortController();
    api
      .workflowRuns(workflowId, 20, ctrl.signal)
      .then((items) => {
        setHistory(items);
        setHistoryError(null);
      })
      .catch((err: unknown) => !ctrl.signal.aborted && setHistoryError(message(err, "Historique indisponible.")));
    return () => ctrl.abort();
  }, [workflowId, runStatus]);

  const launch = async () => {
    setBusy(true);
    setError(null);
    try {
      const id = dirty || !workflowId ? await onSave() : workflowId;
      if (!id) return;
      attempt.current = 0;
      receive(await api.runWorkflowV2(id, values));
    } catch (err) {
      setError(message(err, "Lancement impossible."));
    } finally {
      setBusy(false);
    }
  };

  const decide = async (pending: PendingApproval, allow: boolean) => {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      attempt.current = 0;
      receive(await api.resumeWorkflowRun(run.id, { [pending.token]: allow }));
    } catch (err) {
      setError(message(err, "Reprise impossible."));
    } finally {
      setBusy(false);
    }
  };

  const reopen = async (id: string) => {
    setError(null);
    try {
      attempt.current = 0;
      receive(await api.workflowRun(id));
    } catch (err) {
      setError(message(err, "Exécution introuvable."));
    }
  };

  const active = isRunActive(run);
  const awaiting = run?.status === "awaiting_approval";
  const label = (id: string) => {
    const step = steps.find((s) => s.id === id);
    return step ? step.label || usesLabel(step.uses, catalog.get(step.uses)) : id;
  };

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      {!workflowId && (
        <p className="rounded-md border border-atelier-line bg-sunken px-3 py-2 text-xs text-muted-foreground">
          Le workflow sera enregistré avant son premier lancement.
        </p>
      )}

      {!awaiting && (
        <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-launch`}>
          <h3 id={`${ids}-launch`} className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Lancement
          </h3>
          {params.map((param) => (
            <div key={param.name} className="grid grid-cols-[minmax(0,1fr)] gap-1">
              <label htmlFor={`${ids}-${param.name}`} className="text-xs font-medium">
                {param.label || param.name}
              </label>
              <Input
                id={`${ids}-${param.name}`}
                className="h-8"
                value={values[param.name] ?? ""}
                placeholder={param.default}
                maxLength={500}
                onChange={(e) => setValues((v) => ({ ...v, [param.name]: e.target.value }))}
              />
            </div>
          ))}
          <Button type="button" disabled={busy || active || steps.length === 0} onClick={() => void launch()}>
            {dirty || !workflowId ? <Save /> : <Play />}
            {busy ? "Lancement…" : active ? "Exécution en cours…" : dirty || !workflowId ? "Enregistrer et lancer" : run ? "Relancer" : "Lancer"}
          </Button>
        </section>
      )}

      {error && (
        <div role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <span className="min-w-0 flex-1">{error}</span>
          {run && (
            <Button type="button" size="sm" variant="outline" className="h-7" onClick={() => void reopen(run.id)}>
              <RefreshCw />
              Réessayer
            </Button>
          )}
        </div>
      )}

      {run && (
        <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-run`} aria-live="polite">
          <div className="flex items-center gap-2">
            <h3 id={`${ids}-run`} className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Exécution
            </h3>
            <Badge variant={RUN_STATUS[run.status].variant}>{RUN_STATUS[run.status].label}</Badge>
            <span className="ml-auto text-[11px] text-muted-foreground">{formatWhen(run.created_at)}</span>
          </div>
          {run.message && <p className="text-sm">{run.message}</p>}

          {run.pending.map((pending) => (
            <ApprovalCard key={pending.token} pending={pending} label={label(pending.step_id)} busy={busy} onDecide={decide} />
          ))}

          <ol className="grid grid-cols-[minmax(0,1fr)] gap-1">
            {run.steps.map((step) => (
              <StepRunLine key={step.id} step={step} label={label(step.id)} />
            ))}
          </ol>

          {run.artifacts.length > 0 && (
            <Button type="button" variant="outline" size="sm" onClick={onShowArtifacts}>
              <Layers />
              Voir les livrables ({run.artifacts.length})
            </Button>
          )}
        </section>
      )}

      {workflowId && (
        <section className="grid grid-cols-[minmax(0,1fr)] gap-1.5" aria-labelledby={`${ids}-history`}>
          <h3 id={`${ids}-history`} className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            <History className="size-3.5" aria-hidden />
            Historique
          </h3>
          {historyError && <p className="text-xs text-destructive">{historyError}</p>}
          {history?.length === 0 && <p className="text-xs text-muted-foreground">Jamais lancé.</p>}
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-1">
            {history?.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => void reopen(item.id)}
                  aria-current={item.id === run?.id}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md border border-atelier-line px-2 py-1.5 text-left text-xs hover:bg-accent focus-visible:shadow-focus",
                    item.id === run?.id && "atelier-nav-active",
                  )}
                >
                  <Badge variant={RUN_STATUS[item.status].variant}>{RUN_STATUS[item.status].label}</Badge>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{item.message || `${item.steps.length} étape(s)`}</span>
                  <span className="shrink-0 text-muted-foreground">{formatWhen(item.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function ApprovalCard({
  pending,
  label,
  busy,
  onDecide,
}: {
  pending: PendingApproval;
  label: string;
  busy: boolean;
  onDecide: (pending: PendingApproval, allow: boolean) => void;
}) {
  return (
    <section aria-label="Action à valider" className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-lg border border-warning/50 bg-warning/8 p-3">
      <header className="flex items-center gap-2 text-sm font-medium">
        <ShieldQuestion className="size-4 shrink-0 text-warning" aria-hidden />
        <span className="min-w-0 flex-1">{pending.summary}</span>
        <KindBadge kind={pending.kind} />
      </header>
      <p className="text-xs text-muted-foreground">
        Étape <code className="font-mono">{pending.step_id}</code> · {label}
      </p>
      <details className="rounded-md border border-atelier-line bg-card">
        <summary className="cursor-pointer px-2 py-1 text-xs text-muted-foreground">Entrée résolue (valeurs réelles)</summary>
        <pre className="max-h-48 overflow-auto border-t border-atelier-line p-2 font-mono text-[11px] whitespace-pre-wrap">
          {JSON.stringify(pending.input, null, 2)}
        </pre>
      </details>
      <div className="flex justify-end gap-1.5">
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => onDecide(pending, false)}>
          <X />
          Refuser
        </Button>
        <Button type="button" size="sm" disabled={busy} onClick={() => onDecide(pending, true)}>
          <Check />
          Autoriser
        </Button>
      </div>
    </section>
  );
}

function StepRunLine({ step, label }: { step: StepRun; label: string }) {
  const [open, setOpen] = useState(false);
  const took = duration(step.started_at, step.ended_at);
  const data = step.data === null || step.data === undefined ? null : JSON.stringify(step.data, null, 2);
  const detail = !!(step.content || data || step.input);
  return (
    <li className="rounded-md border border-atelier-border-soft bg-sunken text-xs">
      <button
        type="button"
        aria-expanded={open}
        disabled={!detail}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left enabled:hover:text-foreground"
      >
        <ChevronRight className={cn("size-3 shrink-0 text-muted-foreground transition-transform", open && "rotate-90", !detail && "invisible")} aria-hidden />
        <StepStatusIcon status={step.status} />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {step.error_code && <code className="font-mono text-[10px] text-destructive">{step.error_code}</code>}
        {took && <span className="shrink-0 text-muted-foreground tabular-nums">{took}</span>}
      </button>
      {open && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5 border-t border-atelier-line px-2 py-2">
          {step.input && <Detail title="Entrée">{JSON.stringify(step.input, null, 2)}</Detail>}
          {step.content && <Detail title="Texte">{step.content}</Detail>}
          {data && <Detail title="Sortie structurée">{data.length > 4000 ? `${data.slice(0, 4000)}\n…` : data}</Detail>}
        </div>
      )}
    </li>
  );
}

function Detail({ title, children }: { title: string; children: string }) {
  return (
    <div>
      <p className="mb-0.5 text-[11px] text-muted-foreground">{title}</p>
      <pre className="max-h-40 overflow-auto rounded-sm border border-atelier-line bg-card p-1.5 font-mono text-[11px] whitespace-pre-wrap">
        {children}
      </pre>
    </div>
  );
}
