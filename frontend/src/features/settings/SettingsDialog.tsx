"use client";

import { CircleCheck, CircleX, LoaderCircle, Settings } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AppStatus, ProviderStatus, SettingsField, SettingsView } from "@/types/api";

import { CHOICE_LABELS, type Draft, byGroup, changes, initialDraft } from "./form";

/** Bouton « Réglages » et fenêtre de configuration (clé Claude, modèles, apps, GitHub). */
export function SettingsDialog({ onSaved }: { onSaved: () => Promise<void> | void }) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Réglages" title="Réglages">
          <Settings />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl grid-cols-[minmax(0,1fr)]">
        <DialogHeader>
          <DialogTitle>Réglages</DialogTitle>
          <DialogDescription>
            Moteurs d&apos;IA, adresses des applications Atelier et accès GitHub. Les changements
            s&apos;appliquent tout de suite.
          </DialogDescription>
        </DialogHeader>
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

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .settings(ctrl.signal)
      .then((view) => {
        setLoad({ status: "ready", view });
        setDraft(initialDraft(view));
      })
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted)
          setLoad({ status: "error", message: err instanceof ApiError ? err.message : "Le serveur ne répond pas." });
      });
    return () => ctrl.abort();
  }, []);

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
    <section aria-label="Vérification" className="rounded-md border bg-muted/40 p-3">
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
