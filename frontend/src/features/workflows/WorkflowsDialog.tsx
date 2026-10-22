"use client";

import {
  ArrowLeft,
  Check,
  CircleAlert,
  CircleCheck,
  CircleSlash,
  Layers,
  Map as MapIcon,
  Network,
  Pencil,
  Play,
  Plus,
  ShieldQuestion,
  Trash2,
  Waypoints,
  Workflow as WorkflowIcon,
  X,
} from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { formatWhen } from "@/features/chat-agent/formatWhen";
import { toolLabel } from "@/features/chat-agent/ToolCall";
import { KindBadge } from "@/features/workflows-graph/StepBadges";
import { ApiError, api, isWorkflowV2 } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";
import { useChatStore } from "@/stores/useChatStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, AnyWorkflow, StepResult, Workflow, WorkflowRunResult } from "@/types/api";

import { allDecided, initialValues, missingParams } from "./form";
import { WorkflowEditor } from "./WorkflowEditor";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: AnyWorkflow[] };

/** Bouton « Workflows » de la conversation : ouvre la liste des workflows de l'agent (v1 et v2). */
export function WorkflowsDialog({ agent }: { agent: AgentInfo }) {
  const streaming = useChatStore((s) => s.streaming);
  const openList = useWorkflowStudioStore((s) => s.openList);
  return (
    <Button variant="ghost" size="sm" disabled={streaming} aria-label="Workflows de l'agent" onClick={() => openList(agent.name)}>
      <WorkflowIcon />
      <span className="hidden sm:inline">Workflows</span>
    </Button>
  );
}

/**
 * Liste des workflows d'un agent, ou de toute la suite (en-tête « Workflows de suite ») :
 * v2 ouverts dans l'éditeur en graphe, v1 lancés et modifiés comme avant ou convertis en v2.
 */
export function WorkflowListDialog({ agents }: { agents: AgentInfo[] }) {
  const open = useWorkflowStudioStore((s) => s.listOpen);
  const setOpen = useWorkflowStudioStore((s) => s.setListOpen);
  const agentName = useWorkflowStudioStore((s) => s.listAgent);
  const version = useWorkflowStudioStore((s) => s.version);
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const setMapOpen = useWorkflowStudioStore((s) => s.setMapOpen);
  const [editing, setEditing] = useState<{ workflow: Workflow; agent: AgentInfo } | null>(null);
  const [reload, setReload] = useState(0);
  const agent = agentName ? agents.find((a) => a.name === agentName) : undefined;

  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl grid-cols-[minmax(0,1fr)]">
          <DialogHeader>
            <DialogTitle>{agentName ? `Workflows de ${agent?.display_name ?? agentName}` : "Workflows de suite"}</DialogTitle>
            <DialogDescription>
              {agentName
                ? "Des enchaînements d'outils déjà réussis, relancés sans modèle : même résultat, tout de suite."
                : "Tous les workflows, dont ceux qui enchaînent plusieurs applications (Viz, Tab, Projets…) sans passer par un agent."}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => openEditor({ kind: "new", agent: agentName })}>
              <Plus />
              Nouveau workflow en graphe
            </Button>
            <Button size="sm" variant="outline" onClick={() => setMapOpen(true)}>
              <MapIcon />
              Carte de la suite
            </Button>
          </div>
          {open && (
            <WorkflowList
              agentName={agentName}
              agents={agents}
              version={version + reload}
              onEdit={(workflow, owner) => {
                // Une fenêtre à la fois : la liste revient quand la modification est fermée
                setOpen(false);
                setEditing({ workflow, agent: owner });
              }}
              onClose={() => setOpen(false)}
            />
          )}
        </DialogContent>
      </Dialog>
      {editing && (
        <WorkflowEditor
          agent={editing.agent}
          source={{ kind: "edit", workflow: editing.workflow }}
          onOpenChange={(o) => {
            if (o) return;
            setEditing(null);
            setOpen(true);
          }}
          onSaved={() => setReload((r) => r + 1)}
        />
      )}
    </>
  );
}

