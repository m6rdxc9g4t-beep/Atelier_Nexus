"use client";

import {
  CircleCheck,
  Cpu,
  LayoutGrid,
  LoaderCircle,
  Lock,
  type LucideIcon,
  Palette,
  RefreshCw,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { appIcon } from "@/components/layout/appIcons";
import { ThemeToggle } from "@/components/theme/theme-toggle";
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
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusDot } from "@/components/ui/status-dot";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useApprovalModeStore } from "@/stores/useApprovalModeStore";
import { useUiStore } from "@/stores/useUiStore";
import type { SettingsField, SettingsView } from "@/types/api";

import { CHOICE_HELP, CHOICE_LABELS, type Draft, GROUP_NOTES, RADIO_FIELDS, byGroup, changes, initialDraft } from "./form";
import {
  type Check,
  type CheckLine,
  SECTION_TITLE,
  type Section,
  type SectionStatus,
  checkLines,
  countBySection,
  firstFieldWith,
  firstSectionWith,
  hasStatus,
  pendingLabel,
  sectionStatus,
  sections,
} from "./status";

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
 * Fenêtre de configuration (apparence, validation, moteurs, apps, Cuisine, GitHub), montée une
 * seule fois dans l'écran principal et ouverte par `useUiStore` (bouton Réglages, messages
 * « non configuré »). Rubriques à gauche (en haut sur mobile), pied fixe avec « Enregistrer ».
 */
export function SettingsDialog({ onSaved }: { onSaved: () => Promise<void> | void }) {
  const open = useUiStore((s) => s.settingsOpen);
  const setOpen = useUiStore((s) => s.setSettingsOpen);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {/* Hauteur fixe : passer d'une rubrique à l'autre ne fait pas sauter la fenêtre */}
      <DialogContent size="lg" scroll="body" className="h-[min(42rem,calc(100dvh-2rem))]">
        <DialogHeader>
          <DialogTitle>Réglages</DialogTitle>
          <DialogDescription>
            Apparence de cet appareil et configuration du serveur Nexus. Les changements enregistrés
            s&apos;appliquent tout de suite.
          </DialogDescription>
        </DialogHeader>
        {/* Monté à chaque ouverture : valeurs et états relus */}
        {open && <SettingsForm onSaved={onSaved} onClose={() => setOpen(false)} />}
      </DialogContent>
    </Dialog>
  );
}

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; view: SettingsView };

const SECTION_ICON: Record<Section, LucideIcon> = {
  Apparence: Palette,
  "Validation des actions": ShieldCheck,
  Modèles: Cpu,
  "Applications Atelier": LayoutGrid,
  "Atelier Cuisine": appIcon("cuisine"),
  GitHub: appIcon("github"),
};

/** Rubrique ouverte en dernier : retrouvée à la réouverture des Réglages pendant la visite. */
let lastSection: Section = "Apparence";

