"use client";

import {
  ArrowLeft,
  Check,
  CircleAlert,
  CircleCheck,
  CircleSlash,
  Ellipsis,
  LibraryBig,
  Layers,
  Network,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Waypoints,
  Workflow as WorkflowIcon,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card } from "@/components/ui/card";
import { DecisionCard, DecisionRow } from "@/components/ui/decision-card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { SectionLabel } from "@/components/ui/section-label";
import { Skeleton } from "@/components/ui/skeleton";
import { AgentIcon } from "@/features/chat-agent/agentMeta";
import { toolLabel } from "@/features/chat-agent/ToolCall";
import { KindBadge } from "@/features/workflows-graph/StepBadges";
import { ApiError, api, isWorkflowV2 } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";
import { useChatStore } from "@/stores/useChatStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, AnyWorkflow, StepResult, Workflow, WorkflowRunResult } from "@/types/api";

import { AppChain } from "./AppChain";
import { workflowChain } from "./chain";
import { allDecided, initialValues, missingParams } from "./form";
import { type Scope, filterWorkflows, lastRunText, lastStatus, stepsText } from "./studio";
import { WorkflowEditor } from "./WorkflowEditor";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: AnyWorkflow[] };

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Bouton « Workflows » de la conversation : ouvre le Studio sur les workflows de l'agent (v1 et v2). */
export function WorkflowsDialog({ agent }: { agent: AgentInfo }) {
  const streaming = useChatStore((s) => s.streaming);
  const openList = useWorkflowStudioStore((s) => s.openList);
  const setListSection = useWorkflowStudioStore((s) => s.setListSection);
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={streaming}
      aria-label="Workflows de l'agent"
      onClick={() => {
        openList(agent.name);
        setListSection("mine");
      }}
    >
      <WorkflowIcon />
      <span className="hidden sm:inline">Workflows</span>
    </Button>
  );
}

/**
 * « Mes workflows » (onglet Workflows du Studio) : tous les workflows enregistrés, en cartes —
 * chaîne d'applications, étapes, dernier lancement. Les workflows en graphe s'ouvrent dans
 * l'éditeur ; les workflows simples (v1, d'un seul agent) se lancent ici, se modifient dans leur
 * éditeur linéaire ou passent en graphe. La portée suit l'agent de la conversation (`listAgent`).
 */
