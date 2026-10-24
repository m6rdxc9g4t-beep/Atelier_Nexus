"use client";

import { CircleCheck, CircleX, LoaderCircle, Settings } from "lucide-react";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/theme/theme-toggle";
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
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useApprovalModeStore } from "@/stores/useApprovalModeStore";
import { useUiStore } from "@/stores/useUiStore";
import type { AppStatus, ProviderStatus, SettingsField, SettingsView } from "@/types/api";

import { CHOICE_HELP, CHOICE_LABELS, type Draft, GROUP_NOTES, RADIO_FIELDS, byGroup, changes, initialDraft } from "./form";

/** Bouton « Réglages » (barre latérale) : ouvre la fenêtre unique des Réglages. */
export function SettingsButton({ className }: { className?: string }) {
  const openSettings = useUiStore((s) => s.openSettings);
  return (
    <Button variant="ghost" size="icon-sm" aria-label="Réglages" title="Réglages" className={className} onClick={openSettings}>
      <Settings />
    </Button>
  );
}

/**
 * Fenêtre de configuration (clé Claude, modèles, apps, Cuisine, GitHub), montée une seule fois
 * dans l'écran principal et ouverte par `useUiStore` (bouton Réglages, messages « non configuré »).
 */
export function SettingsDialog({ onSaved }: { onSaved: () => Promise<void> | void }) {
  const open = useUiStore((s) => s.settingsOpen);
  const setOpen = useUiStore((s) => s.setSettingsOpen);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-2xl grid-cols-[minmax(0,1fr)]">
        <DialogHeader>
          <DialogTitle>Réglages</DialogTitle>
          <DialogDescription>
            Apparence, validation des actions, moteurs d&apos;IA, adresses des applications Atelier, compte
            Atelier Cuisine et accès GitHub. Les changements s&apos;appliquent tout de suite.
          </DialogDescription>
        </DialogHeader>
        {/* Préférence propre à cet appareil (localStorage), indépendante du serveur */}
        <section aria-labelledby="settings-theme" className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 id="settings-theme" className="text-sm font-semibold">
              Apparence
            </h3>
            <p className="text-xs text-muted-foreground">Thème clair, sombre ou celui du système.</p>
          </div>
          <ThemeToggle />
        </section>
        {/* Monté à chaque ouverture : valeurs relues */}
        {open && <SettingsForm onSaved={onSaved} onClose={() => setOpen(false)} />}
      </DialogContent>
    </Dialog>
  );
}

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; view: SettingsView };
type Check = { providers: ProviderStatus[]; apps: AppStatus[] };

function SettingsForm({ onSaved, onClose }: { onSaved: () => Promise<void> | void; onClose: () => void }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const approvalSaved = useApprovalModeStore((s) => s.fromSettings);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .settings(ctrl.signal)
      .then((view) => {
        setLoad({ status: "ready", view });
        setDraft(initialDraft(view));
        approvalSaved(view);
      })
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted)
          setLoad({ status: "error", message: err instanceof ApiError ? err.message : "Le serveur ne répond pas." });
      });
    return () => ctrl.abort();
  }, [approvalSaved]);

  if (load.status === "loading") return <p className="text-sm text-muted-foreground">Chargement…</p>;
  if (load.status === "error")
    return (
      <p role="alert" className="text-sm text-destructive">
        Réglages indisponibles : {load.message}
      </p>
    );

  const view = load.view;
  const pending = changes(view, draft);
  const dirty = Object.keys(pending).length > 0;
  const set = (key: string, patch: Partial<Draft[string]>) =>
    setDraft((d) => ({ ...d, [key]: { ...(d[key] ?? { value: "", clear: false }), ...patch } }));

  const save = async () => {
    setSaving(true);
    setErrors({});
    setMessage(null);
    try {
      const next = await api.updateSettings(pending);
      setLoad({ status: "ready", view: next });
      setDraft(initialDraft(next));
      approvalSaved(next);
      await onSaved();
      const [providers, apps] = await Promise.all([api.providers(), api.appsStatus()]);
      setCheck({ providers, apps });
      setMessage("Réglages enregistrés.");
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fields).length) setErrors(err.fields);
      setMessage(err instanceof ApiError ? err.message : "Enregistrement impossible.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="flex min-h-0 flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty && !saving) void save();
      }}
    >
      {byGroup(view).map(([group, fields]) => (
        <fieldset key={group} className="flex flex-col gap-3">
          <legend className="mb-1 text-sm font-semibold">{group}</legend>
          {GROUP_NOTES[group] && <p className="-mt-2 text-xs text-muted-foreground">{GROUP_NOTES[group]}</p>}
          {fields.map((field) => (
            <FieldRow
              key={field.key}
              field={field}
              draft={draft[field.key] ?? { value: "", clear: false }}
              error={errors[field.key]}
              onChange={(patch) => set(field.key, patch)}
            />
          ))}
        </fieldset>
      ))}

      {check && <CheckSummary check={check} />}

      <p className="text-xs text-muted-foreground">
        Fichier : <code className="font-mono break-all">{view.env_file}</code>
      </p>

      <DialogFooter className="items-center sm:justify-between">
        <p role="status" className={cn("text-sm", Object.keys(errors).length ? "text-destructive" : "text-muted-foreground")}>
          {message}
        </p>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Fermer
          </Button>
          <Button type="submit" disabled={!dirty || saving}>
            {saving && <LoaderCircle className="animate-spin" />}
            Enregistrer
          </Button>
        </div>
      </DialogFooter>
    </form>
  );
}

