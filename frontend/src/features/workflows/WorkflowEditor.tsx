"use client";

import { ChevronRight, Info, ShieldQuestion, Trash2, Workflow as WorkflowIcon } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toolLabel } from "@/features/chat-agent/ToolCall";
import { ApiError, api } from "@/lib/api";
import { approvalPromise } from "@/lib/approval";
import { cn } from "@/lib/utils";
import { useApprovalMode } from "@/stores/useApprovalModeStore";
import type { AgentInfo, Message, Workflow } from "@/types/api";

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
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [openStep, setOpenStep] = useState<string | null>(null);
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
        if (alive) setServerError(err instanceof ApiError ? err.message : "Capture impossible.");
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
  const updateStep = (index: number, inputText: string) =>
    setForm((f) => ({ ...f, steps: f.steps.map((s, i) => (i === index ? { ...s, inputText } : s)) }));
  const removeStep = (index: number) =>
    setForm((f) => ({ ...f, steps: f.steps.filter((_, i) => i !== index) }));

  const save = async () => {
    const parsed = toFields({ ...form, params });
    setErrors(parsed.errors);
    if (!parsed.fields) return;
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

  const field = (id: string) => `${ids}-${id}`;
  const ready = !loading && form.steps.length > 0;
  // Capture refusée (aucune action réutilisable…) : pas de formulaire vide, juste l'explication
  const captureFailed = source.kind === "capture" && !loading && form.steps.length === 0 && !!serverError;

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl grid-cols-[minmax(0,1fr)]">
        <DialogHeader>
          <DialogTitle>{editing ? "Modifier le workflow" : "Enregistrer en workflow"}</DialogTitle>
          <DialogDescription>
            Les mêmes outils, dans le même ordre, relancés sans modèle : résultat immédiat et sans
            jeton. {approvalPromise(approvalMode)}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <p role="status" className="text-sm text-muted-foreground">
            Lecture des actions du dernier tour…
          </p>
        )}

        {captureFailed && (
          <div className="grid gap-3">
            <p role="alert" className="text-sm text-destructive">
              {serverError}
            </p>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Fermer
              </Button>
            </DialogFooter>
          </div>
        )}

        {!loading && !captureFailed && (
          <form
            className="grid grid-cols-[minmax(0,1fr)] gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <div className="grid gap-1.5">
              <label htmlFor={field("title")} className="text-sm font-medium">
                Titre
              </label>
              <Input
                id={field("title")}
                value={form.title}
                maxLength={120}
                aria-invalid={!!errors.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              />
              {errors.title && <p className="text-xs text-destructive">{errors.title}</p>}
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
              <legend className="mb-1.5 text-sm font-medium">Étapes</legend>
              <p className="text-xs text-muted-foreground">
                Pour demander une valeur à chaque lancement, remplacez-la par{" "}
                <code className="font-mono">{"{{nom}}"}</code> dans les paramètres d&apos;une étape (par
                exemple <code className="font-mono">{'"dataset_id": "{{jeu}}"'}</code>).
              </p>
              <ol className="grid grid-cols-[minmax(0,1fr)] gap-2">
                {form.steps.map((step, index) => {
                  const expanded = openStep === step.key;
                  const error = errors[`step-${index}`];
                  return (
                    <li
                      key={step.key}
                      className={cn(
                        "rounded-md border bg-card",
                        error ? "border-destructive/50" : "border-atelier-border-soft",
                      )}
                    >
                      <div className="flex items-center gap-2 px-2.5 py-1.5">
                        <button
                          type="button"
                          aria-expanded={expanded}
                          onClick={() => setOpenStep(expanded ? null : step.key)}
                          className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
                        >
                          <ChevronRight
                            className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")}
                            aria-hidden
                          />
                          <span className="text-muted-foreground tabular-nums">{index + 1}.</span>
                          <span className="truncate">{toolLabel(step.tool)}</span>
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
                          onClick={() => removeStep(index)}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                      {(expanded || error) && (
                        <div className="border-t border-atelier-line px-2.5 py-2">
                          <label htmlFor={field(`step-${index}`)} className="mb-1 block text-xs text-muted-foreground">
                            Paramètres de l&apos;outil (JSON)
                          </label>
                          <Textarea
                            id={field(`step-${index}`)}
                            value={step.inputText}
                            spellCheck={false}
                            aria-invalid={!!error}
                            className="font-mono text-xs"
                            onChange={(e) => updateStep(index, e.target.value)}
                          />
                          {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
              {errors.steps && <p className="text-xs text-destructive">{errors.steps}</p>}
              {skipped.length > 0 && (
                <p className="flex items-start gap-2 text-xs text-muted-foreground">
                  <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  <span>
                    Écartés :{" "}
                    {skipped.map((s) => `${toolLabel(s.tool)} (${s.reason})`).join(" ; ")}.
                  </span>
                </p>
              )}
            </fieldset>

            {params.length > 0 && (
              <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
                <legend className="mb-1.5 text-sm font-medium">Paramètres demandés au lancement</legend>
                {params.map((param) => (
                  <div key={param.name} className="grid gap-2 sm:grid-cols-[8rem_1fr_1fr] sm:items-center">
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

            {serverError && (
              <p role="alert" className="text-sm text-destructive">
                {serverError}
              </p>
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