export function MyWorkflows({ agents, onShowTemplates }: { agents: AgentInfo[]; onShowTemplates: () => void }) {
  const listAgent = useWorkflowStudioStore((s) => s.listAgent);
  const version = useWorkflowStudioStore((s) => s.version);
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const bump = useWorkflowStudioStore((s) => s.bump);
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [refresh, setRefresh] = useState(0);
  const [scope, setScope] = useState<Scope>(listAgent ? "agent" : "all");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState<{ workflow: Workflow; agent: AgentInfo } | null>(null);
  const [editing, setEditing] = useState<{ workflow: Workflow; agent: AgentInfo } | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [converting, setConverting] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Toujours la liste complète : la portée (suite, agent) et la recherche filtrent ici
  useEffect(() => {
    const controller = new AbortController();
    api
      .workflows(null, controller.signal)
      .then((items) => setState({ status: "ready", items }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: errorText(err, "Le serveur ne répond pas.") });
      });
    return () => controller.abort();
  }, [version, refresh]);

  const byName = new Map(agents.map((a) => [a.name, a]));
  const ownerName = (wf: AnyWorkflow) => (wf.agent ? (byName.get(wf.agent)?.display_name ?? wf.agent) : "Suite");
  const agentLabel = listAgent ? (byName.get(listAgent)?.display_name ?? listAgent) : null;
  const reload = () => {
    setState({ status: "loading" });
    setRefresh((r) => r + 1);
  };

  const remove = async (id: string) => {
    setActionError(null);
    try {
      await api.deleteWorkflow(id);
    } catch (err) {
      // La liste reste affichée : on peut réessayer
      setActionError(errorText(err, "Suppression impossible."));
      return;
    }
    setConfirming(null);
    setRefresh((r) => r + 1);
    bump();
  };

  const convert = async (id: string) => {
    setActionError(null);
    setConverting(id);
    try {
      const converted = await api.convertWorkflow(id);
      bump();
      openEditor({ kind: "open", id: converted.id });
    } catch (err) {
      setActionError(errorText(err, "Passage en graphe impossible."));
    } finally {
      setConverting(null);
    }
  };

  if (running) {
    return (
      <Card className="mx-auto w-full max-w-2xl gap-4 p-4">
        <RunPanel
          agent={running.agent}
          workflow={running.workflow}
          onBack={() => {
            setRunning(null);
            setRefresh((r) => r + 1);
          }}
        />
      </Card>
    );
  }

  const scopes = [
    { value: "all" as const, label: "Tous" },
    {
      value: "suite" as const,
      label: (
        <>
          <Network aria-hidden />
          Suite
        </>
      ),
      ariaLabel: "Workflows de suite (sans agent)",
    },
    ...(agentLabel ? [{ value: "agent" as const, label: agentLabel, ariaLabel: `Workflows de ${agentLabel}` }] : []),
  ];
  const items =
    state.status === "ready" ? filterWorkflows(state.items, { scope, agent: listAgent, query, ownerName }) : [];

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full min-w-0 sm:w-72">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher un workflow…"
            aria-label="Rechercher un workflow"
            className="pl-8"
          />
        </div>
        <Segmented label="Portée des workflows" value={scope} onChange={setScope} options={scopes} />
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => openEditor({ kind: "new", agent: scope === "agent" ? listAgent : null })}
        >
          <Plus />
          Nouveau workflow
        </Button>
      </div>

      {actionError && (
        <Callout tone="destructive" role="alert">
          {actionError}
        </Callout>
      )}

      {state.status === "loading" && (
        <div role="status" aria-label="Lecture des workflows" className={GRID}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      )}
      {state.status === "error" && (
        <Callout
          tone="destructive"
          title="Workflows indisponibles"
          action={
            <Button size="sm" variant="outline" onClick={reload}>
              <RefreshCw />
              Réessayer
            </Button>
          }
        >
          {state.message}
        </Callout>
      )}
      {state.status === "ready" &&
        (items.length === 0 ? (
          <EmptyState
            icon={Waypoints}
            title={query.trim() ? "Aucun workflow ne correspond" : "Aucun workflow pour l'instant"}
            actions={
              !query.trim() && (
                <>
                  <Button variant="soft" onClick={onShowTemplates}>
                    <LibraryBig />
                    Partir d&apos;un modèle
                  </Button>
                  <Button variant="outline" onClick={() => openEditor({ kind: "new", agent: scope === "agent" ? listAgent : null })}>
                    <Plus />
                    Composer en graphe
                  </Button>
                </>
              )
            }
          >
            {query.trim()
              ? "Essayez d'autres mots, ou changez de portée."
              : scope === "agent"
                ? "Après une réponse réussie, « Enregistrer en workflow » sous le message de l'agent en fait un enchaînement à relancer. Ou partez d'un modèle de la suite."
                : "Enchaînez Convert, Tab, Viz et Projets : partez d'un modèle de la suite, d'une action de la carte, ou composez votre workflow en graphe."}
          </EmptyState>
        ) : (
          <ul className={GRID}>
            {items.map((wf) => {
              const owner = wf.agent ? byName.get(wf.agent) : undefined;
              return (
                <li key={wf.id} className="min-w-0">
                  <WorkflowCard
                    wf={wf}
                    owner={owner}
                    ownerLabel={ownerName(wf)}
                    confirming={confirming === wf.id}
                    converting={converting === wf.id}
                    busy={converting !== null}
                    onRun={() =>
                      isWorkflowV2(wf)
                        ? openEditor({ kind: "open", id: wf.id, panel: "run" })
                        : owner && setRunning({ workflow: wf, agent: owner })
                    }
                    onOpen={() =>
                      isWorkflowV2(wf) ? openEditor({ kind: "open", id: wf.id }) : owner && setEditing({ workflow: wf, agent: owner })
                    }
                    onTriggers={() => openEditor({ kind: "open", id: wf.id, panel: "triggers" })}
                    onConvert={() => void convert(wf.id)}
                    onAskDelete={() => setConfirming(wf.id)}
                    onCancelDelete={() => setConfirming(null)}
                    onDelete={() => void remove(wf.id)}
                  />
                </li>
              );
            })}
          </ul>
        ))}

      {editing && (
        <WorkflowEditor
          agent={editing.agent}
          source={{ kind: "edit", workflow: editing.workflow }}
          onOpenChange={(o) => !o && setEditing(null)}
          onSaved={() => setRefresh((r) => r + 1)}
        />
      )}
    </div>
  );
}

