"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  BackgroundVariant,
  type Connection,
  Controls,
  type EdgeChange,
  MarkerType,
  MiniMap,
  type NodeChange,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import {
  CircleCheck,
  LayoutGrid,
  Monitor,
  Play,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  TriangleAlert,
  Workflow as WorkflowIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { ApiError, api, isWorkflowV2 } from "@/lib/api";
import { useArtifactStore } from "@/stores/useArtifactStore";
import { type EditorTarget, useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, Catalog, CatalogEntry, ValidationError, WorkflowRun, WorkflowStepV2, WorkflowV2 } from "@/types/api";

import { catalogIndex } from "./catalog";
import {
  type WorkflowDraftV2,
  declareMissingParams,
  draftFromWorkflow,
  draftSignature,
  emptyDraft,
  mergeErrors,
  saveBlockers,
  toBody,
  undeclaredParams,
} from "./draft";
import {
  MAX_STEPS,
  STEP_ID,
  applyLayout,
  connect,
  createStep,
  disconnect,
  mergeRunState,
  nextPosition,
  removeSteps,
  renameStep,
  stepsToEdges,
  stepsToNodes,
} from "./graph";
import { StepInspector, WorkflowSettings } from "./Inspector";
import { DRAG_MIME, Palette } from "./Palette";
import { RunPanel } from "./RunPanel";
import { StepNode } from "./StepNode";
import { validateLocal } from "./validate";

const NODE_TYPES = { step: StepNode };
const DEFAULT_EDGE = { markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 } };
const FLOW_LABELS = {
  "node.a11yDescription.default":
    "Entrée ou Espace pour sélectionner une étape ; Suppr ou Retour arrière pour la supprimer ; Échap pour annuler.",
  "node.a11yDescription.keyboardDisabled":
    "Entrée ou Espace pour sélectionner une étape, puis les flèches pour la déplacer ; Suppr pour la supprimer.",
  "node.a11yDescription.ariaLiveMessage": ({ direction, x, y }: { direction: string; x: number; y: number }) =>
    `Étape déplacée vers ${direction === "left" ? "la gauche" : direction === "right" ? "la droite" : direction === "up" ? "le haut" : "le bas"} : x ${x}, y ${y}`,
  "edge.a11yDescription.default": "Entrée ou Espace pour sélectionner une liaison ; Suppr pour la retirer.",
  "controls.ariaLabel": "Commandes du graphe",
  "controls.zoomIn.ariaLabel": "Zoom avant",
  "controls.zoomOut.ariaLabel": "Zoom arrière",
  "controls.fitView.ariaLabel": "Ajuster à l'écran",
  "controls.interactive.ariaLabel": "Verrouiller ou déverrouiller le graphe",
  "minimap.ariaLabel": "Mini-carte",
  "handle.ariaLabel": "Poignée de liaison",
};