function WorkflowList({
  agentName,
  agents,
  version,
  onEdit,
  onClose,
}: {
  agentName: string | null;
  agents: AgentInfo[];
  version: number;
  onEdit: (workflow: Workflow, agent: AgentInfo) => void;
  onClose: () => void;
}) {
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [running, setRunning] = useState<{ workflow: Workflow; agent: AgentInfo } | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [converting, setConverting] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const bump = useWorkflowStudioStore((s) => s.bump);

  useEffect(() => {
    const controller = new AbortController();
    api
      .workflows(agentName, controller.signal)
      .then((items) => setState({ status: "ready", items }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: err instanceof ApiError ? err.message : "Le serveur ne répond pas." });
      });
    return () => controller.abort();
  }, [agentName, version, refresh]);

  const remove = async (id: string) => {
    setActionError(null);
    try {
      await api.deleteWorkflow(id);
    } catch (err) {
      // La liste reste affichée : on peut réessayer
      setActionError(err instanceof ApiError ? err.message : "Suppression impossible.");
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
      setActionError(err instanceof ApiError ? err.message : "Conversion impossible.");
    } finally {
      setConverting(null);
    }
  };

  if (running) {
    return (
      <RunPanel
        agent={running.agent}
        workflow={running.workflow}
        onBack={() => {
          setRunning(null);
          setRefresh((r) => r + 1);
        }}
        onShowArtifacts={onClose}
      />
    );
  }
  if (state.status === "loading") return <p className="text-sm text-muted-foreground">Chargement…</p>;
  if (state.status === "error")
    return (
      <p role="alert" className="text-sm text-destructive">
        Workflows indisponibles : {state.message}
      </p>
    );
  if (state.items.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        {agentName
          ? "Aucun workflow pour cet agent. Après une réponse réussie, utilisez « Enregistrer en workflow » sous le message de l'agent : ses actions deviennent un enchaînement à relancer. Ou composez-en un en graphe."
          : "Aucun workflow pour l'instant. Composez-en un en graphe, ou partez d'une action de la carte de la suite."}
      </p>
    );

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
      {actionError && (
        <p role="alert" className="text-sm text-destructive">
          {actionError}
        </p>
      )}
      <ul className="grid max-h-[60dvh] grid-cols-[minmax(0,1fr)] gap-2 overflow-y-auto">
        {state.items.map((wf) => {
          const v2 = isWorkflowV2(wf);
          const owner = wf.agent ? agents.find((a) => a.name === wf.agent) : undefined;
          const ownerLabel = wf.agent ? (owner?.display_name ?? wf.agent) : "Suite";
          const status = wf.last_status && wf.last_status in LAST_STATUS ? LAST_STATUS[wf.last_status as keyof typeof LAST_STATUS] : null;
          return (
            <li key={wf.id} className="rounded-md border border-atelier-border-soft bg-card p-3">
              <div className="flex flex-wrap items-start gap-2">
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5">
                    <span className="truncate text-sm font-medium">{wf.title}</span>
                    {v2 ? (
                      <Badge variant="default" title="Workflow en graphe (v2)">
                        <Waypoints aria-hidden />
                        graphe
                      </Badge>
                    ) : (
                      <Badge variant="outline" title="Workflow linéaire (v1)">
                        v1
                      </Badge>
                    )}
                  </p>
                  {wf.description && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{wf.description}</p>}
                  <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    {!agentName && (
                      <span className="inline-flex items-center gap-1">
                        {!wf.agent && <Network className="size-3" aria-hidden />}
                        {ownerLabel} ·
                      </span>
                    )}
                    <span>{wf.steps.length} étape(s)</span>
                    {wf.params.length > 0 && <span>· {wf.params.length} paramètre(s)</span>}
                    {wf.last_run_at ? (
                      <>
                        <span aria-hidden>·</span>
                        <span>lancé {formatWhen(wf.last_run_at)}</span>
                        {status && <Badge variant={status.variant}>{status.label}</Badge>}
                      </>
                    ) : (
                      <span>· jamais lancé</span>
                    )}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {confirming === wf.id ? (
                    <>
                      <Button size="sm" variant="destructive" onClick={() => void remove(wf.id)}>
                        Supprimer
                      </Button>
                      <Button size="icon-sm" variant="ghost" aria-label="Annuler" onClick={() => setConfirming(null)}>
                        <X />
                      </Button>
                    </>
                  ) : v2 ? (
                    <>
                      <Button size="icon-sm" variant="ghost" aria-label={`Supprimer ${wf.title}`} onClick={() => setConfirming(wf.id)}>
                        <Trash2 />
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => openEditor({ kind: "open", id: wf.id })}>
                        <Waypoints />
                        Ouvrir
                      </Button>
                      <Button size="sm" onClick={() => openEditor({ kind: "open", id: wf.id, panel: "run" })}>
                        <Play />
                        Lancer
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Modifier ${wf.title}`}
                        disabled={!owner}
                        title={owner ? undefined : "Agent introuvable"}
                        onClick={() => owner && onEdit(wf, owner)}
                      >
                        <Pencil />
                      </Button>
                      <Button size="icon-sm" variant="ghost" aria-label={`Supprimer ${wf.title}`} onClick={() => setConfirming(wf.id)}>
                        <Trash2 />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={converting !== null}
                        title="Enregistre une version en graphe (v2), éditable et reliable à d'autres apps"
                        onClick={() => void convert(wf.id)}
                      >
                        <Waypoints />
                        {converting === wf.id ? "Conversion…" : "Convertir"}
                      </Button>
                      <Button size="sm" disabled={!owner} onClick={() => owner && setRunning({ workflow: wf, agent: owner })}>
                        <Play />
                        Lancer
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const LAST_STATUS = {
  completed: { variant: "success", label: "réussi" },
  failed: { variant: "destructive", label: "échec" },
  stopped: { variant: "warning", label: "arrêté (refus)" },
} as const;

const STEP_ICON = {
  ok: { Icon: CircleCheck, className: "text-success", label: "réussie" },
  error: { Icon: CircleAlert, className: "text-destructive", label: "en erreur" },
  refused: { Icon: CircleSlash, className: "text-warning", label: "refusée" },
  skipped: { Icon: CircleSlash, className: "text-muted-foreground", label: "non exécutée" },
} as const;

function RunPanel({
  agent,
  workflow,
  onBack,
  onShowArtifacts,
}: {
  agent: AgentInfo;
  workflow: Workflow;
  onBack: () => void;
  onShowArtifacts: () => void;
}) {
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
      // Livrables : panneau Artefacts (CLAUDE.md « Expérience Artefacts »), pas dans la fenêtre
      const wide = window.matchMedia("(min-width: 1280px)").matches;
      for (const artifact of outcome.artifacts) addArtifact(artifact, agent.name, wide);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Lancement impossible.");
    } finally {
      setBusy(false);
    }
  };

  return (
    // Colonne bornée : un titre long est tronqué au lieu d'élargir la fenêtre
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon-sm" aria-label="Retour à la liste" onClick={onBack}>
          <ArrowLeft />
        </Button>
        <p className="min-w-0 flex-1 truncate text-sm font-medium">{workflow.title}</p>
      </div>

      {!awaiting && workflow.params.length > 0 && (
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
      )}

      {awaiting && result && (
        <section aria-label="Actions à valider" className="rounded-lg border border-warning/50 bg-warning/8 p-3">
          <header className="mb-2 flex items-center gap-2 text-sm font-medium">
            <ShieldQuestion className="size-4 text-warning" aria-hidden />
            {result.message}
          </header>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-2">
            {result.pending.map((step) => {
              const key = step.token;
              const choice = decisions[key];
              return (
                <li key={key} className="flex flex-wrap items-center gap-2 rounded-md border border-atelier-line bg-card px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm break-words">{step.summary}</p>
                    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <KindBadge kind={step.kind ?? "write"} />
                      Étape {step.index} · {toolLabel(step.tool)}
                    </p>
                  </div>
                  <div className="flex gap-1.5">
                    <Button
                      size="sm"
                      variant={choice === false ? "secondary" : "outline"}
                      aria-pressed={choice === false}
                      onClick={() => setDecisions((d) => ({ ...d, [key]: false }))}
                    >
                      <X />
                      Refuser
                    </Button>
                    <Button
                      size="sm"
                      variant={choice === true ? "default" : "outline"}
                      aria-pressed={choice === true}
                      onClick={() => setDecisions((d) => ({ ...d, [key]: true }))}
                    >
                      <Check />
                      Autoriser
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {result && !awaiting && <RunResult result={result} />}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2">
        {result && result.artifacts.length > 0 && !awaiting && (
          <Button
            variant="outline"
            onClick={() => {
              setPanelOpen(true);
              onShowArtifacts();
            }}
          >
            <Layers />
            Voir les livrables ({result.artifacts.length})
          </Button>
        )}
        {awaiting && result ? (
          <Button disabled={busy || !allDecided(result, decisions)} onClick={() => void launch(decisions)}>
            <Play />
            {busy ? "Exécution…" : "Continuer"}
          </Button>
        ) : (
          <Button
            disabled={busy || missing.length > 0}
            title={missing.length ? `À renseigner : ${missing.join(", ")}` : undefined}
            onClick={() => void launch(null)}
          >
            <Play />
            {busy ? "Exécution…" : result ? "Relancer" : "Lancer"}
          </Button>
        )}
      </div>
    </div>
  );
}

function RunResult({ result }: { result: WorkflowRunResult }) {
  const ok = result.status === "completed";
  const stopped = result.status === "stopped";
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
      <p
        role="status"
        className={cn(
          "flex items-start gap-2 rounded-md border px-3 py-2 text-sm",
          ok && "border-success/30 bg-success/8",
          stopped && "border-warning/40 bg-warning/8",
          !ok && !stopped && "border-destructive/30 bg-destructive/8 text-destructive",
        )}
      >
        {ok ? (
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
        ) : stopped ? (
          <CircleSlash className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        ) : (
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        )}
        {result.message}
      </p>
      {result.steps.length > 0 && (
        <ol className="grid grid-cols-[minmax(0,1fr)] gap-1">
          {result.steps.map((step) => (
            <StepLine key={step.index} step={step} />
          ))}
        </ol>
      )}
    </div>
  );
}

function StepLine({ step }: { step: StepResult }) {
  const [open, setOpen] = useState(false);
  const { Icon, className, label } = STEP_ICON[step.status];
  return (
    <li className="rounded-md border border-atelier-border-soft bg-sunken text-sm">
      <button
        type="button"
        aria-expanded={open}
        disabled={!step.content}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-muted-foreground enabled:hover:text-foreground"
      >
        <span className="tabular-nums">{step.index}.</span>
        <span className="min-w-0 flex-1 truncate">{toolLabel(step.tool)}</span>
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