const GRID = "grid gap-3 md:grid-cols-2 2xl:grid-cols-3";

/**
 * Carte d'un workflow : titre, agent ou « Suite », chaîne d'applications, étapes, dernier
 * lancement ; Lancer, Ouvrir (Modifier pour un workflow simple), menu ⋯. La suppression se
 * confirme dans la carte.
 */
function WorkflowCard({
  wf,
  owner,
  ownerLabel,
  confirming,
  converting,
  busy,
  onRun,
  onOpen,
  onTriggers,
  onConvert,
  onAskDelete,
  onCancelDelete,
  onDelete,
}: {
  wf: AnyWorkflow;
  owner: AgentInfo | undefined;
  ownerLabel: string;
  confirming: boolean;
  converting: boolean;
  busy: boolean;
  onRun: () => void;
  onOpen: () => void;
  onTriggers: () => void;
  onConvert: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onDelete: () => void;
}) {
  const v2 = isWorkflowV2(wf);
  // Un workflow simple appartient à un agent : sans lui (supprimé), ni lancement ni modification
  const orphan = !v2 && !owner;
  const status = wf.last_run_at ? lastStatus(wf.last_status) : null;
  const chain = workflowChain(wf.steps);
  const menuRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);

  // Confirmation annulée : le focus revient sur « ⋯ » au lieu de se perdre dans la page
  useEffect(() => {
    if (wasConfirming.current && !confirming && document.activeElement === document.body) menuRef.current?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);

  return (
    <Card variant="interactive" className={cn("h-full gap-3 p-4", confirming && "border-destructive/40")}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold" title={wf.title}>
            {wf.title}
          </h3>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
            {wf.agent ? (
              <AgentIcon icon={owner?.icon} className="size-3.5 shrink-0" aria-hidden />
            ) : (
              <Network className="size-3.5 shrink-0" aria-hidden />
            )}
            <span className="truncate">{ownerLabel}</span>
            {orphan && <span className="shrink-0 text-warning-ink">· agent introuvable</span>}
          </p>
        </div>
        {!v2 && (
          <Badge variant="outline" title="Workflow simple : les étapes d'un agent, l'une après l'autre">
            Simple
          </Badge>
        )}
      </div>

      {wf.description && <p className="line-clamp-2 text-[13px] text-muted-foreground">{wf.description}</p>}
      <AppChain apps={chain} />

      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
        <span>{stepsText(wf.steps.length, wf.params.length)}</span>
        <span aria-hidden>·</span>
        <span>{lastRunText(wf.last_run_at)}</span>
        {status && <Badge variant={status.variant}>{status.label}</Badge>}
      </p>

      {confirming ? (
        <DeleteConfirm title={wf.title} onCancel={onCancelDelete} onDelete={onDelete} />
      ) : (
        <div className="mt-auto flex items-center gap-1.5 pt-1">
          <Button size="sm" variant="soft" disabled={orphan} title={orphan ? "Agent introuvable" : undefined} onClick={onRun}>
            <Play />
            Lancer
          </Button>
          <Button size="sm" variant="outline" disabled={orphan} title={orphan ? "Agent introuvable" : undefined} onClick={onOpen}>
            {v2 ? <Waypoints /> : <Pencil />}
            {v2 ? "Ouvrir" : "Modifier"}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button ref={menuRef} size="icon-xs" variant="ghost" className="ml-auto" aria-label={`Plus d'actions pour « ${wf.title} »`}>
                <Ellipsis />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {v2 ? (
                <DropdownMenuItem onSelect={onTriggers}>
                  <Zap />
                  Déclencheurs
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem disabled={busy} onSelect={onConvert}>
                  <Waypoints />
                  {converting ? "Passage en graphe…" : "Passer en graphe"}
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem className="text-destructive-ink focus:text-destructive-ink" onSelect={onAskDelete}>
                <Trash2 />
                Supprimer…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
    </Card>
  );
}

/**
 * Suppression confirmée dans la carte. Le focus va sur « Annuler », jamais sur « Supprimer » (le
 * bouton ⋯ qui l'avait ouverte a disparu) ; Échap annule.
 */
function DeleteConfirm({ title, onCancel, onDelete }: { title: string; onCancel: () => void; onDelete: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => cancelRef.current?.focus(), []);
  return (
    <div
      role="group"
      aria-label={`Confirmer la suppression de ${title}`}
      className="mt-auto grid gap-2 border-t border-atelier-line pt-3"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        onCancel();
      }}
    >
      <p className="text-[13px] text-destructive-ink">Supprimer « {title} » ? Ses déclencheurs et son historique partent avec lui.</p>
      <div className="flex justify-end gap-1.5">
        <Button ref={cancelRef} size="sm" variant="ghost" onClick={onCancel}>
          Annuler
        </Button>
        <Button size="sm" variant="destructive" onClick={onDelete}>
          <Trash2 />
          Supprimer
        </Button>
      </div>
    </div>
  );
}

const STEP_ICON = {
  ok: { Icon: CircleCheck, className: "text-success", label: "réussie" },
  error: { Icon: CircleAlert, className: "text-destructive", label: "en erreur" },
  refused: { Icon: CircleSlash, className: "text-warning", label: "refusée" },
  skipped: { Icon: CircleSlash, className: "text-muted-foreground", label: "non exécutée" },
} as const;

/**
 * Lancement d'un workflow simple (v1) : paramètres, puis chaque étape à valider (Refuser /
 * Autoriser, une par une, jamais tout d'un coup), les étapes déjà exécutées restant visibles.
 */
function RunPanel({ agent, workflow, onBack }: { agent: AgentInfo; workflow: Workflow; onBack: () => void }) {
  const [values, setValues] = useState(() => initialValues(workflow.params));
  const [result, setResult] = useState<WorkflowRunResult | null>(null);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const addArtifact = useArtifactStore((s) => s.add);
  const setPanelOpen = useArtifactStore((s) => s.setPanelOpen);
  const ids = useId();

  const missing = missingParams(workflow.params, values);
  const awaiting = result?.status === "awaiting_approval";

  const launch = async (approvals: Record<string, boolean> | null) => {
    setBusy(true);
    setError(null);
    try {
      const outcome = await api.runWorkflow(workflow.id, values, approvals);
      setResult(outcome);
      if (outcome.status !== "awaiting_approval") setDecisions({});
      // Livrables : panneau Artefacts (CLAUDE.md « Expérience Artefacts »), pas dans le Studio
      const wide = window.matchMedia("(min-width: 1280px)").matches;
      for (const artifact of outcome.artifacts) addArtifact(artifact, agent.name, wide);
    } catch (err) {
      setError(errorText(err, "Lancement impossible."));
    } finally {
      setBusy(false);
    }
  };

  return (
    // Colonne bornée : un titre long est tronqué au lieu d'élargir la carte
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon-sm" aria-label="Retour à la liste" onClick={onBack}>
          <ArrowLeft />
        </Button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{workflow.title}</p>
          <p className="truncate text-xs text-muted-foreground">
            {agent.display_name} · {stepsText(workflow.steps.length, workflow.params.length)}
          </p>
        </div>
      </div>

      {workflow.params.length > 0 &&
        (awaiting ? (
          // Pendant la validation, les valeurs du lancement restent sous les yeux (lecture seule)
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 rounded-lg border border-atelier-line bg-sunken px-3 py-2 text-xs">
            {workflow.params.map((param) => (
              <div key={param.name} className="contents">
                <dt className="text-muted-foreground">{param.label || param.name}</dt>
                <dd className="font-mono break-words">{values[param.name] || "—"}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <div className="grid gap-2">
            {workflow.params.map((param) => (
              <div key={param.name} className="grid gap-1">
                <label htmlFor={`${ids}-${param.name}`} className="text-xs text-muted-foreground">
                  {param.label || param.name}
                </label>
                <Input
                  id={`${ids}-${param.name}`}
                  value={values[param.name] ?? ""}
                  placeholder={param.default}
                  maxLength={500}
                  onChange={(e) => setValues((v) => ({ ...v, [param.name]: e.target.value }))}
                />
              </div>
            ))}
          </div>
        ))}

      {awaiting && result && result.steps.length > 0 && (
        <div className="grid gap-1.5">
          <SectionLabel as="p">Étapes déjà exécutées</SectionLabel>
          <StepList steps={result.steps} />
        </div>
      )}

      {awaiting && result && (
        <DecisionCard
          aria-label="Actions à valider"
          heading={result.message || "Votre accord est nécessaire"}
          footer={
            <Button disabled={busy || !allDecided(result, decisions)} onClick={() => void launch(decisions)}>
              <Play />
              {busy ? "Exécution…" : "Continuer"}
            </Button>
          }
        >
          {result.pending.map((step) => {
            const key = step.token;
            const choice = decisions[key];
            const summaryId = `${ids}-pending-${key}`;
            return (
              <DecisionRow
                key={key}
                summary={step.summary}
                summaryId={summaryId}
                meta={
                  <>
                    <KindBadge kind={step.kind ?? "write"} />
                    <span>
                      Étape {step.index} · {toolLabel(step.tool)}
                    </span>
                  </>
                }
                actions={
                  <>
                    <Button
                      size="sm"
                      variant={choice === false ? "secondary" : "outline"}
                      aria-pressed={choice === false}
                      aria-describedby={summaryId}
                      onClick={() => setDecisions((d) => ({ ...d, [key]: false }))}
                    >
                      <X />
                      Refuser
                    </Button>
                    <Button
                      size="sm"
                      variant={choice === true ? "default" : "outline"}
                      aria-pressed={choice === true}
                      aria-describedby={summaryId}
                      onClick={() => setDecisions((d) => ({ ...d, [key]: true }))}
                    >
                      <Check />
                      Autoriser
                    </Button>
                  </>
                }
              />
            );
          })}
        </DecisionCard>
      )}

      {result && !awaiting && <RunResult result={result} />}

      {error && (
        <Callout tone="destructive" role="alert">
          {error}
        </Callout>
      )}

      {!awaiting && (
        <div className="flex flex-wrap justify-end gap-2">
          {result && result.artifacts.length > 0 && (
            <Button variant="outline" onClick={() => setPanelOpen(true)}>
              <Layers />
              Voir les livrables ({result.artifacts.length})
            </Button>
          )}
          <Button
            disabled={busy || missing.length > 0}
            title={missing.length ? `À renseigner : ${missing.join(", ")}` : undefined}
            onClick={() => void launch(null)}
          >
            <Play />
            {busy ? "Exécution…" : result ? "Relancer" : "Lancer"}
          </Button>
        </div>
      )}
    </div>
  );
}

function RunResult({ result }: { result: WorkflowRunResult }) {
  const ok = result.status === "completed";
  const stopped = result.status === "stopped";
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
      <Callout role="status" tone={ok ? "success" : stopped ? "warning" : "destructive"} icon={stopped ? CircleSlash : undefined}>
        {result.message}
      </Callout>
      {result.steps.length > 0 && <StepList steps={result.steps} />}
    </div>
  );
}

function StepList({ steps }: { steps: StepResult[] }) {
  return (
    <ol className="grid grid-cols-[minmax(0,1fr)] gap-1">
      {steps.map((step) => (
        <StepLine key={step.index} step={step} />
      ))}
    </ol>
  );
}

function StepLine({ step }: { step: StepResult }) {
  const [open, setOpen] = useState(false);
  const { Icon, className, label } = STEP_ICON[step.status];
  return (
    <li className="rounded-lg border border-atelier-line bg-sunken text-sm">
      <button
        type="button"
        aria-expanded={open}
        disabled={!step.content}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-muted-foreground enabled:hover:text-foreground"
      >
        <span className="tabular-nums">{step.index}.</span>
        <span className="min-w-0 flex-1 truncate">{step.label || toolLabel(step.tool)}</span>
        <Icon aria-label={label} className={cn("size-3.5", className)} />
      </button>
      {open && step.content && (
        <pre className="max-h-48 overflow-auto border-t border-atelier-line px-2.5 py-2 font-mono text-xs whitespace-pre-wrap">
          {step.content}
        </pre>
      )}
    </li>
  );
}
