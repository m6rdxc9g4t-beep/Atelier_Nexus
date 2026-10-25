"use client";

import { ChevronRight, ShieldQuestion, Trash2, Workflow as WorkflowIcon } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { AppChip } from "@/components/layout/AppChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { toolLabel } from "@/features/chat-agent/ToolCall";
import { toolApp } from "@/features/chat-agent/agentApps";
import { ApiError, api } from "@/lib/api";
import { approvalPromise } from "@/lib/approval";
import { cn } from "@/lib/utils";
import { useApprovalMode } from "@/stores/useApprovalModeStore";
import type { AgentInfo, Message, Workflow } from "@/types/api";

import { AppChain } from "./AppChain";
import { workflowChain } from "./chain";
import { type WorkflowForm, stepDraft, syncParams, toFields } from "./form";

/** Création depuis le dernier tour d'une conversation, ou modification d'un workflow. */
export type EditorSource =
  | { kind: "capture"; messages: Message[]; conversationId: string | null }
  | { kind: "edit"; workflow: Workflow };

interface WorkflowEditorProps {
  agent: AgentInfo;
  source: EditorSource;
  onOpenChange: (open: boolean) => void;
  onSaved: (workflow: Workflow) => void;
}

const EMPTY: WorkflowForm = { title: "", description: "", steps: [], params: [] };

/** Sans l'erreur d'une clé (champ corrigé depuis). */
const without = (errors: Record<string, string>, key: string) =>
  key in errors ? Object.fromEntries(Object.entries(errors).filter(([k]) => k !== key)) : errors;