type Loaded =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "v1"; id: string; title: string }
  | { status: "ready"; draft: WorkflowDraftV2; saved: string | null };

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Fenêtre plein écran de l'éditeur en graphe ; ouverte par le store des workflows de suite. */
export function WorkflowGraphDialog({ agents }: { agents: AgentInfo[] }) {
  const editor = useWorkflowStudioStore((s) => s.editor);
  const editorKey = useWorkflowStudioStore((s) => s.editorKey);
  const close = useWorkflowStudioStore((s) => s.closeEditor);
  const dirty = useWorkflowStudioStore((s) => s.editorDirty);
  const wide = useMediaQuery("(min-width: 1024px)");
  const [confirming, setConfirming] = useState(false);
  if (!editor) return null;
  const requestClose = () => (dirty ? setConfirming(true) : close());
  return (
    <>
      <Dialog open onOpenChange={(open) => !open && requestClose()}>
        <DialogContent
          className="flex h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-none"
          onEscapeKeyDown={(e) => {
            // Échap dans le graphe annule une sélection : on ne ferme pas la fenêtre par erreur
            if ((e.target as HTMLElement | null)?.closest(".react-flow")) e.preventDefault();
          }}
        >
          {wide ? (
            <ReactFlowProvider>
              <GraphEditor key={editorKey} target={editor} agents={agents} />
            </ReactFlowProvider>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
              <Monitor className="size-8 text-accent-ink" aria-hidden />
              <DialogTitle>Écran trop étroit</DialogTitle>
              <DialogDescription className="max-w-sm">
                L&apos;éditeur de workflows en graphe demande un écran d&apos;au moins 1024 pixels de large.
                Agrandissez la fenêtre ou ouvrez Atelier Nexus sur un ordinateur.
              </DialogDescription>
              <Button variant="outline" onClick={close}>
                Fermer
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="max-w-sm">
          <DialogTitle>Quitter sans enregistrer ?</DialogTitle>
          <DialogDescription>Les modifications de ce workflow seront perdues.</DialogDescription>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Continuer l&apos;édition
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                setConfirming(false);
                close();
              }}
            >
              Quitter
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function GraphEditor({ target, agents }: { target: EditorTarget; agents: AgentInfo[] }) {
  const [loaded, setLoaded] = useState<Loaded>(() =>
    target.kind === "new" ? { status: "ready", draft: emptyDraft(target.agent), saved: null } : { status: "loading" },
  );
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const bump = useWorkflowStudioStore((s) => s.bump);

  useEffect(() => {
    if (target.kind !== "open") return;
    const ctrl = new AbortController();
    api
      .workflow(target.id, ctrl.signal)
      .then((wf) => {
        if (!isWorkflowV2(wf)) return setLoaded({ status: "v1", id: wf.id, title: wf.title });
        const draft = draftFromWorkflow(wf);
        setLoaded({ status: "ready", draft, saved: draftSignature(draft) });
      })
      .catch((err: unknown) => !ctrl.signal.aborted && setLoaded({ status: "error", message: errorText(err, "Workflow introuvable.") }));
    return () => ctrl.abort();
  }, [target]);

  if (loaded.status === "loading")
    return (
      <Centered title="Ouverture du workflow…">
        <span />
      </Centered>
    );
  if (loaded.status === "error")
    return (
      <Centered title="Impossible d'ouvrir le workflow">
        <p role="alert" className="text-sm text-destructive">
          {loaded.message}
        </p>
      </Centered>
    );
  if (loaded.status === "v1")
    return (
      <ConvertPrompt
        id={loaded.id}
        title={loaded.title}
        onConverted={(wf) => {
          bump();
          openEditor({ kind: "open", id: wf.id });
        }}
      />
    );
  return (
    <EditorBody
      initial={loaded.draft}
      savedSignature={loaded.saved}
      initialUses={target.kind === "new" ? (target.uses ?? null) : null}
      openRun={target.kind === "open" && target.panel === "run"}
      agents={agents}
    />
  );
}

function Centered({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <DialogTitle>{title}</DialogTitle>
      <DialogDescription className="sr-only">Éditeur de workflows en graphe</DialogDescription>
      {children}
    </div>
  );
}

/** Workflow v1 : on propose la conversion (enregistrée côté serveur) avant d'ouvrir le graphe. */
export function ConvertPrompt({ id, title, onConverted }: { id: string; title: string; onConverted: (wf: WorkflowV2) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Centered title={`« ${title} » est un workflow v1`}>
      <p className="max-w-md text-sm text-muted-foreground">
        Pour l&apos;éditer en graphe, convertissez-le : ses étapes deviennent s1, s2… reliées en chaîne, et chaque{" "}
        <code className="font-mono">{"{{nom}}"}</code> devient <code className="font-mono">{"{{params.nom}}"}</code>.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          api
            .convertWorkflow(id)
            .then(onConverted)
            .catch((err: unknown) => setError(errorText(err, "Conversion impossible.")))
            .finally(() => setBusy(false));
        }}
      >
        <WorkflowIcon />
        {busy ? "Conversion…" : "Convertir en workflow v2"}
      </Button>
    </Centered>
  );
}

