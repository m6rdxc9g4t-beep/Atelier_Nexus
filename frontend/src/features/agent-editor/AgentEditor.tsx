"use client";

import { Lock, PencilLine, ShieldCheck, Trash2 } from "lucide-react";
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
import { NativeSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AGENT_ICONS, AgentIcon } from "@/features/chat-agent/agentMeta";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { EditorOptions, ProviderName } from "@/types/api";

import { type AgentForm, emptyForm, forcesLocal, formFrom, slugify, toPayload, validate } from "./form";

interface AgentEditorProps {
  open: boolean;
  /** Nom de l'agent personnalisé à modifier ; null = création */
  editing: string | null;
  onOpenChange: (open: boolean) => void;
  /** Après enregistrement ou suppression : nom de l'agent à sélectionner (null après suppression) */
  onSaved: (name: string | null) => void | Promise<void>;
}

const PROMPT_HINT =
  "Ex. : Tu es responsable de la veille concurrentielle. Chaque lundi, tu résumes les annonces " +
  "des concurrents, tu classes les sujets par impact et tu proposes trois actions.";

export function AgentEditor({ open, editing, onOpenChange, onSaved }: AgentEditorProps) {
  const [options, setOptions] = useState<EditorOptions | null>(null);
  // Monté à chaque ouverture (clé dans Workspace) : l'état initial suffit à le réinitialiser
  const [form, setForm] = useState<AgentForm>(emptyForm);
  const [nameTouched, setNameTouched] = useState(!!editing);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const ids = useId();

  // Options de l'éditeur et agent à modifier : chargés à part, sans jamais écraser la saisie
  const [loading, setLoading] = useState(!!editing);
  useEffect(() => {
    let alive = true;
    const fail = (fallback: string) => (err: unknown) => {
      if (alive) setServerError(err instanceof ApiError ? err.message : fallback);
    };
    api
      .editorOptions()
      .then((opts) => alive && setOptions(opts))
      .catch(fail("Chargement impossible."));
    if (editing) {
      api
        .customAgent(editing)
        .then((definition) => alive && setForm(formFrom(definition)))
        .catch(fail("Agent introuvable."))
        .finally(() => alive && setLoading(false));
    }
    return () => {
      alive = false;
    };
  }, [editing]);

  const toolsets = options?.toolsets.filter((t) => t.id !== "core") ?? [];
  const locked = options ? forcesLocal(form, options.toolsets) : false;
  const update = <K extends keyof AgentForm>(key: K, value: AgentForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const toggleToolset = (id: string) =>
    setForm((f) => ({
      ...f,
      toolsets: f.toolsets.includes(id) ? f.toolsets.filter((t) => t !== id) : [...f.toolsets, id],
    }));

  const save = async () => {
    if (!options) return;
    const found = validate(form, options.reserved_names, !!editing);
    setErrors(found);
    if (Object.keys(found).length) return;
    setSaving(true);
    setServerError(null);
    try {
      const payload = toPayload(form, options.toolsets);
      const info = editing
        ? await api.updateAgent(editing, payload)
        : await api.createAgent({ ...payload, name: form.name });
      onOpenChange(false);
      await onSaved(info.name);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : "Enregistrement impossible.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await api.deleteAgent(editing);
      onOpenChange(false);
      await onSaved(null);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : "Suppression impossible.");
    } finally {
      setSaving(false);
    }
  };

  const field = (id: string) => `${ids}-${id}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{editing ? "Modifier l'agent" : "Créer un agent"}</DialogTitle>
          <DialogDescription>
            Un agent, c&apos;est un rôle, des consignes et des outils. Les actions qui modifient vos
            données demanderont toujours votre validation.
          </DialogDescription>
        </DialogHeader>

        <form
          aria-busy={loading}
          className={cn("grid gap-4", loading && "pointer-events-none opacity-60")}
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
            <Field id={field("display")} label="Nom" error={errors.display_name}>
              <Input
                id={field("display")}
                value={form.display_name}
                maxLength={60}
                onChange={(e) => {
                  update("display_name", e.target.value);
                  if (!editing && !nameTouched) update("name", slugify(e.target.value));
                }}
                placeholder="Veille concurrentielle"
              />
            </Field>
            <Field id={field("category")} label="Catégorie">
              <Input
                id={field("category")}
                value={form.category}
                maxLength={40}
                onChange={(e) => update("category", e.target.value)}
                className="sm:w-44"
              />
            </Field>
          </div>

          {!editing && (
            <Field
              id={field("name")}
              label="Identifiant"
              hint="Utilisé dans l'adresse de l'agent. Ne peut plus changer ensuite."
              error={errors.name}
            >
              <Input
                id={field("name")}
                value={form.name}
                onChange={(e) => {
                  setNameTouched(true);
                  update("name", e.target.value);
                }}
                className="font-mono"
              />
            </Field>
          )}

          <Field id={field("description")} label="Rôle en une phrase" error={errors.description}>
            <Input
              id={field("description")}
              value={form.description}
              maxLength={300}
              onChange={(e) => update("description", e.target.value)}
              placeholder="Résume l'actualité des concurrents et propose des actions."
            />
          </Field>

          <fieldset>
            <legend className="mb-1.5 text-sm font-medium">Icône</legend>
            <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Icône">
              {(options?.icons ?? Object.keys(AGENT_ICONS)).map((icon) => (
                <button
                  key={icon}
                  type="button"
                  role="radio"
                  aria-checked={form.icon === icon}
                  aria-label={icon}
                  onClick={() => update("icon", icon)}
                  className={cn(
                    "grid size-8 place-items-center rounded-md border transition-colors",
                    form.icon === icon
                      ? "border-primary bg-accent-soft text-accent-ink"
                      : "border-transparent text-muted-foreground hover:bg-accent",
                  )}
                >
                  <AgentIcon icon={icon} className="size-4" aria-hidden />
                </button>
              ))}
            </div>
          </fieldset>

          <Field
            id={field("prompt")}
            label="Consignes"
            hint="Qui est l'agent, ce qu'il fait, comment il répond. Les règles communes de Nexus (français, artefacts, validation) sont ajoutées automatiquement."
            error={errors.system_prompt}
          >
            <Textarea
              id={field("prompt")}
              value={form.system_prompt}
              onChange={(e) => update("system_prompt", e.target.value)}
              placeholder={PROMPT_HINT}
              className="min-h-32"
            />
          </Field>

          <fieldset>
            <legend className="mb-1 text-sm font-medium">Outils</legend>
            <p className="mb-2 text-xs text-muted-foreground">
              Date, heure et publication d&apos;artefacts sont toujours inclus.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {toolsets.map((t) => {
                const checked = form.toolsets.includes(t.id);
                return (
                  <label
                    key={t.id}
                    className={cn(
                      "flex cursor-pointer gap-2.5 rounded-md border p-2.5 text-sm transition-colors",
                      checked ? "border-primary/60 bg-accent-soft/60" : "hover:bg-accent",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleToolset(t.id)}
                      className="mt-0.5 size-4 accent-[var(--primary)]"
                    />
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-1.5 font-medium">
                        {t.label}
                        {t.sensitive && (
                          <Badge variant="secondary">
                            <Lock aria-hidden />
                            local
                          </Badge>
                        )}
                        {t.writes && (
                          <Badge variant="warning">
                            <ShieldCheck aria-hidden />
                            avec validation
                          </Badge>
                        )}
                        {!t.configured && <Badge variant="outline">non configuré</Badge>}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{t.description}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id={field("provider")} label="Moteur par défaut">
              {locked ? (
                <p className="flex h-9 items-center gap-1.5 rounded-md border bg-muted px-3 text-sm text-muted-foreground">
                  <Lock className="size-3.5" aria-hidden />
                  Ollama (local) imposé par les outils choisis
                </p>
              ) : (
                <NativeSelect
                  id={field("provider")}
                  className="w-full [&_select]:h-9"
                  value={form.privacy === "local_only" ? "local" : (form.default_provider ?? "")}
                  onChange={(e) => {
                    const v = e.target.value;
                    update("privacy", v === "local" ? "local_only" : "standard");
                    update("default_provider", v === "" || v === "local" ? null : (v as ProviderName));
                  }}
                >
                  <option value="">Celui choisi dans l&apos;en-tête</option>
                  <option value="anthropic">Claude</option>
                  <option value="ollama">Ollama (local)</option>
                  <option value="local">Toujours local (verrouillé)</option>
                </NativeSelect>
              )}
            </Field>
            <Field
              id={field("starters")}
              label="Exemples de demandes"
              hint="Un par ligne, six au plus."
              error={errors.startersText}
            >
              <Textarea
                id={field("starters")}
                value={form.startersText}
                onChange={(e) => update("startersText", e.target.value)}
                rows={3}
                className="min-h-20"
              />
            </Field>
          </div>

          {serverError && (
            <p role="alert" className="text-sm text-destructive">
              {serverError}
            </p>
          )}

          <DialogFooter className="items-center">
            {editing && (
              <Button
                type="button"
                variant={confirmDelete ? "destructive" : "ghost"}
                className="sm:mr-auto"
                disabled={saving}
                onClick={() => (confirmDelete ? void remove() : setConfirmDelete(true))}
              >
                <Trash2 />
                {confirmDelete ? "Confirmer la suppression" : "Supprimer"}
              </Button>
            )}
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Annuler
            </Button>
            <Button type="submit" disabled={saving || loading || !options}>
              <PencilLine />
              {editing ? "Enregistrer" : "Créer l'agent"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