export function WorkflowEditor({ agent, source, onOpenChange, onSaved }: WorkflowEditorProps) {
  const approvalMode = useApprovalMode();
  const editing = source.kind === "edit" ? source.workflow : null;
  const writeTools = new Set(agent.tools.filter((t) => t.requires_approval).map((t) => t.name));
  const [form, setForm] = useState<WorkflowForm>(() =>
    editing
      ? {
          title: editing.title,
          description: editing.description,
          steps: editing.steps.map((s) => stepDraft(s, writeTools.has(s.tool))),
          params: editing.params,
        }
      : EMPTY,
  );
  const [skipped, setSkipped] = useState<{ tool: string; reason: string }[]>([]);
  const [loading, setLoading] = useState(source.kind === "capture");
  // Erreurs du titre et de la liste ; celles des étapes par clé d'étape (stables si l'on en retire une)
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [stepErrors, setStepErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  // Capture refusée (aucune action réutilisable…) : distincte d'un échec d'enregistrement
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Étapes dépliées (clés) : une étape en erreur est dépliée, et se replie encore d'un clic
  const [openSteps, setOpenSteps] = useState<string[]>([]);
  const ids = useId();

  // Capture : le backend propose les étapes à partir du dernier tour (rien n'est enregistré)
  const captureFrom = source.kind === "capture" ? source.messages : null;
  useEffect(() => {
    if (!captureFrom) return;
    let alive = true;
    api
      .captureWorkflow(agent.name, captureFrom)
      .then((draft) => {
        if (!alive) return;
        const steps = draft.steps.map((s, i) => stepDraft(s, draft.writes.includes(i + 1)));
        setForm({ title: draft.title, description: draft.description, steps, params: [] });
        setSkipped(draft.skipped);
      })
      .catch((err: unknown) => {
        if (alive) setCaptureError(err instanceof ApiError ? err.message : "Le serveur ne répond pas.");
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [agent.name, captureFrom]);

  const params = syncParams(form.steps, form.params);
  const setParam = (name: string, key: "label" | "default", value: string) =>
    setForm((f) => ({
      ...f,
      params: syncParams(f.steps, f.params).map((p) => (p.name === name ? { ...p, [key]: value } : p)),
    }));
  const updateStep = (key: string, inputText: string) => {
    setForm((f) => ({ ...f, steps: f.steps.map((s) => (s.key === key ? { ...s, inputText } : s)) }));
    setStepErrors((e) => without(e, key));
  };
  const removeStep = (key: string) =>
    setForm((f) => ({ ...f, steps: f.steps.filter((s) => s.key !== key) }));
  const toggleStep = (key: string) =>
    setOpenSteps((open) => (open.includes(key) ? open.filter((k) => k !== key) : [...open, key]));

  const field = (id: string) => `${ids}-${id}`;

  const save = async () => {
    const parsed = toFields({ ...form, params });
    // `step-<rang>` (form.ts) rattachée à la clé de l'étape
    const byStep: Record<string, string> = {};
    form.steps.forEach((step, index) => {
      const error = parsed.errors[`step-${index}`];
      if (error) byStep[step.key] = error;
    });
    setErrors(Object.fromEntries(Object.entries(parsed.errors).filter(([k]) => !k.startsWith("step-"))));
    setStepErrors(byStep);
    if (!parsed.fields) {
      // Étapes en erreur dépliées ; focus sur la première erreur (titre, puis l'étape au JSON invalide)
      const wrong = Object.keys(byStep);
      setOpenSteps((open) => [...open, ...wrong.filter((k) => !open.includes(k))]);
      const first = parsed.errors.title ? "title" : wrong[0] ? `step-${wrong[0]}` : null;
      if (first) requestAnimationFrame(() => document.getElementById(field(first))?.focus());
      return;
    }
    setSaving(true);
    setServerError(null);
    try {
      const saved = editing
        ? await api.updateWorkflow(editing.id, parsed.fields)
        : await api.createWorkflow({
            ...parsed.fields,
            agent: agent.name,
            source_conversation_id: source.kind === "capture" ? source.conversationId : null,
          });
      onOpenChange(false);
      onSaved(saved);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : "Enregistrement impossible.");
    } finally {
      setSaving(false);
    }
  };

  const ready = !loading && form.steps.length > 0;
  // Capture refusée : pas de formulaire vide, juste l'explication
  const captureFailed = !loading && !!captureError;
  const chain = workflowChain(form.steps);

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent size="lg" scroll="body">
        <DialogHeader>
          <DialogTitle>{editing ? "Modifier le workflow" : "Enregistrer en workflow"}</DialogTitle>
          <DialogDescription>
            Les mêmes outils, dans le même ordre, relancés sans modèle : résultat immédiat et sans
            jeton. {approvalPromise(approvalMode)}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <>
            <DialogBody aria-busy>
              <p role="status" className="text-sm text-muted-foreground">
                Lecture des actions du dernier tour…
              </p>
              <div className="grid gap-1.5">
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-9 w-full" />
              </div>
              <div className="grid gap-2">
                <Skeleton className="h-4 w-20" />
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-11 w-full rounded-lg" />
                ))}
              </div>
            </DialogBody>
            {/* Même pied qu'ensuite : on peut renoncer pendant la lecture, rien n'est enregistré */}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Annuler
              </Button>
              <Button type="button" disabled>
                <WorkflowIcon />
                Créer le workflow
              </Button>
            </DialogFooter>
          </>
        )}

        {captureFailed && (
          <>
            <DialogBody>
              <Callout tone="destructive" role="alert" title="Capture impossible">
                {captureError}
              </Callout>
            </DialogBody>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Fermer
              </Button>
            </DialogFooter>
          </>
        )}

        {!loading && !captureFailed && (
          <form
            className="flex min-h-0 flex-1 flex-col"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <DialogBody className="gap-5">
              <div className="grid gap-1.5">
                <label htmlFor={field("title")} className="text-sm font-medium">
                  Titre
                </label>
                <Input
                  id={field("title")}
                  value={form.title}
                  maxLength={120}
                  aria-invalid={errors.title ? true : undefined}
                  aria-describedby={errors.title ? field("title-error") : undefined}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, title: e.target.value }));
                    setErrors((er) => without(er, "title"));
                  }}
                />
                {errors.title && (
                  <p id={field("title-error")} className="text-xs text-destructive-ink">
                    {errors.title}
                  </p>
                )}
              </div>
              <div className="grid gap-1.5">
                <label htmlFor={field("description")} className="text-sm font-medium">
                  Description <span className="font-normal text-muted-foreground">(facultatif)</span>
                </label>
                <Textarea
                  id={field("description")}
                  value={form.description}
                  maxLength={500}
                  rows={2}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>

              <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
                <legend className="mb-1.5 text-sm font-medium">
                  Étapes <span className="font-normal text-muted-foreground tabular-nums">({form.steps.length})</span>
                </legend>
                {chain.length > 0 && <AppChain apps={chain} max={5} />}
                <p className="text-xs text-muted-foreground">
                  Pour demander une valeur à chaque lancement, remplacez-la par{" "}
                  <code className="font-mono">{"{{nom}}"}</code> dans les paramètres d&apos;une étape (par
                  exemple <code className="font-mono">{'"dataset_id": "{{jeu}}"'}</code>).
                </p>
                <ol className="grid grid-cols-[minmax(0,1fr)] gap-2">
                  {form.steps.map((step, index) => {
                    const error = stepErrors[step.key];
                    const expanded = openSteps.includes(step.key);
                    const app = toolApp(step.tool);
                    const input = field(`step-${step.key}`);
                    const panel = `${input}-panel`;
                    return (
                      <li
                        key={step.key}
                        className={cn(
                          "rounded-lg border bg-card",
                          error ? "border-destructive/50" : expanded ? "border-atelier-border-soft" : "border-atelier-line",
                        )}
                      >
                        <div className="flex items-center gap-2 py-1 pr-1 pl-2.5">
                          <button
                            type="button"
                            aria-expanded={expanded}
                            aria-controls={expanded ? panel : undefined}
                            onClick={() => toggleStep(step.key)}
                            className="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left text-sm focus-visible:shadow-focus focus-visible:outline-none"
                          >
                            <ChevronRight
                              className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")}
                              aria-hidden
                            />
                            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-signature-faint text-xs font-semibold text-accent-ink tabular-nums">
                              {index + 1}
                            </span>
                            {app && <AppChip app={app} iconOnly className="size-5" />}
                            <span className="truncate">{toolLabel(step.tool)}</span>
                            {error && !expanded && <span className="sr-only"> (JSON invalide)</span>}
                          </button>
                          {step.writes && (
                            <Badge variant="warning" title="Validation demandée à chaque lancement">
                              <ShieldQuestion aria-hidden />
                              Écriture
                            </Badge>
                          )}
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Retirer l'étape ${index + 1}`}
                            title="Retirer l'étape"
                            onClick={() => removeStep(step.key)}
                          >
                            <Trash2 />
                          </Button>
                        </div>
                        {expanded && (
                          <div id={panel} className="border-t border-atelier-line px-2.5 py-2">
                            <label htmlFor={input} className="mb-1 block text-xs text-muted-foreground">
                              Paramètres de l&apos;outil (JSON)
                            </label>
                            <Textarea
                              id={input}
                              value={step.inputText}
                              spellCheck={false}
                              aria-invalid={error ? true : undefined}
                              aria-describedby={error ? `${input}-error` : undefined}
                              className="bg-sunken font-mono text-xs"
                              onChange={(e) => updateStep(step.key, e.target.value)}
                            />
                            {error && (
                              <p id={`${input}-error`} className="mt-1 text-xs text-destructive-ink">
                                {error}
                              </p>
                            )}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ol>
                {errors.steps ? (
                  <Callout tone="destructive" role="alert">
                    {errors.steps}
                  </Callout>
                ) : (
                  form.steps.length === 0 && (
                    // Toutes retirées : « Enregistrer » est désactivé, on dit pourquoi
                    <Callout tone="warning">
                      Il faut au moins une étape.
                      {editing && " Annulez pour garder le workflow tel qu'il est."}
                    </Callout>
                  )
                )}
                {skipped.length > 0 && (
                  <Callout tone="info" title="Actions écartées">
                    {skipped.map((s) => `${toolLabel(s.tool)} (${s.reason})`).join(" ; ")}.
                  </Callout>
                )}
              </fieldset>

              {params.length > 0 && (
                <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
                  <legend className="mb-1.5 text-sm font-medium">Paramètres demandés au lancement</legend>
                  {params.map((param) => (
                    <div key={param.name} className="grid gap-2 sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)] sm:items-center">
                      <code className="truncate font-mono text-xs text-accent-ink">{`{{${param.name}}}`}</code>
                      <Input
                        aria-label={`Libellé de ${param.name}`}
                        placeholder="Libellé (ex. Jeu de données)"
                        maxLength={80}
                        value={param.label}
                        onChange={(e) => setParam(param.name, "label", e.target.value)}
                      />
                      <Input
                        aria-label={`Valeur par défaut de ${param.name}`}
                        placeholder="Valeur par défaut"
                        maxLength={500}
                        value={param.default}
                        onChange={(e) => setParam(param.name, "default", e.target.value)}
                      />
                    </div>
                  ))}
                </fieldset>
              )}
            </DialogBody>

            {serverError && (
              <div className="shrink-0 px-6 pt-3">
                <Callout tone="destructive" role="alert">
                  {serverError}
                </Callout>
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                Annuler
              </Button>
              <Button type="submit" disabled={!ready || saving}>
                <WorkflowIcon />
                {saving ? "Enregistrement…" : editing ? "Enregistrer" : "Créer le workflow"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