function FieldRow({
  field,
  draft,
  error,
  onChange,
}: {
  field: SettingsField;
  draft: Draft[string];
  error: string | undefined;
  onChange: (patch: Partial<Draft[string]>) => void;
}) {
  const id = `setting-${field.key}`;
  const locked = field.source === "environnement";
  const note = locked ? "Fixé par une variable d'environnement : modifiable seulement à la source." : field.help;
  const describedBy = note || error ? `${id}-note` : undefined;

  if (field.kind === "choice" && RADIO_FIELDS.has(field.key)) {
    return <RadioRow field={field} draft={draft} locked={locked} note={locked ? note : ""} error={error} onChange={onChange} />;
  }

  let control;
  if (field.kind === "choice") {
    control = (
      <NativeSelect
        id={id}
        value={draft.value}
        disabled={locked}
        aria-describedby={describedBy}
        onChange={(e) => onChange({ value: e.target.value })}
      >
        {field.choices.map((c) => (
          <option key={c} value={c}>
            {CHOICE_LABELS[c] ?? c}
          </option>
        ))}
      </NativeSelect>
    );
  } else if (field.kind === "secret") {
    control = (
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={draft.value}
          disabled={locked || draft.clear}
          aria-describedby={describedBy}
          placeholder={field.configured ? `Configurée (${field.hint ?? "masquée"}) : laisser vide pour la garder` : "Non configurée"}
          onChange={(e) => onChange({ value: e.target.value })}
        />
        {field.configured && !locked && (
          <Button
            type="button"
            variant={draft.clear ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={draft.clear}
            onClick={() => onChange({ clear: !draft.clear, value: "" })}
          >
            {draft.clear ? "Annuler" : "Effacer"}
          </Button>
        )}
      </div>
    );
  } else {
    control = (
      <Input
        id={id}
        type={field.kind === "url" ? "url" : "text"}
        spellCheck={false}
        value={draft.value}
        disabled={locked}
        aria-describedby={describedBy}
        aria-invalid={error ? true : undefined}
        onChange={(e) => onChange({ value: e.target.value })}
      />
    );
  }

  return (
    <div className="grid gap-1.5 sm:grid-cols-[13rem_minmax(0,1fr)] sm:items-start sm:gap-x-4">
      <label htmlFor={id} className="pt-2 text-sm">
        {field.label}
      </label>
      <div className="flex min-w-0 flex-col gap-1">
        {control}
        {(error || note) && (
          <p id={`${id}-note`} className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>
            {error ?? note}
          </p>
        )}
      </div>
    </div>
  );
}

/** Choix fermé présenté en boutons radio : chaque option avec son explication. */
function RadioRow({
  field,
  draft,
  locked,
  note,
  error,
  onChange,
}: {
  field: SettingsField;
  draft: Draft[string];
  locked: boolean;
  note: string;
  error: string | undefined;
  onChange: (patch: Partial<Draft[string]>) => void;
}) {
  const id = `setting-${field.key}`;
  return (
    <div role="radiogroup" aria-labelledby={`${id}-label`} aria-describedby={note || error ? `${id}-note` : undefined} className="grid gap-2">
      <p id={`${id}-label`} className="text-sm">
        {field.label}
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {field.choices.map((choice) => {
          const checked = draft.value === choice;
          return (
            <label
              key={choice}
              className={cn(
                "flex cursor-pointer items-start gap-2 rounded-md border border-atelier-line bg-card p-3 text-sm has-focus-visible:shadow-focus",
                checked && "atelier-nav-active",
                locked && "cursor-not-allowed opacity-60",
              )}
            >
              <input
                type="radio"
                name={id}
                value={choice}
                checked={checked}
                disabled={locked}
                onChange={() => onChange({ value: choice })}
                className="mt-0.5 accent-primary"
              />
              <span className="grid gap-0.5">
                <span className="font-medium">{CHOICE_LABELS[choice] ?? choice}</span>
                {CHOICE_HELP[choice] && <span className="text-xs text-muted-foreground">{CHOICE_HELP[choice]}</span>}
              </span>
            </label>
          );
        })}
      </div>
      {(error || note) && (
        <p id={`${id}-note`} className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>
          {error ?? note}
        </p>
      )}
    </div>
  );
}

const PROVIDER_NAMES: Record<string, string> = { anthropic: "Claude", ollama: "Ollama (local)" };

function CheckSummary({ check }: { check: Check }) {
  const lines = [
    ...check.providers.map((p) => ({
      label: PROVIDER_NAMES[p.name] ?? p.name,
      ok: p.available,
      detail: !p.configured
        ? "non configuré"
        : p.available
          ? `${p.is_default ? "moteur par défaut, " : ""}${p.default_model}`
          : (p.error ?? "injoignable"),
    })),
    ...check.apps
      .filter((a) => a.configured)
      .map((a) => ({ label: a.label, ok: a.available, detail: a.available ? (a.detail ?? "") : (a.error ?? "injoignable") })),
  ];
  return (
    <section aria-label="Vérification" className="rounded-md border border-atelier-border-soft bg-signature-faint p-3">
      <h3 className="mb-2 text-sm font-medium">Vérification</h3>
      <ul className="flex flex-col gap-1.5">
        {lines.map((l) => (
          <li key={l.label} className="flex items-start gap-2 text-sm">
            {l.ok ? (
              <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" aria-label="joignable" />
            ) : (
              <CircleX className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="injoignable" />
            )}
            <span className="min-w-0">
              <span className="font-medium">{l.label}</span>
              <span className="text-muted-foreground"> : {l.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
