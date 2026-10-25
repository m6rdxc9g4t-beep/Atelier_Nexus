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
  LayoutTemplate,
  Monitor,
  Play,
  Save,
  ShieldCheck,
  ShieldQuestion,
  SlidersHorizontal,
  TriangleAlert,
  Workflow as WorkflowIcon,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge, badgeVariants } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TriggersPanel } from "@/features/workflow-triggers/TriggersPanel";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { ApiError, api, isWorkflowV2 } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";
import { type EditorTarget, type TriggerPreset, useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, Catalog, CatalogEntry, ValidationError, WorkflowRun, WorkflowStepV2, WorkflowV2 } from "@/types/api";

import { catalogIndex } from "./catalog";
import {
  SAVE_STATE_LABEL,
  type SaveState,
  type WorkflowDraftV2,
  declareMissingParams,
  draftFromTemplate,
  draftFromWorkflow,
  draftSignature,
  emptyDraft,
  mergeErrors,
  saveBlockers,
  saveState,
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
  isRunActive,
  mergeRunState,
  nextPosition,
  removeSteps,
  renameStep,
  stepsToEdges,
  stepsToNodes,
} from "./graph";
import { StepInspector, WorkflowSettings } from "./Inspector";
import { type EditorExit, leaveEditor } from "./leave";
import { DRAG_MIME, Palette } from "./Palette";
import { RunPanel, type RunPanelHandle } from "./RunPanel";
import { StepNode } from "./StepNode";
import { displayedErrors, firstErrorStep, problemsText, validateLocal } from "./validate";

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
  const openTemplates = useWorkflowStudioStore((s) => s.openTemplates);
  const dirty = useWorkflowStudioStore((s) => s.editorDirty);
  const wide = useMediaQuery("(min-width: 1024px)");
  /** Sortie en attente de confirmation (modifications non enregistrées) */
  const [confirming, setConfirming] = useState<EditorExit | null>(null);
  if (!editor) return null;
  const leave = (to: EditorExit) => leaveEditor({ closeEditor: close, openTemplates }, to);
  // Fermer ou partir d'un modèle : même confirmation s'il y a des modifications
  const requestLeave = (to: EditorExit) => (dirty ? setConfirming(to) : leave(to));
  return (
    <>
      <Dialog open onOpenChange={(open) => !open && requestLeave("close")}>
        <DialogContent
          className="flex h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-none flex-col gap-0 overflow-hidden p-0 sm:max-w-none"
          onEscapeKeyDown={(e) => {
            // Échap dans le graphe annule une sélection, dans le titre il quitte le champ : on ne
            // ferme pas la fenêtre par erreur
            if ((e.target as HTMLElement | null)?.closest(".react-flow, [data-escape-local]")) e.preventDefault();
          }}
        >
          {wide ? (
            <ReactFlowProvider>
              <GraphEditor key={editorKey} target={editor} agents={agents} onShowTemplates={() => requestLeave("templates")} />
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
      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent className="max-w-sm">
          <DialogTitle>Quitter sans enregistrer ?</DialogTitle>
          <DialogDescription>
            {confirming === "templates"
              ? "Les modifications de ce workflow seront perdues ; les modèles de la suite s'ouvriront ensuite."
              : "Les modifications de ce workflow seront perdues."}
          </DialogDescription>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirming(null)}>
              Continuer l&apos;édition
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                const to = confirming ?? "close";
                setConfirming(null);
                leave(to);
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

function GraphEditor({
  target,
  agents,
  onShowTemplates,
}: {
  target: EditorTarget;
  agents: AgentInfo[];
  /** « Partir d'un modèle de la suite » : quitte l'éditeur (confirmé si modifié) pour les modèles */
  onShowTemplates: () => void;
}) {
  const [loaded, setLoaded] = useState<Loaded>(() => {
    if (target.kind !== "new") return { status: "loading" };
    // Copie d'un modèle de la suite : brouillon prérempli, jamais enregistré tant qu'on ne le fait pas
    if (target.template) return { status: "ready", draft: draftFromTemplate(target.template, target.agent), saved: null };
    // Brouillon vierge : rien à perdre tant qu'on n'y touche pas (fermeture sans confirmation)
    const blank = emptyDraft(target.agent);
    return { status: "ready", draft: blank, saved: draftSignature(blank) };
  });
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
        <div aria-hidden className="flex items-center gap-6">
          <Skeleton className="h-16 w-44" />
          <Skeleton className="h-16 w-44" />
          <Skeleton className="h-16 w-44" />
        </div>
      </Centered>
    );
  if (loaded.status === "error")
    return (
      <Centered title="Impossible d'ouvrir le workflow">
        <Callout tone="destructive" role="alert" className="max-w-md text-left">
          {loaded.message}
        </Callout>
      </Centered>
    );
  if (loaded.status === "v1")
    return (
      <ConvertPrompt
        id={loaded.id}
        title={loaded.title}
        withTrigger={!!target.trigger}
        onConverted={(wf) => {
          bump();
          // Le déclencheur prérempli suit la conversion
          openEditor({ kind: "open", id: wf.id, ...(target.trigger ? { panel: "triggers", trigger: target.trigger } : {}) });
        }}
      />
    );
  return (
    <EditorBody
      initial={loaded.draft}
      savedSignature={loaded.saved}
      initialUses={target.kind === "new" ? (target.uses ?? null) : null}
      initialPanel={target.trigger ? "triggers" : target.kind === "open" && target.panel ? target.panel : "inspect"}
      initialRunId={target.kind === "open" ? (target.runId ?? null) : null}
      triggerPreset={target.trigger ?? null}
      fromTemplate={target.kind === "new" ? (target.template?.title ?? null) : null}
      agents={agents}
      onShowTemplates={onShowTemplates}
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
export function ConvertPrompt({
  id,
  title,
  withTrigger = false,
  onConverted,
}: {
  id: string;
  title: string;
  /** Un déclencheur attend la conversion (carte de la suite) */
  withTrigger?: boolean;
  onConverted: (wf: WorkflowV2) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Centered title={`« ${title} » est un workflow v1`}>
      <p className="max-w-md text-sm text-muted-foreground">
        Pour l&apos;éditer en graphe, convertissez-le : ses étapes deviennent s1, s2… reliées en chaîne, et chaque{" "}
        <code className="font-mono">{"{{nom}}"}</code> devient <code className="font-mono">{"{{params.nom}}"}</code>.
      </p>
      <p className="max-w-md text-sm text-muted-foreground">
        {withTrigger
          ? "Les déclencheurs (horaire, événement) ne s'appliquent qu'aux workflows v2 : le déclencheur demandé s'ouvrira après la conversion."
          : "Les déclencheurs (horaire, événement) ne s'appliquent eux aussi qu'aux workflows v2."}
      </p>
      {error && (
        <Callout tone="destructive" role="alert" className="max-w-md text-left">
          {error}
        </Callout>
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

type SidePanel = "inspect" | "run" | "triggers";

type Notice = { tone: "ok" | "info" | "error"; text: string };

const NOTICE_TONE = { ok: "success", info: "signature", error: "destructive" } as const;

/** Pastille de la puce d'enregistrement (le libellé dit la même chose : jamais la couleur seule). */
const SAVE_DOT: Record<SaveState, string> = {
  draft: "bg-muted-foreground/50",
  modified: "bg-warning",
  saved: "bg-success",
};

function EditorBody({
  initial,
  savedSignature,
  initialUses,
  initialPanel,
  initialRunId,
  triggerPreset,
  fromTemplate,
  agents,
  onShowTemplates,
}: {
  initial: WorkflowDraftV2;
  savedSignature: string | null;
  initialUses: string | null;
  initialPanel: SidePanel;
  /** Exécution à afficher dans le suivi dès l'ouverture (boîte « À valider ») */
  initialRunId: string | null;
  /** Déclencheur événement à préremplir (carte de la suite) */
  triggerPreset: TriggerPreset | null;
  /** Titre du modèle de la suite copié dans ce brouillon (message d'accueil) */
  fromTemplate: string | null;
  agents: AgentInfo[];
  onShowTemplates: () => void;
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
  const [notice, setNotice] = useState<Notice | null>(() =>
    fromTemplate
      ? {
          tone: "info",
          text: `Copie du modèle « ${fromTemplate} » : vérifiez les étapes et leurs réglages, puis enregistrez. Rien n'est enregistré pour l'instant.`,
        }
      : null,
  );
  const [busy, setBusy] = useState<"validate" | "save" | null>(null);
  const [panel, setPanel] = useState<SidePanel>(initialPanel);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [preset, setPreset] = useState<TriggerPreset | null>(triggerPreset);
  const [titleMissing, setTitleMissing] = useState(false);
  const clearPreset = useCallback(() => setPreset(null), []);
  const flow = useReactFlow();
  const seeded = useRef(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const runPanel = useRef<RunPanelHandle>(null);
  const bump = useWorkflowStudioStore((s) => s.bump);
  const setPanelOpen = useArtifactStore((s) => s.setPanelOpen);
  const closeEditor = useWorkflowStudioStore((s) => s.closeEditor);
  const setLastWorkflow = useWorkflowStudioStore((s) => s.setLastWorkflow);

  // Dernier workflow enregistré ouvert : la carte de la suite propose d'y ajouter un déclencheur
  useEffect(() => {
    if (draft.id) setLastWorkflow({ id: draft.id, title: draft.title.trim() || "Sans titre" });
  }, [draft.id, draft.title, setLastWorkflow]);

  // Exécution demandée à l'ouverture (boîte « À valider ») : affichée dans le suivi
  useEffect(() => {
    if (!initialRunId) return;
    const ctrl = new AbortController();
    api
      .workflowRun(initialRunId, ctrl.signal)
      .then(setRun)
      .catch((err: unknown) => !ctrl.signal.aborted && setNotice({ tone: "error", text: errorText(err, "Exécution introuvable.") }));
    return () => ctrl.abort();
  }, [initialRunId]);

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

  // Un succès (« Workflow enregistré. ») s'efface tout seul ; erreurs et informations restent
  useEffect(() => {
    if (notice?.tone !== "ok") return;
    const timer = setTimeout(() => setNotice((n) => (n === notice ? null : n)), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  const index = useMemo(() => catalogIndex(catalog), [catalog]);
  const apps = useMemo(
    () => new Map((catalog?.apps ?? []).map((a) => [a.app, { name: a.name, color: a.color, status: a.status }])),
    [catalog],
  );
  const localErrors = useMemo(() => validateLocal({ steps: draft.steps, params: draft.params, catalog: catalog ? index : null }), [draft, catalog, index]);
  const errors = useMemo(() => mergeErrors(localErrors, serverErrors), [localErrors, serverErrors]);
  const shownErrors = useMemo(() => displayedErrors(errors), [errors]);
  const runView = useMemo(() => mergeRunState(draft.steps, run), [draft.steps, run]);
  const signature = draftSignature(draft);
  const dirty = signature !== saved;
  const state = saveState(draft, dirty);
  const setEditorDirty = useWorkflowStudioStore((s) => s.setEditorDirty);
  useEffect(() => setEditorDirty(dirty), [dirty, setEditorDirty]);

  const nodes = useMemo(
    () => stepsToNodes(draft.steps, { catalog: index, catalogReady: !!catalog, apps, errors, run: runView, selected, measured }),
    [draft.steps, index, catalog, apps, errors, runView, selected, measured],
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

  /** Badge « n problèmes » : sélectionne la première étape en erreur et la centre ; sinon les réglages du workflow. */
  const showFirstProblem = () => {
    const id = firstErrorStep(draft.steps, shownErrors);
    setSelectedEdges(new Set());
    setPanel("inspect");
    if (!id) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set([id]));
    window.requestAnimationFrame(() => void flow.fitView({ nodes: [{ id }], padding: 0.8, maxZoom: 1.1, duration: 250 }));
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
          : { tone: "error", text: `${problemsText(result.errors.length)} signalé${result.errors.length > 1 ? "s" : ""} sur le graphe.` },
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
      // Seul blocage propre à l'enregistrement : le titre, modifiable dans l'en-tête
      setTitleMissing(true);
      titleRef.current?.focus();
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

  /** Valide puis enregistre (lancement, déclencheurs). */
  const validateAndSave = async () => {
    if (!(await validate())) return null;
    return save();
  };

  /** « Lancer » de l'en-tête : onglet Exécution, puis le même lancement que le panneau. */
  const startRun = () => {
    setPanel("run");
    runPanel.current?.start();
  };

  const selectedStep = selected.size === 1 ? draft.steps.find((s) => selected.has(s.id)) : undefined;
  const undeclared = undeclaredParams(draft);
  const errorCount = shownErrors.length;
  const running = isRunActive(run);
  const awaiting = run?.status === "awaiting_approval";
  const agentName = draft.agent ? (agents.find((a) => a.name === draft.agent)?.display_name ?? draft.agent) : null;

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
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-atelier-line bg-sidebar/85 pr-12 pl-3">
        <WorkflowIcon className="ml-1 size-4 shrink-0 text-accent-ink" aria-hidden />
        <DialogTitle className="sr-only">{draft.title.trim() || "Nouveau workflow"}</DialogTitle>
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Input
            ref={titleRef}
            data-escape-local
            aria-label="Titre du workflow"
            aria-invalid={titleMissing && !draft.title.trim()}
            maxLength={120}
            size={Math.min(Math.max(draft.title.length + 2, 24), 48)}
            placeholder="Nouveau workflow — titre"
            value={draft.title}
            onChange={(e) => {
              setTitleMissing(false);
              update((d) => ({ ...d, title: e.target.value }));
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === "Escape") e.currentTarget.blur();
            }}
            className="h-8 w-auto max-w-[28rem] min-w-0 border-transparent bg-transparent px-2 text-base font-semibold tracking-tight hover:border-atelier-line focus-visible:border-input aria-[invalid=true]:border-destructive"
          />
          <span role="status" className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-atelier-line px-2 py-0.5 text-xs text-muted-foreground">
            <span aria-hidden className={cn("size-1.5 rounded-full", SAVE_DOT[state])} />
            {SAVE_STATE_LABEL[state]}
          </span>
          <DialogDescription className="min-w-0 truncate text-xs">
            {agentName ? `Workflow de ${agentName}` : "Workflow de suite"} · {draft.steps.length} étape(s)
          </DialogDescription>
        </div>
        {errorCount > 0 ? (
          <button
            type="button"
            onClick={showFirstProblem}
            title="Afficher le premier problème"
            className={cn(
              badgeVariants({ variant: "destructive" }),
              "h-7 cursor-pointer px-2 transition-colors hover:bg-destructive/20 focus-visible:shadow-focus focus-visible:outline-none",
            )}
          >
            <TriangleAlert aria-hidden />
            {problemsText(errorCount)}
            <span className="sr-only"> : afficher le premier</span>
          </button>
        ) : checked?.ok && checked.at === signature ? (
          <Badge variant="success" className="h-7 px-2">
            <CircleCheck aria-hidden />
            valide
          </Badge>
        ) : null}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={relayout}
          disabled={draft.steps.length === 0}
          aria-label="Mise en page automatique"
          title="Mise en page automatique : les étapes rangées en colonnes, dans l'ordre d'exécution"
        >
          <LayoutGrid />
        </Button>
        <Button variant="outline" size="sm" onClick={() => void validate()} disabled={busy !== null || draft.steps.length === 0}>
          <ShieldCheck />
          {busy === "validate" ? "Validation…" : "Valider"}
        </Button>
        <Button variant="outline" size="sm" onClick={() => void save()} disabled={busy !== null || (!dirty && !!draft.id)}>
          <Save />
          {busy === "save" ? "Enregistrement…" : "Enregistrer"}
        </Button>
        {awaiting ? (
          // Une validation attend : on y mène (onglet Exécution), on n'autorise rien d'ici
          <Button size="sm" onClick={() => setPanel("run")}>
            <ShieldQuestion />À valider
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={startRun}
            disabled={busy !== null || running || draft.steps.length === 0}
            title={dirty || !draft.id ? "Enregistre puis lance le workflow" : "Lance le workflow"}
          >
            <Play />
            {running ? "En cours…" : "Lancer"}
          </Button>
        )}
      </header>

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
            <Background variant={BackgroundVariant.Dots} gap={20} size={1.5} />
            <Controls position="bottom-left" showInteractive={false} />
            <MiniMap position="bottom-right" pannable zoomable ariaLabel="Mini-carte du workflow" />
          </ReactFlow>

          {notice && (
            <div className="pointer-events-none absolute inset-x-0 top-3 z-10 flex justify-center px-4">
              <div className="pointer-events-auto w-full max-w-xl rounded-xl bg-card shadow-glow-strong">
                <Callout
                  tone={NOTICE_TONE[notice.tone]}
                  role={notice.tone === "error" ? "alert" : "status"}
                  action={
                    <Button type="button" variant="ghost" size="icon-xs" aria-label="Masquer le message" onClick={() => setNotice(null)}>
                      <X />
                    </Button>
                  }
                >
                  {notice.text}
                </Callout>
              </div>
            </div>
          )}

          {draft.steps.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-8">
              <div className="pointer-events-auto w-full max-w-md rounded-xl border border-dashed border-atelier-border-soft bg-card/90 backdrop-blur-sm">
                <EmptyState
                  icon={WorkflowIcon}
                  title="Point de départ"
                  className="py-7"
                  actions={
                    <Button type="button" variant="soft" size="sm" onClick={onShowTemplates}>
                      <LayoutTemplate />
                      Partir d&apos;un modèle de la suite
                    </Button>
                  }
                >
                  <ol className="mt-2 grid gap-1.5 text-left">
                    {[
                      "Glissez une action de la palette sur le graphe (ou « + »).",
                      "Reliez la sortie d'une étape à l'entrée de la suivante.",
                      "Validez, enregistrez, puis lancez.",
                    ].map((text, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <span aria-hidden className="mt-px grid size-5 shrink-0 place-items-center rounded-full bg-signature-faint text-xs font-semibold text-accent-ink tabular-nums">
                          {i + 1}
                        </span>
                        <span>{text}</span>
                      </li>
                    ))}
                  </ol>
                </EmptyState>
              </div>
            </div>
          )}
        </div>

        <aside
          aria-label="Inspecteur"
          className={cn(
            "flex min-h-0 shrink-0 flex-col border-l border-atelier-line bg-card transition-[width] duration-200 ease-out",
            panel === "triggers" ? "w-[30rem]" : "w-[24rem]",
          )}
        >
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
                  {(running || awaiting) && (
                    <>
                      <span aria-hidden className={cn("size-1.5 rounded-full", awaiting ? "bg-warning" : "animate-pulse bg-primary")} />
                      <span className="sr-only">{awaiting ? "(validation demandée)" : "(en cours)"}</span>
                    </>
                  )}
                </TabsTrigger>
                <TabsTrigger
                  value="triggers"
                  className="flex-1"
                  title={draft.id ? "Lancer ce workflow à heure fixe ou sur un événement" : "Enregistrez le workflow pour lui ajouter des déclencheurs"}
                >
                  <Zap />
                  Déclencheurs
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
                  catalogReady={!!catalog}
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
                    <Callout tone="info" className="mb-4">
                      {selected.size} étapes sélectionnées : Suppr pour les retirer, ou cliquez sur une seule pour la régler.
                    </Callout>
                  )}
                  <WorkflowSettings
                    draft={draft}
                    agents={agents}
                    errors={shownErrors}
                    undeclared={undeclared}
                    onChange={(patch) => update((d) => ({ ...d, ...patch }))}
                    onDeclareMissing={() => update(declareMissingParams)}
                  />
                </>
              )}
            </TabsContent>
            <TabsContent value="run" className="overflow-x-hidden overflow-y-auto p-4" forceMount hidden={panel !== "run"}>
              <RunPanel
                ref={runPanel}
                workflowId={draft.id}
                dirty={dirty}
                params={draft.params}
                steps={draft.steps}
                catalog={index}
                run={run}
                onRun={setRun}
                onSave={validateAndSave}
                onShowArtifacts={() => {
                  setPanelOpen(true);
                  closeEditor();
                }}
              />
            </TabsContent>
            {/* Toujours monté : un formulaire en cours survit au passage par un autre onglet */}
            <TabsContent value="triggers" className="overflow-x-hidden overflow-y-auto p-4" forceMount hidden={panel !== "triggers"}>
              <TriggersPanel
                workflowId={draft.id}
                dirty={dirty}
                params={draft.params}
                preset={preset}
                onPresetUsed={clearPreset}
                onSave={validateAndSave}
                onRun={(next) => {
                  setRun(next);
                  setPanel("run");
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