function SettingsForm({ onSaved, onClose }: { onSaved: () => Promise<void> | void; onClose: () => void }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [check, setCheck] = useState<Check | null>(null);
  const [checking, setChecking] = useState(true);
  // Vérification impossible (serveur joint mais état des moteurs ou des apps illisible)
  const [checkFailed, setCheckFailed] = useState(false);
  const [section, setSection] = useState<Section>(lastSection);
  const body = useRef<HTMLDivElement>(null);
  // Champ en erreur à focaliser, une fois sa rubrique affichée (après le rendu)
  const focusField = useRef<string | null>(null);
  // Rubriques en colonne à partir de sm : les flèches suivent le sens de la liste
  const vertical = useMediaQuery("(min-width: 640px)");
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

  // État des moteurs et des apps (pastilles des rubriques), vérifié dès l'ouverture
  useEffect(() => {
    const ctrl = new AbortController();
    Promise.all([api.providers(ctrl.signal), api.appsStatus(ctrl.signal)])
      .then(([providers, apps]) => setCheck({ providers, apps }))
      .catch(() => {
        // État inconnu : rubriques sans pastille, avec « Vérifier » pour réessayer
        if (!ctrl.signal.aborted) setCheckFailed(true);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setChecking(false);
      });
    return () => ctrl.abort();
  }, []);

  const recheck = () => {
    setChecking(true);
    setCheckFailed(false);
    Promise.all([api.providers(), api.appsStatus()])
      .then(([providers, apps]) => setCheck({ providers, apps }))
      .catch(() => {
        setCheck(null);
        setCheckFailed(true);
      })
      .finally(() => setChecking(false));
  };

  // Après le rendu qui affiche la rubrique en erreur : focus sur son premier champ refusé
  useEffect(() => {
    if (!focusField.current) return;
    document.getElementById(`setting-${focusField.current}`)?.focus();
    focusField.current = null;
  });

  const view = load.status === "ready" ? load.view : null;
  const groups = view ? byGroup(view) : [];
  const order = sections(groups.map(([group]) => group));
  // Pendant le chargement, la rubrique mémorisée reste choisie (squelette) ; absente ensuite : Apparence
  const current: Section = load.status === "loading" || order.includes(section) ? section : "Apparence";
  const pending = view ? changes(view, draft) : {};
  const pendingKeys = Object.keys(pending);
  const dirty = pendingKeys.length > 0;
  const pendingBy = view ? countBySection(view, pendingKeys) : {};
  const errorBy = view ? countBySection(view, Object.keys(errors)) : {};

  // Mémorisée pour la prochaine ouverture (hors rendu)
  useEffect(() => {
    lastSection = section;
  }, [section]);

  const choose = (next: Section) => {
    setSection(next);
    body.current?.scrollTo({ top: 0 });
  };
  const set = (key: string, patch: Partial<Draft[string]>) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [key]: { ...(d[key] ?? { value: "", clear: false }), ...patch } }));
  };

  const save = async () => {
    if (!view) return;
    setSaving(true);
    setErrors({});
    setFailure(null);
    setSaved(false);
    let done = false;
    try {
      const next = await api.updateSettings(pending);
      setLoad({ status: "ready", view: next });
      setDraft(initialDraft(next));
      approvalSaved(next);
      setSaved(true);
      done = true;
    } catch (err) {
      const fields = err instanceof ApiError ? err.fields : {};
      const keys = Object.keys(fields);
      if (keys.length) {
        setErrors(fields);
        // Aucune erreur dans la rubrique affichée : on va à la première rubrique en erreur
        const target = countBySection(view, keys)[current] ? current : firstSectionWith(view, order, keys);
        if (target && target !== current) choose(target);
        focusField.current = target ? firstFieldWith(view, target, keys) : null;
      }
      setFailure(err instanceof ApiError ? err.message : "Enregistrement impossible.");
    } finally {
      setSaving(false);
    }
    if (!done) return;
    // Catalogue rechargé et état revérifié à part : un moteur injoignable ou un rechargement
    // manqué n'est pas un échec d'enregistrement (le fichier est déjà écrit)
    recheck();
    try {
      await onSaved();
    } catch {
      /* catalogue relu au prochain rechargement périodique */
    }
  };

  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(e) => {
        e.preventDefault();
        if (dirty && !saving) void save();
      }}
    >
      <Tabs
        value={current}
        onValueChange={(v) => choose(v as Section)}
        orientation={vertical ? "vertical" : "horizontal"}
        className="min-h-0 flex-1 gap-0 sm:flex-row"
      >
        <TabsList
          aria-label="Rubriques des Réglages"
          className="h-auto w-full shrink-0 justify-start gap-0.5 overflow-x-auto rounded-none border-0 border-b border-atelier-line bg-transparent p-2 sm:w-52 sm:flex-col sm:items-stretch sm:overflow-x-visible sm:overflow-y-auto sm:border-r sm:border-b-0 sm:p-3"
        >
          {order.map((s) => (
            <SectionTab
              key={s}
              section={s}
              status={sectionStatus(s, check, checking)}
              pending={pendingBy[s] ?? 0}
              errors={errorBy[s] ?? 0}
            />
          ))}
          {load.status === "loading" &&
            [0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-9 w-28 shrink-0 rounded-lg sm:w-auto" />)}
        </TabsList>

        <DialogBody ref={body} className="min-w-0">
          {load.status === "error" && (
            <Callout tone="destructive" role="alert" title="Réglages du serveur indisponibles">
              {load.message} Seule l&apos;apparence de cet appareil reste modifiable.
            </Callout>
          )}

          <TabsContent value="Apparence" className="grid grid-cols-[minmax(0,1fr)] content-start gap-5">
            <SectionHeader section="Apparence">
              Thème clair, sombre ou celui du système. Préférence propre à cet appareil, appliquée tout
              de suite (sans « Enregistrer »).
            </SectionHeader>
            <ThemeToggle labels className="w-fit" />
          </TabsContent>

          {load.status === "loading" && current !== "Apparence" && (
            <div className="grid gap-5" aria-busy>
              <span className="sr-only" role="status">
                Chargement des réglages…
              </span>
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-full max-w-md" />
              {[0, 1, 2].map((i) => (
                <div key={i} className="grid gap-1.5">
                  <Skeleton className="h-4 w-36" />
                  <Skeleton className="h-9 w-full" />
                </div>
              ))}
            </div>
          )}

          {view &&
            groups.map(([group, fields]) => {
              const lines = check ? checkLines(group, check) : [];
              return (
                <TabsContent key={group} value={group} className="grid grid-cols-[minmax(0,1fr)] content-start gap-5">
                  <SectionHeader
                    section={group}
                    action={
                      hasStatus(group) && (
                        <Button type="button" variant="ghost" size="sm" disabled={checking} onClick={recheck}>
                          <RefreshCw className={cn(checking && "motion-safe:animate-spin")} />
                          Vérifier
                        </Button>
                      )
                    }
                  >
                    {GROUP_NOTES[group]}
                  </SectionHeader>
                  {checkFailed && !checking && hasStatus(group) && (
                    <Callout tone="warning" title="État inconnu">
                      La vérification des moteurs et des applications n&apos;a pas abouti. Les réglages
                      restent modifiables ; « Vérifier » relance le contrôle.
                    </Callout>
                  )}
                  {lines.length > 0 && <CheckList lines={lines} checking={checking} />}
                  {fields.map((field) => (
                    <FieldRow
                      key={field.key}
                      field={field}
                      draft={draft[field.key] ?? { value: "", clear: false }}
                      changed={field.key in pending}
                      error={errors[field.key]}
                      onChange={(patch) => set(field.key, patch)}
                    />
                  ))}
                  <p className="text-xs text-muted-foreground">
                    Enregistré dans <code className="font-mono break-all">{view.env_file}</code>
                  </p>
                </TabsContent>
              );
            })}
        </DialogBody>
      </Tabs>

      {failure && (
        <div className="shrink-0 px-6 pt-3">
          <Callout tone="destructive" role="alert">
            {failure}
          </Callout>
        </div>
      )}

      <DialogFooter className="flex-col items-stretch sm:flex-row sm:items-center sm:justify-between">
        <p role="status" className="flex min-h-5 items-center gap-2 text-[13px]">
          {dirty ? (
            <>
              <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-primary" />
              <span className="font-medium">{pendingLabel(pendingKeys.length)}</span>
            </>
          ) : saved ? (
            <>
              <CircleCheck className="size-4 shrink-0 text-success" aria-hidden />
              <span className="text-success-ink">Réglages enregistrés.</span>
            </>
          ) : null}
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          {dirty && (
            <Button
              type="button"
              variant="ghost"
              disabled={saving}
              onClick={() => {
                if (view) setDraft(initialDraft(view));
                setErrors({});
                setFailure(null);
              }}
            >
              Annuler les modifications
            </Button>
          )}
          <Button type="button" variant="outline" onClick={onClose}>
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

/** Entrée de la navigation : icône, titre, modifications en attente ou erreurs, pastille d'état. */
function SectionTab({
  section,
  status,
  pending,
  errors,
}: {
  section: Section;
  status: SectionStatus | null;
  pending: number;
  errors: number;
}) {
  const Icon = SECTION_ICON[section];
  const extra = [
    status?.label,
    errors ? `${errors} erreur${errors >= 2 ? "s" : ""}` : null,
    pending ? `${pending} modification${pending >= 2 ? "s" : ""} en attente` : null,
  ].filter(Boolean);
  return (
    <TabsTrigger
      value={section}
      title={status?.label}
      className={cn(
        "h-9 shrink-0 justify-start gap-2.5 rounded-lg px-2.5 text-[13px] text-foreground/85 hover:bg-accent [&_svg]:size-4",
        "data-[state=active]:bg-signature-soft data-[state=active]:font-semibold data-[state=active]:text-foreground",
        "data-[state=active]:shadow-[inset_0_-2px_0_var(--atelier-signature)] sm:data-[state=active]:shadow-[inset_3px_0_0_var(--atelier-signature)]",
      )}
    >
      <Icon aria-hidden className="text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate text-left">{SECTION_TITLE[section]}</span>
      {errors > 0 ? (
        <span aria-hidden className="text-xs font-semibold text-destructive-ink tabular-nums">
          {errors}
        </span>
      ) : pending > 0 ? (
        <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-primary" />
      ) : null}
      {status && <StatusDot status={status.status} />}
      {extra.length > 0 && <span className="sr-only">, {extra.join(", ")}</span>}
    </TabsTrigger>
  );
}

function SectionHeader({
  section,
  action,
  children,
}: {
  section: Section;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="grid min-w-0 gap-1">
        <h3 className="text-base font-semibold tracking-tight">{SECTION_TITLE[section]}</h3>
        {children && <p className="text-[13px] text-muted-foreground">{children}</p>}
      </div>
      {action}
    </div>
  );
}

/** État des moteurs ou des applications de la rubrique (vérifié à l'ouverture et après enregistrement). */
function CheckList({ lines, checking }: { lines: CheckLine[]; checking: boolean }) {
  return (
    <ul aria-label="État" className="grid gap-1.5 rounded-lg border border-atelier-line bg-sunken px-3 py-2.5">
      {lines.map((l) => (
        <li key={l.id} className="flex items-start gap-2 text-[13px]">
          <StatusDot status={checking ? "pending" : l.ok ? "up" : l.down ? "down" : "off"} className="mt-1.5" />
          <span className="min-w-0 break-words">
            <span className="font-medium">{l.label}</span>
            <span className="sr-only">{l.ok ? " (joignable)" : l.down ? " (injoignable)" : ""}</span>
            <span className="text-muted-foreground"> : {l.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function FieldRow({
  field,
  draft,
  changed,
  error,
  onChange,
}: {
  field: SettingsField;
  draft: Draft[string];
  changed: boolean;
  error: string | undefined;
  onChange: (patch: Partial<Draft[string]>) => void;
}) {
  const id = `setting-${field.key}`;
  const locked = field.source === "environnement";
  const note = locked ? "Fixé par une variable d'environnement : modifiable seulement à la source." : field.help;
  const describedBy = note || error ? `${id}-note` : undefined;
  const invalid = error ? true : undefined;

  if (field.kind === "choice" && RADIO_FIELDS.has(field.key)) {
    return (
      <RadioRow
        field={field}
        draft={draft}
        locked={locked}
        changed={changed}
        note={locked ? note : ""}
        error={error}
        onChange={onChange}
      />
    );
  }

  let control;
  if (field.kind === "choice") {
    control = (
      <NativeSelect
        id={id}
        value={draft.value}
        disabled={locked}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        className="w-full [&_select]:h-9"
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
          aria-invalid={invalid}
          placeholder={
            draft.clear
              ? "Sera retirée à l'enregistrement"
              : field.configured
                ? `Configurée (${field.hint ?? "masquée"}) : laisser vide pour la garder`
                : "Non configurée"
          }
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
        aria-invalid={invalid}
        onChange={(e) => onChange({ value: e.target.value })}
      />
    );
  }

  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <label htmlFor={id} className="text-sm font-medium">
          {field.label}
        </label>
        <FieldBadges locked={locked} changed={changed} />
      </div>
      {control}
      {(error || note) && (
        <p id={`${id}-note`} className={cn("text-xs", error ? "text-destructive-ink" : "text-muted-foreground")}>
          {error ?? note}
        </p>
      )}
    </div>
  );
}

function FieldBadges({ locked, changed }: { locked: boolean; changed: boolean }) {
  return (
    <>
      {locked && (
        <Badge variant="outline">
          <Lock aria-hidden />
          Variable d&apos;environnement
        </Badge>
      )}
      {changed && <Badge variant="signature">Modifié</Badge>}
    </>
  );
}

/** Choix fermé présenté en boutons radio : chaque option avec son explication. */
function RadioRow({
  field,
  draft,
  locked,
  changed,
  note,
  error,
  onChange,
}: {
  field: SettingsField;
  draft: Draft[string];
  locked: boolean;
  changed: boolean;
  note: string;
  error: string | undefined;
  onChange: (patch: Partial<Draft[string]>) => void;
}) {
  const id = `setting-${field.key}`;
  // Option qui reçoit l'identifiant du champ (focus sur erreur) : la cochée, sinon la première
  const focusChoice = field.choices.includes(draft.value) ? draft.value : field.choices[0];
  return (
    <div
      role="radiogroup"
      aria-labelledby={`${id}-label`}
      aria-describedby={note || error ? `${id}-note` : undefined}
      aria-invalid={error ? true : undefined}
      className="grid gap-2"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p id={`${id}-label`} className="text-sm font-medium">
          {field.label}
        </p>
        <FieldBadges locked={locked} changed={changed} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {field.choices.map((choice) => {
          const checked = draft.value === choice;
          return (
            <label
              key={choice}
              className={cn(
                "flex cursor-pointer items-start gap-2.5 rounded-lg border bg-card p-3 text-sm transition-[border-color,box-shadow,background-color] has-focus-visible:shadow-focus",
                checked ? "border-atelier-border bg-signature-faint shadow-glow" : "border-atelier-line hover:border-atelier-border",
                locked && "cursor-not-allowed opacity-60",
              )}
            >
              <input
                type="radio"
                id={choice === focusChoice ? id : undefined}
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
        <p id={`${id}-note`} className={cn("text-xs", error ? "text-destructive-ink" : "text-muted-foreground")}>
          {error ?? note}
        </p>
      )}
    </div>
  );
}
