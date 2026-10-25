"use client";

import { Lock, PencilLine, ShieldCheck, Trash2, Unplug } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useEffect, useId, useState } from "react";

import { AppChip } from "@/components/layout/AppChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { SectionLabel } from "@/components/ui/section-label";
import { NativeSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AgentTile } from "@/features/chat-agent/AgentTile";
import { AGENT_ICONS, AgentIcon } from "@/features/chat-agent/agentMeta";
import { ApiError, api } from "@/lib/api";
import { approvalPromise } from "@/lib/approval";
import { PROVIDER_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { useApprovalMode } from "@/stores/useApprovalModeStore";
import type { EditorOptions, ProviderName } from "@/types/api";

import {
  type AgentForm,
  emptyForm,
  forcesLocal,
  formFrom,
  missingToolsets,
  slugify,
  toPayload,
  toStarters,
  validate,
} from "./form";
import { iconLabel, previewApps } from "./preview";

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

/** Champ de chaque erreur de validation, dans l'ordre du formulaire (focus sur la première). */
const ERROR_FIELDS: [keyof AgentForm, string][] = [
  ["display_name", "display"],
  ["name", "name"],
  ["description", "description"],
  ["system_prompt", "prompt"],
  ["toolsets", "toolsets"],
  ["startersText", "starters"],
];

/** Sans l'erreur d'un champ (corrigé depuis) : l'erreur ne reste pas affichée sous un champ modifié. */
const without = (errors: Record<string, string>, key: string) =>
  key in errors ? Object.fromEntries(Object.entries(errors).filter(([k]) => k !== key)) : errors;

export function AgentEditor({ open, editing, onOpenChange, onSaved }: AgentEditorProps) {
  const approvalMode = useApprovalMode();
  const [options, setOptions] = useState<EditorOptions | null>(null);
  // Monté à chaque ouverture (clé dans Workspace) : l'état initial suffit à le réinitialiser
  const [form, setForm] = useState<AgentForm>(emptyForm);
  const [nameTouched, setNameTouched] = useState(!!editing);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Boîtes de la définition chargée : celles absentes du catalogue restent listées après retrait (« Remettre »)
  const [loadedToolsets, setLoadedToolsets] = useState<string[]>([]);
  // Agent à modifier illisible : enregistrer écraserait sa définition avec un formulaire vide
  const [loadFailed, setLoadFailed] = useState(false);
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
        .then((definition) => {
          if (!alive) return;
          setForm(formFrom(definition));
          setLoadedToolsets(definition.toolsets);
        })
        .catch((err: unknown) => {
          if (alive) setLoadFailed(true);
          fail("Agent introuvable.")(err);
        })
        .finally(() => alive && setLoading(false));
    }
    return () => {
      alive = false;
    };
  }, [editing]);

  const toolsets = options?.toolsets.filter((t) => t.id !== "core") ?? [];
  // Boîtes inconnues de cette installation (constat G-08) : ni cochables ni perdues en silence
  const missing = options ? missingToolsets(loadedToolsets, options.toolsets) : [];
  const locked = options ? forcesLocal(form, options.toolsets) : false;
  const update = <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => without(e, key));
  };

  const toggleToolset = (id: string) => {
    setForm((f) => ({
      ...f,
      toolsets: f.toolsets.includes(id) ? f.toolsets.filter((t) => t !== id) : [...f.toolsets, id],
    }));
    setErrors((e) => without(e, "toolsets"));
  };

  const field = (id: string) => `${ids}-${id}`;

  const save = async () => {
    if (!options) return;
    const found = validate(form, options.reserved_names, !!editing);
    setErrors(found);
    const first = ERROR_FIELDS.find(([key]) => found[key]);
    if (first) {
      document.getElementById(field(first[1]))?.focus();
      return;
    }
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

  const icons = options?.icons ?? Object.keys(AGENT_ICONS);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" scroll="body">
        <DialogHeader>
          <DialogTitle>{editing ? "Modifier l'agent" : "Créer un agent"}</DialogTitle>
          <DialogDescription>
            Un agent, c&apos;est un rôle, des consignes et des outils. {approvalPromise(approvalMode)}
          </DialogDescription>
        </DialogHeader>

        <form
          aria-busy={loading}
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <DialogBody className="md:grid-cols-[minmax(0,1fr)_15rem] md:gap-6">
            {/* Colonnes selon la largeur du formulaire (requêtes de conteneur), pas de l'écran : l'aperçu la réduit ≥ md */}
            <div
              className={cn(
                "@container grid grid-cols-[minmax(0,1fr)] content-start gap-5",
                loading && "pointer-events-none opacity-60",
              )}
            >
              <div className="grid gap-4 @sm:grid-cols-[minmax(0,1fr)_auto]">
                <Field id={field("display")} label="Nom" error={errors.display_name}>
                  {(a11y) => (
                    <Input
                      {...a11y}
                      value={form.display_name}
                      maxLength={60}
                      onChange={(e) => {
                        update("display_name", e.target.value);
                        if (!editing && !nameTouched) update("name", slugify(e.target.value));
                      }}
                      placeholder="Veille concurrentielle"
                    />
                  )}
                </Field>
                <Field id={field("category")} label="Catégorie">
                  {(a11y) => (
                    <Input
                      {...a11y}
                      value={form.category}
                      maxLength={40}
                      onChange={(e) => update("category", e.target.value)}
                      className="@sm:w-44"
                    />
                  )}
                </Field>
              </div>

              {!editing && (
                <Field
                  id={field("name")}
                  label="Identifiant"
                  hint="Utilisé dans l'adresse de l'agent. Ne peut plus changer ensuite."
                  error={errors.name}
                >
                  {(a11y) => (
                    <Input
                      {...a11y}
                      value={form.name}
                      spellCheck={false}
                      onChange={(e) => {
                        setNameTouched(true);
                        update("name", e.target.value);
                      }}
                      className="font-mono"
                    />
                  )}
                </Field>
              )}

              <Field id={field("description")} label="Rôle en une phrase" error={errors.description}>
                {(a11y) => (
                  <Input
                    {...a11y}
                    value={form.description}
                    maxLength={300}
                    onChange={(e) => update("description", e.target.value)}
                    placeholder="Résume l'actualité des concurrents et propose des actions."
                  />
                )}
              </Field>

              <IconPicker icons={icons} value={form.icon} onChange={(icon) => update("icon", icon)} />

              <Field
                id={field("prompt")}
                label="Consignes"
                hint="Qui est l'agent, ce qu'il fait, comment il répond. Les règles communes de Nexus (français, artefacts, validation) sont ajoutées automatiquement."
                error={errors.system_prompt}
              >
                {(a11y) => (
                  <Textarea
                    {...a11y}
                    value={form.system_prompt}
                    onChange={(e) => update("system_prompt", e.target.value)}
                    placeholder={PROMPT_HINT}
                    className="min-h-32"
                  />
                )}
              </Field>

              <fieldset className="grid min-w-0 gap-2">
                <legend className="text-sm font-medium">Outils</legend>
                <p className="-mt-1 text-xs text-muted-foreground">
                  Date, heure et publication d&apos;artefacts sont toujours inclus.
                </p>
                <div className="grid gap-2 @lg:grid-cols-2">
                  {toolsets.map((t, index) => {
                    const checked = form.toolsets.includes(t.id);
                    return (
                      <label
                        key={t.id}
                        className={cn(
                          "flex cursor-pointer gap-2.5 rounded-lg border p-2.5 text-sm transition-[border-color,background-color] has-focus-visible:shadow-focus",
                          checked
                            ? "border-atelier-border bg-signature-faint"
                            : "border-atelier-line bg-card hover:border-atelier-border",
                        )}
                      >
                        <Checkbox
                          id={index === 0 ? field("toolsets") : undefined}
                          checked={checked}
                          aria-invalid={errors.toolsets ? true : undefined}
                          aria-describedby={errors.toolsets ? field("toolsets-note") : undefined}
                          onCheckedChange={() => toggleToolset(t.id)}
                          className="mt-0.5"
                        />
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-1.5 font-medium">
                            {t.app && <AppChip app={t.app} iconOnly className="size-5" />}
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
                {missing.length > 0 && (
                  <MissingToolsets ids={missing} kept={form.toolsets} onToggle={toggleToolset} />
                )}
                {errors.toolsets && (
                  <p id={field("toolsets-note")} className="text-xs text-destructive-ink">
                    {errors.toolsets}
                  </p>
                )}
              </fieldset>

              <div className="grid gap-4 @lg:grid-cols-2">
                <Field
                  id={field("provider")}
                  label="Moteur par défaut"
                  hint={locked ? "Imposé par un outil sensible : ses données ne quittent pas la machine." : undefined}
                >
                  {(a11y) =>
                    locked ? (
                      <NativeSelect {...a11y} disabled value="ollama" className="w-full [&_select]:h-9">
                        <option value="ollama">{PROVIDER_LABEL.ollama}, verrouillé</option>
                      </NativeSelect>
                    ) : (
                      <NativeSelect
                        {...a11y}
                        className="w-full [&_select]:h-9"
                        value={form.privacy === "local_only" ? "local" : (form.default_provider ?? "")}
                        onChange={(e) => {
                          const v = e.target.value;
                          update("privacy", v === "local" ? "local_only" : "standard");
                          update("default_provider", v === "" || v === "local" ? null : (v as ProviderName));
                        }}
                      >
                        <option value="">Celui choisi dans la conversation</option>
                        <option value="anthropic">{PROVIDER_LABEL.anthropic}</option>
                        <option value="ollama">{PROVIDER_LABEL.ollama}</option>
                        <option value="local">Toujours local (verrouillé)</option>
                      </NativeSelect>
                    )
                  }
                </Field>
                <Field
                  id={field("starters")}
                  label="Exemples de demandes"
                  hint="Un par ligne, six au plus."
                  error={errors.startersText}
                >
                  {(a11y) => (
                    <Textarea
                      {...a11y}
                      value={form.startersText}
                      onChange={(e) => update("startersText", e.target.value)}
                      rows={3}
                      className="min-h-20"
                    />
                  )}
                </Field>
              </div>
            </div>

            <AgentPreview
              form={form}
              apps={options ? previewApps(form.toolsets, options.toolsets) : []}
              local={locked || form.privacy === "local_only"}
            />
          </DialogBody>

          {serverError && (
            <div className="shrink-0 px-6 pt-3">
              <Callout tone="destructive" role="alert">
                {serverError}
              </Callout>
            </div>
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
            <Button type="submit" disabled={saving || loading || loadFailed || !options}>
              <PencilLine />
              {editing ? "Enregistrer" : "Créer l'agent"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface FieldA11y {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
}

/** Libellé + champ + aide ou erreur, reliées au champ par aria-describedby. */
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
  children: (a11y: FieldA11y) => ReactNode;
}) {
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className="grid content-start gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children({ id, "aria-describedby": note ? noteId : undefined, "aria-invalid": error ? true : undefined })}
      {note && (
        <p id={noteId} className={cn("text-xs", error ? "text-destructive-ink" : "text-muted-foreground")}>
          {note}
        </p>
      )}
    </div>
  );
}

/**
 * Boîtes de la définition que cette installation ne connaît plus (extension retirée de
 * NEXUS_PLUGINS ou non chargée) : l'agent fonctionne sans elles ; « Retirer » les enlève de la
 * définition à l'enregistrement, « Remettre » annule avant d'enregistrer.
 */
function MissingToolsets({ ids, kept, onToggle }: { ids: string[]; kept: string[]; onToggle: (id: string) => void }) {
  return (
    <ul aria-label="Boîtes indisponibles" className="grid gap-2">
      {ids.map((id) => {
        const present = kept.includes(id);
        return (
          <li
            key={id}
            className={cn(
              "flex items-start gap-2.5 rounded-lg border border-dashed p-2.5 text-sm",
              present ? "border-warning/40 bg-warning/8" : "border-atelier-line",
            )}
          >
            <Unplug className={cn("mt-0.5 size-4 shrink-0", present ? "text-warning" : "text-muted-foreground")} aria-hidden />
            <span className="min-w-0 flex-1">
              <span className={cn("block font-mono text-[13px] font-medium break-all", !present && "text-muted-foreground line-through")}>
                {id}
              </span>
              <span className={cn("mt-0.5 block text-xs", present ? "text-warning-ink" : "text-muted-foreground")}>
                {present
                  ? "Boîte indisponible : extension non chargée. Ses outils ne sont plus proposés à l'agent."
                  : "Retirée de l'agent à l'enregistrement."}
              </span>
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={present ? `Retirer la boîte ${id}` : `Remettre la boîte ${id}`}
              onClick={() => onToggle(id)}
            >
              {present ? "Retirer" : "Remettre"}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}

const ARROW_STEP: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

/** Choix de l'icône : groupe radio (flèches pour se déplacer), chaque icône nommée en français. */
function IconPicker({ icons, value, onChange }: { icons: string[]; value: string; onChange: (icon: string) => void }) {
  const labelId = useId();
  const current = icons.includes(value) ? value : icons[0];
  const move = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = ARROW_STEP[e.key];
    const target = e.key === "Home" ? 0 : e.key === "End" ? icons.length - 1 : step ? (index + step + icons.length) % icons.length : null;
    if (target === null) return;
    e.preventDefault();
    onChange(icons[target]!);
    const buttons = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=radio]");
    buttons?.[target]?.focus();
  };
  return (
    <div className="grid gap-1.5">
      {/* Nom de l'icône choisie affiché, mais pas répété dans le nom du groupe (déjà annoncé par l'option cochée) */}
      <p className="text-sm font-medium">
        <span id={labelId}>Icône</span> <span className="font-normal text-muted-foreground">: {iconLabel(value)}</span>
      </p>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-labelledby={labelId}>
        {icons.map((icon, index) => {
          const checked = icon === value;
          return (
            <button
              key={icon}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-label={iconLabel(icon)}
              title={iconLabel(icon)}
              tabIndex={icon === current ? 0 : -1}
              onClick={() => onChange(icon)}
              onKeyDown={(e) => move(e, index)}
              className={cn(
                "grid size-9 place-items-center rounded-lg border transition-colors focus-visible:shadow-focus focus-visible:outline-none",
                checked
                  ? "border-atelier-border bg-signature-soft text-accent-ink"
                  : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <AgentIcon icon={icon} className="size-4" aria-hidden />
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Aperçu (≥ md) : l'entrée de l'agent dans la liste et son accueil, tels qu'ils apparaîtront,
 * avec les applications touchées par les outils cochés.
 */
function AgentPreview({ form, apps, local }: { form: AgentForm; apps: string[]; local: boolean }) {
  const name = form.display_name.trim() || "Nouvel agent";
  const starters = toStarters(form.startersText).slice(0, 3);
  return (
    <aside aria-label="Aperçu de l'agent" className="hidden content-start gap-4 md:sticky md:top-0 md:grid md:self-start">
      <SectionLabel as="p">Aperçu</SectionLabel>
      <div className="grid gap-1.5">
        <p className="text-xs text-muted-foreground">Dans la liste des agents</p>
        <div className="atelier-nav-active flex items-center gap-2.5 rounded-lg px-1.5 py-1 text-[13px] font-semibold">
          <AgentTile icon={form.icon} size="sm" variant="glass" />
          <span className="min-w-0 flex-1 truncate">{name}</span>
          {local && (
            <>
              <Lock className="size-3 shrink-0 text-muted-foreground" aria-hidden />
              <span className="sr-only">100 % local</span>
            </>
          )}
        </div>
        <p className="truncate text-xs text-muted-foreground">Catégorie : {form.category.trim() || "Mes agents"}</p>
      </div>
      <div className="grid gap-1.5">
        <p className="text-xs text-muted-foreground">Accueil de la conversation</p>
        <Card className="gap-3 p-4">
          <AgentTile icon={form.icon} variant="glass" />
          <div className="min-w-0">
            <p className="truncate text-base font-semibold tracking-tight">{name}</p>
            <p className="mt-1 line-clamp-3 text-[13px] text-muted-foreground">
              {form.description.trim() || "Son rôle en une phrase."}
            </p>
          </div>
          {apps.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Travaille avec</span>
              {apps.map((app) => (
                <AppChip key={app} app={app} />
              ))}
            </div>
          )}
          {local && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Lock className="size-3.5 shrink-0 text-accent-ink" aria-hidden />
              Modèle local uniquement
            </p>
          )}
          {starters.length > 0 && (
            <ul className="grid gap-1.5">
              {starters.map((starter) => (
                <li key={starter} className="truncate rounded-lg border border-atelier-line px-2.5 py-1.5 text-xs">
                  {starter}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </aside>
  );
}