type SidePanel = "inspect" | "run";

function EditorBody({
  initial,
  savedSignature,
  initialUses,
  openRun,
  agents,
}: {
  initial: WorkflowDraftV2;
  savedSignature: string | null;
  initialUses: string | null;
  openRun: boolean;
  agents: AgentInfo[];
}) {
  const [draft, setDraft] = useState(initial);
  const [saved, setSaved] = useState(savedSignature);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedEdges, setSelectedEdges] = useState<Set<string>>(new Set());
  const [measured, setMeasured] = useState<Record<string, { width: number; height: number }>>({});
  const [serverErrors, setServerErrors] = useState<ValidationError[]>([]);
  const [checked, setChecked] = useState<{ ok: boolean; at: string } | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState<"validate" | "save" | null>(null);
  const [panel, setPanel] = useState<SidePanel>(openRun ? "run" : "inspect");
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const flow = useReactFlow();
  const seeded = useRef(false);
  const bump = useWorkflowStudioStore((s) => s.bump);
  const setPanelOpen = useArtifactStore((s) => s.setPanelOpen);
  const closeEditor = useWorkflowStudioStore((s) => s.closeEditor);

  // Catalogue de l'agent (ou de la suite) : rechargé si l'agent change
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .workflowCatalog(draft.agent, ctrl.signal)
      .then((c) => {
        setCatalog(c);
        setCatalogError(null);
      })
      .catch((err: unknown) => !ctrl.signal.aborted && setCatalogError(errorText(err, "Le serveur ne répond pas.")));
    return () => ctrl.abort();
  }, [draft.agent]);

  const index = useMemo(() => catalogIndex(catalog), [catalog]);
  const apps = useMemo(
    () => new Map((catalog?.apps ?? []).map((a) => [a.app, { name: a.name, color: a.color, status: a.status }])),
    [catalog],
  );
  const localErrors = useMemo(() => validateLocal({ steps: draft.steps, params: draft.params, catalog: catalog ? index : null }), [draft, catalog, index]);
  const errors = useMemo(() => mergeErrors(localErrors, serverErrors), [localErrors, serverErrors]);
  const runView = useMemo(() => mergeRunState(draft.steps, run), [draft.steps, run]);
  const signature = draftSignature(draft);
  const dirty = signature !== saved;
  const setEditorDirty = useWorkflowStudioStore((s) => s.setEditorDirty);
  useEffect(() => setEditorDirty(dirty), [dirty, setEditorDirty]);

  const nodes = useMemo(
    () => stepsToNodes(draft.steps, { catalog: index, apps, errors, run: runView, selected, measured }),
    [draft.steps, index, apps, errors, runView, selected, measured],
  );
  const edges = useMemo(() => stepsToEdges(draft.steps, runView, selectedEdges), [draft.steps, runView, selectedEdges]);

  /** Toute modification du contenu invalide le résultat de la dernière validation serveur. */
  const update = useCallback((fn: (d: WorkflowDraftV2) => WorkflowDraftV2) => {
    setDraft(fn);
    setServerErrors([]);
    setChecked(null);
  }, []);
  const setSteps = useCallback((fn: (steps: WorkflowStepV2[]) => WorkflowStepV2[]) => update((d) => ({ ...d, steps: fn(d.steps) })), [update]);

  const addStep = useCallback(
    (entry: CatalogEntry | { uses: string }, at?: { x: number; y: number }) => {
      if (draft.steps.length >= MAX_STEPS) {
        setNotice({ tone: "error", text: `${MAX_STEPS} étapes au plus.` });
        return;
      }
      const after = at ? null : selected.size === 1 ? [...selected][0]! : null;
      const step = createStep(draft.steps, entry.uses, at ?? nextPosition(draft.steps, after), after);
      setSteps((steps) => [...steps, step]);
      setSelected(new Set([step.id]));
      setSelectedEdges(new Set());
      setPanel("inspect");
    },
    [draft.steps, selected, setSteps],
  );

  // « Créer un workflow à partir de cette action » : première étape posée à l'ouverture
  useEffect(() => {
    if (!initialUses || seeded.current) return;
    seeded.current = true;
    addStep({ uses: initialUses }, { x: 0, y: 0 });
  }, [initialUses, addStep]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const moves = new Map<string, { x: number; y: number }>();
      const removed: string[] = [];
      let sel: Set<string> | null = null;
      const dims: Record<string, { width: number; height: number }> = {};
      for (const change of changes) {
        if (change.type === "position" && change.position) moves.set(change.id, change.position);
        else if (change.type === "remove") removed.push(change.id);
        else if (change.type === "select") {
          sel ??= new Set(selected);
          if (change.selected) sel.add(change.id);
          else sel.delete(change.id);
        } else if (change.type === "dimensions" && change.dimensions) dims[change.id] = change.dimensions;
      }
      if (Object.keys(dims).length) setMeasured((m) => ({ ...m, ...dims }));
      if (sel) setSelected(sel);
      if (moves.size) {
        // Déplacement : la validation reste valable (seule la position change)
        setDraft((d) => ({ ...d, steps: d.steps.map((s) => (moves.has(s.id) ? { ...s, position: moves.get(s.id)! } : s)) }));
      }
      if (removed.length) {
        setSteps((steps) => removeSteps(steps, removed));
        setSelected((s) => new Set([...s].filter((id) => !removed.includes(id))));
      }
    },
    [selected, setSteps],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      let sel: Set<string> | null = null;
      const removed: { source: string; target: string }[] = [];
      for (const change of changes) {
        if (change.type === "select") {
          sel ??= new Set(selectedEdges);
          if (change.selected) sel.add(change.id);
          else sel.delete(change.id);
        } else if (change.type === "remove") {
          const [source, target] = change.id.split("->");
          if (source && target) removed.push({ source, target });
        }
      }
      if (sel) setSelectedEdges(sel);
      if (removed.length) setSteps((steps) => removed.reduce((acc, e) => disconnect(acc, e.source, e.target), steps));
    },
    [selectedEdges, setSteps],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      const next = connect(draft.steps, c.source, c.target);
      if (!next) {
        setNotice({ tone: "error", text: "Liaison refusée : elle existe déjà ou formerait une boucle." });
        return;
      }
      setNotice(null);
      setSteps(() => next);
    },
    [draft.steps, setSteps],
  );

  const isValidConnection = useCallback(
    (c: Connection | { source: string; target: string }) => !!connect(draft.steps, c.source, c.target),
    [draft.steps],
  );

  const onDrop = (event: React.DragEvent) => {
    const uses = event.dataTransfer.getData(DRAG_MIME);
    if (!uses) return;
    event.preventDefault();
    const pos = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    addStep({ uses }, { x: Math.round(pos.x - 120), y: Math.round(pos.y - 30) });
  };

  const relayout = () => {
    setDraft((d) => ({ ...d, steps: applyLayout(d.steps) }));
    window.requestAnimationFrame(() => void flow.fitView({ padding: 0.2, duration: 250 }));
  };

  const validate = async (): Promise<boolean> => {
    setBusy("validate");
    setNotice(null);
    try {
      const result = await api.validateWorkflow(toBody(draft));
      setServerErrors(result.errors);
      setChecked({ ok: result.ok, at: signature });
      setNotice(
        result.ok
          ? { tone: "ok", text: `Workflow valide. Ordre : ${result.order.join(" → ")}.` }
          : { tone: "error", text: `${result.errors.length} problème(s) signalé(s) sur le graphe.` },
      );
      return result.ok;
    } catch (err) {
      setNotice({ tone: "error", text: errorText(err, "Validation impossible.") });
      return false;
    } finally {
      setBusy(null);
    }
  };

  const save = async (): Promise<string | null> => {
    const blockers = saveBlockers(draft);
    if (blockers.length) {
      setSelected(new Set());
      setPanel("inspect");
      setNotice({ tone: "error", text: blockers.join(" ") });
      return null;
    }
    setBusy("save");
    setNotice(null);
    try {
      const body = toBody(draft);
      const result = draft.id ? await api.updateWorkflowV2(draft.id, body) : await api.createWorkflowV2(body);
      const next = { ...draft, id: result.id };
      setDraft(next);
      setSaved(draftSignature(next));
      setServerErrors([]);
      bump();
      setNotice({ tone: "ok", text: "Workflow enregistré." });
      return result.id;
    } catch (err) {
      // 422 : erreurs de validation renvoyées par le serveur, affichées si elles ont la forme attendue
      setNotice({ tone: "error", text: errorText(err, "Enregistrement impossible.") });
      return null;
    } finally {
      setBusy(null);
    }
  };

  const selectedStep = selected.size === 1 ? draft.steps.find((s) => selected.has(s.id)) : undefined;
  const undeclared = undeclaredParams(draft);
  const errorCount = errors.length;

  const rename = (step: WorkflowStepV2) => (to: string) => {
    if (!STEP_ID.test(to)) return "Identifiant invalide : minuscule en tête, puis a-z, 0-9 ou _ (40 au plus).";
    if (draft.steps.some((s) => s.id === to)) return `« ${to} » est déjà utilisé.`;
    setSteps((steps) => renameStep(steps, step.id, to));
    setSelected(new Set([to]));
    setMeasured((m) => {
      const { [step.id]: dims, ...rest } = m;
      return dims ? { ...rest, [to]: dims } : rest;
    });
    return null;
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-atelier-border-soft bg-sidebar/85 pr-12 pl-4">
        <WorkflowIcon className="size-4 shrink-0 text-accent-ink" aria-hidden />
        <div className="min-w-0 flex-1">
          <DialogTitle className="truncate text-base">{draft.title.trim() || "Nouveau workflow"}</DialogTitle>
          <DialogDescription className="truncate text-xs">
            {draft.agent ? `Workflow de ${agents.find((a) => a.name === draft.agent)?.display_name ?? draft.agent}` : "Workflow de suite"} ·{" "}
            {draft.steps.length} étape(s)
            {dirty ? " · modifié" : draft.id ? " · enregistré" : ""}
          </DialogDescription>
        </div>
        {errorCount > 0 ? (
          <Badge variant="destructive">
            <TriangleAlert aria-hidden />
            {errorCount} problème(s)
          </Badge>
        ) : checked?.ok && checked.at === signature ? (
          <Badge variant="success">
            <CircleCheck aria-hidden />
            valide
          </Badge>
        ) : null}
        <Button variant="ghost" size="sm" onClick={relayout} disabled={draft.steps.length === 0}>
          <LayoutGrid />
          Mise en page
        </Button>
        <Button variant="outline" size="sm" onClick={() => void validate()} disabled={busy !== null || draft.steps.length === 0}>
          <ShieldCheck />
          {busy === "validate" ? "Validation…" : "Valider"}
        </Button>
        <Button size="sm" onClick={() => void save()} disabled={busy !== null || (!dirty && !!draft.id)}>
          <Save />
          {busy === "save" ? "Enregistrement…" : "Enregistrer"}
        </Button>
      </header>

      {notice && (
        <p
          role={notice.tone === "error" ? "alert" : "status"}
          className={
            notice.tone === "error"
              ? "border-b border-destructive/30 bg-destructive/8 px-4 py-1.5 text-sm text-destructive"
              : "border-b border-success/30 bg-success/8 px-4 py-1.5 text-sm"
          }
        >
          {notice.text}
        </p>
      )}

      <div className="flex min-h-0 flex-1">
        <Palette catalog={catalog} error={catalogError} onAdd={(entry) => addStep(entry)} />

        <div
          className="relative min-w-0 flex-1"
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes(DRAG_MIME)) {
              e.preventDefault();
              e.dataTransfer.dropEffect = "copy";
            }
          }}
          onDrop={onDrop}
        >
          <ReactFlow
            className="atelier-flow"
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            defaultEdgeOptions={DEFAULT_EDGE}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            onPaneClick={() => {
              setSelected(new Set());
              setSelectedEdges(new Set());
            }}
            deleteKeyCode={["Delete", "Backspace"]}
            ariaLabelConfig={FLOW_LABELS}
            fitView
            fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
            minZoom={0.2}
            maxZoom={2}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} />
            <Controls position="bottom-left" showInteractive={false} />
            <MiniMap position="bottom-right" pannable zoomable ariaLabel="Mini-carte du workflow" />
          </ReactFlow>
          {draft.steps.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-8">
              <div className="max-w-sm rounded-lg border border-dashed border-atelier-border-soft bg-card/80 p-5 text-center text-sm text-muted-foreground backdrop-blur-sm">
                <WorkflowIcon className="mx-auto mb-2 size-6 text-accent-ink" aria-hidden />
                Glissez une action de la palette ici, puis reliez la sortie d&apos;une étape à l&apos;entrée de la suivante.
              </div>
            </div>
          )}
        </div>

        <aside aria-label="Inspecteur" className="flex min-h-0 w-[22rem] shrink-0 flex-col border-l border-atelier-border-soft bg-card">
          <Tabs value={panel} onValueChange={(v) => setPanel(v as SidePanel)} className="min-h-0 flex-1 gap-0">
            <div className="border-b border-atelier-line px-3 py-2">
              <TabsList className="w-full">
                <TabsTrigger value="inspect" className="flex-1">
                  <SlidersHorizontal />
                  {selectedStep ? "Étape" : "Workflow"}
                </TabsTrigger>
                <TabsTrigger value="run" className="flex-1">
                  <Play />
                  Exécution
                </TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="inspect" className="overflow-x-hidden overflow-y-auto p-4">
              {selectedStep ? (
                <StepInspector
                  key={selectedStep.id}
                  step={selectedStep}
                  draft={draft}
                  catalog={index}
                  apps={apps}
                  errors={errors}
                  onChange={(patch) => setSteps((steps) => steps.map((s) => (s.id === selectedStep.id ? { ...s, ...patch } : s)))}
                  onRename={rename(selectedStep)}
                  onRemove={() => {
                    setSteps((steps) => removeSteps(steps, [selectedStep.id]));
                    setSelected(new Set());
                  }}
                  onDisconnect={(source) => setSteps((steps) => disconnect(steps, source, selectedStep.id))}
                  onConnect={(source) => onConnect({ source, target: selectedStep.id, sourceHandle: null, targetHandle: null })}
                />
              ) : (
                <>
                  {selected.size > 1 && (
                    <p className="mb-3 text-xs text-muted-foreground">
                      {selected.size} étapes sélectionnées : Suppr pour les retirer, ou cliquez sur une seule pour la régler.
                    </p>
                  )}
                  <WorkflowSettings
                    draft={draft}
                    agents={agents}
                    errors={errors}
                    undeclared={undeclared}
                    onChange={(patch) => update((d) => ({ ...d, ...patch }))}
                    onDeclareMissing={() => update(declareMissingParams)}
                  />
                </>
              )}
            </TabsContent>
            <TabsContent value="run" className="overflow-x-hidden overflow-y-auto p-4" forceMount hidden={panel !== "run"}>
              <RunPanel
                workflowId={draft.id}
                dirty={dirty}
                params={draft.params}
                steps={draft.steps}
                catalog={index}
                run={run}
                onRun={setRun}
                onSave={async () => {
                  if (!(await validate())) return null;
                  return save();
                }}
                onShowArtifacts={() => {
                  setPanelOpen(true);
                  closeEditor();
                }}
              />
            </TabsContent>
          </Tabs>
        </aside>
      </div>
      {/* Sélection courante annoncée aux lecteurs d'écran */}
      <p className="sr-only" aria-live="polite">
        {selectedStep ? `Étape ${selectedStep.id} sélectionnée` : ""}
        {selectedEdges.size ? ` ${selectedEdges.size} liaison(s) sélectionnée(s)` : ""}
      </p>
    </div>
  );
}
