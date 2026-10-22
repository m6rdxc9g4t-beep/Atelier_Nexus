"use client";

import {
  Braces,
  CalendarClock,
  FlaskConical,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  ShieldQuestion,
  Trash2,
  TriangleAlert,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { appTheme } from "@/features/workflows-graph/catalog";
import { RUN_STATUS } from "@/features/workflows-graph/run";
import { AppStatusDot, AppTile } from "@/features/workflows-graph/StepBadges";
import { ApiError, api } from "@/lib/api";
import { triggerReminder } from "@/lib/approval";
import { cn } from "@/lib/utils";
import { useApprovalMode } from "@/stores/useApprovalModeStore";
import type { TriggerPreset } from "@/stores/useWorkflowStudioStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { EventsCatalog, EventsCatalogApp, RunStatus, Trigger, WorkflowParam, WorkflowRun } from "@/types/api";

import {
  FILTER_OPS,
  LIMITS,
  type FilterDraft,
  type TriggerDraft,
  type TriggerErrors,
  WORKDAYS,
  bodyFromTrigger,
  catalogApp,
  draftFromTrigger,
  emptyTriggerDraft,
  eventTemplateOptions,
  filterFields,
  hasErrors,
  insertEventTemplate,
  parseSampleEvent,
  sampleEvent,
  toTriggerBody,
  validateTrigger,
} from "./form";
import {
  WEEKDAYS,
  WEEKDAY_LABEL,
  WEEKDAY_SHORT,
  countersText,
  limitsText,
  occurrenceText,
  timeAgo,
  timeUntil,
  triggerSummaryParts,
} from "./summary";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);
const REFRESH_MS = 30_000;

/** Rappel affiché partout où l'on crée ou teste un déclencheur (règle §0.1 du contrat), selon
 * le réglage APPROVAL_MODE (chaque étape, ou les écritures). */
export function ApprovalReminder({ className }: { className?: string }) {
  const { lead, tail } = triggerReminder(useApprovalMode());
  return (
    <p className={cn("flex items-start gap-1.5 rounded-md border border-warning/40 bg-warning/8 px-2 py-1.5 text-xs", className)}>
      <ShieldQuestion className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
      <span>
        {lead} <strong className="font-semibold">À valider</strong>
        {tail}
      </span>
    </p>
  );
}

function SectionTitle({ children, id }: { children: React.ReactNode; id?: string }) {
  return (
    <h3 id={id} className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
      {children}
    </h3>
  );
}

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="text-[11px] text-destructive">
      {message}
    </p>
  );
}

/**
 * Panneau « Déclencheurs » de l'éditeur : liste (résumé, actif / coupé, état, compteurs, erreurs),
 * création et modification (horaire, événement), test immédiat. Un déclencheur lance la version
 * enregistrée du workflow : il faut donc un workflow v2 enregistré.
 */
export function TriggersPanel({
  workflowId,
  dirty,
  params,
  preset,
  onPresetUsed,
  onSave,
  onRun,
}: {
  /** null : workflow pas encore enregistré */
  workflowId: string | null;
  /** Modifications non enregistrées (les déclencheurs lancent la version enregistrée) */
  dirty: boolean;
  /** Paramètres du workflow (version éditée) */
  params: WorkflowParam[];
  /** Déclencheur à préremplir (carte de la suite), ouvert dès que le workflow est enregistré */
  preset: TriggerPreset | null;
  onPresetUsed: () => void;
  /** Enregistre le workflow ; renvoie son identifiant (null si refusé) */
  onSave: () => Promise<string | null>;
  /** Exécution reçue (test, dernière exécution) : affichée dans le suivi */
  onRun: (run: WorkflowRun) => void;
}) {
  const ids = useId();
  const [triggers, setTriggers] = useState<Trigger[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<EventsCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [editing, setEditing] = useState<TriggerDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!workflowId) return;
      api
        .triggers(workflowId, signal)
        .then((items) => {
          setTriggers(items);
          setListError(null);
        })
        .catch((err: unknown) => !signal?.aborted && setListError(errorText(err, "Déclencheurs indisponibles.")));
    },
    [workflowId],
  );

  // Liste, puis relue toutes les 30 s (prochaine occurrence, compteurs) tant que l'onglet est visible
  useEffect(() => {
    if (!workflowId) return;
    const ctrl = new AbortController();
    load(ctrl.signal);
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load(ctrl.signal);
    }, REFRESH_MS);
    return () => {
      ctrl.abort();
      clearInterval(timer);
    };
  }, [workflowId, load, refresh]);

  // Catalogue des événements : lu une fois (nécessaire au résumé et au formulaire)
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .eventsCatalog(ctrl.signal)
      .then((c) => {
        setCatalog(c);
        setCatalogError(null);
      })
      .catch((err: unknown) => !ctrl.signal.aborted && setCatalogError(errorText(err, "Catalogue des événements indisponible.")));
    return () => ctrl.abort();
  }, []);

  // Déclencheur prérempli (carte de la suite) : formulaire ouvert dès que le workflow existe,
  // jusqu'à ce qu'on l'enregistre ou l'abandonne
  const presetDraft = useMemo(
    () => (preset ? emptyTriggerDraft("event", { app: preset.app, types: [...preset.types] }) : null),
    [preset],
  );
  const form = editing ?? (workflowId ? presetDraft : null);
  const closeForm = () => {
    setEditing(null);
    if (preset) onPresetUsed();
  };

  if (!workflowId)
    return (
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
        <p className="rounded-md border border-atelier-line bg-sunken px-3 py-2 text-sm text-muted-foreground">
          Enregistrez d&apos;abord le workflow (un titre et ses étapes) : un déclencheur lance sa version enregistrée, à heure
          fixe ou quand une application publie un événement.
        </p>
        {preset && (
          <p className="text-xs">
            Un déclencheur sur{" "}
            <em>{catalog ? (catalogApp(catalog, preset.app)?.events.find((e) => e.type === preset.types[0])?.label ?? preset.types[0]) : preset.types[0]}</em>{" "}
            vous attend : il s&apos;ouvrira dès l&apos;enregistrement.
          </p>
        )}
        <Button type="button" onClick={() => void onSave()}>
          <Save />
          Enregistrer le workflow
        </Button>
      </div>
    );

  const submit = async (draft: TriggerDraft) => {
    setSaving(true);
    try {
      const body = toTriggerBody(draft, params);
      const saved = draft.id ? await api.updateTrigger(draft.id, body) : await api.createTrigger(workflowId, body);
      setTriggers((items) => (items ? (draft.id ? items.map((t) => (t.id === saved.id ? saved : t)) : [...items, saved]) : [saved]));
      closeForm();
      setRefresh((r) => r + 1);
      return null;
    } catch (err) {
      return errorText(err, "Enregistrement du déclencheur impossible.");
    } finally {
      setSaving(false);
    }
  };

  if (form)
    return (
      <TriggerForm
        key={form.id ?? `nouveau-${form.kind}`}
        initial={form}
        params={params}
        catalog={catalog}
        catalogError={catalogError}
        saving={saving}
        onCancel={closeForm}
        onSubmit={submit}
      />
    );

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
      <div className="flex items-center gap-2">
        <SectionTitle id={`${ids}-list`}>Déclencheurs</SectionTitle>
        <Button type="button" variant="ghost" size="icon-sm" className="ml-auto size-7" aria-label="Actualiser les déclencheurs" onClick={() => setRefresh((r) => r + 1)}>
          <RefreshCw />
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">Lancez ce workflow tout seul : à heure fixe, ou quand une application de la suite publie un événement.</p>
      {dirty && (
        <p className="rounded-md border border-atelier-line bg-sunken px-2 py-1.5 text-xs text-muted-foreground">
          Modifications non enregistrées : les déclencheurs lancent la dernière version enregistrée.
        </p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => setEditing(emptyTriggerDraft("schedule"))}>
          <CalendarClock />
          Horaire
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => setEditing(emptyTriggerDraft("event"))}>
          <Zap />
          Événement
        </Button>
      </div>
      <ApprovalReminder />
      {listError && (
        <p role="alert" className="text-sm text-destructive">
          {listError}
        </p>
      )}
      {triggers === null && !listError && (
        <p role="status" className="text-xs text-muted-foreground">
          Lecture des déclencheurs…
        </p>
      )}
      {triggers?.length === 0 && <p className="text-xs text-muted-foreground">Aucun déclencheur : ce workflow ne part qu&apos;à la main.</p>}
      <ul aria-labelledby={`${ids}-list`} className="grid grid-cols-[minmax(0,1fr)] gap-2">
        {triggers?.map((trigger) => (
          <TriggerCard
            key={trigger.id}
            trigger={trigger}
            catalog={catalog}
            onChanged={(next) => setTriggers((items) => items?.map((t) => (t.id === next.id ? next : t)) ?? null)}
            onRemoved={() => setTriggers((items) => items?.filter((t) => t.id !== trigger.id) ?? null)}
            onEdit={() => setEditing(draftFromTrigger(trigger))}
            onRun={onRun}
          />
        ))}
      </ul>
    </div>
  );
}

// ─── Carte d'un déclencheur ──────────────────────────────────────

function TriggerCard({
  trigger,
  catalog,
  onChanged,
  onRemoved,
  onEdit,
  onRun,
}: {
  trigger: Trigger;
  catalog: EventsCatalog | null;
  onChanged: (trigger: Trigger) => void;
  onRemoved: () => void;
  onEdit: () => void;
  onRun: (run: WorkflowRun) => void;
}) {
  const ids = useId();
  const [busy, setBusy] = useState<"toggle" | "delete" | "run" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [testing, setTesting] = useState(false);
  const bumpInbox = useWorkflowStudioStore((s) => s.bumpInbox);
  const { state } = trigger;
  const parts = triggerSummaryParts(trigger, catalog);
  const app = trigger.kind === "event" ? catalogApp(catalog, trigger.app) : null;
  const lastStatus = state.last_run_status && state.last_run_status in RUN_STATUS ? RUN_STATUS[state.last_run_status as RunStatus] : null;

  const toggle = async (enabled: boolean) => {
    setBusy("toggle");
    setError(null);
    try {
      onChanged(await api.updateTrigger(trigger.id, bodyFromTrigger(trigger, { enabled })));
    } catch (err) {
      setError(errorText(err, "Modification impossible."));
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy("delete");
    setError(null);
    try {
      await api.deleteTrigger(trigger.id);
      onRemoved();
    } catch (err) {
      setError(errorText(err, "Suppression impossible."));
      setBusy(null);
    }
  };

  const openLastRun = async () => {
    if (!state.last_run_id) return;
    setBusy("run");
    setError(null);
    try {
      onRun(await api.workflowRun(state.last_run_id));
    } catch (err) {
      setError(errorText(err, "Exécution introuvable."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <li
      {...(app ? appTheme(app.app, app.color) : {})}
      className={cn(
        "grid grid-cols-[minmax(0,1fr)] gap-2 rounded-lg border bg-card p-3",
        trigger.enabled ? "border-atelier-border shadow-glow" : "border-atelier-line opacity-80",
      )}
    >
      <header className="flex items-start gap-2">
        {trigger.kind === "event" ? (
          <AppTile app={trigger.app} color={app?.color} size="xs" />
        ) : (
          <span aria-hidden className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-accent-soft text-accent-ink">
            <CalendarClock className="size-3.5" />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p id={`${ids}-title`} className="text-sm leading-snug font-medium">
            {trigger.label || (trigger.kind === "event" ? "Événement" : "Horaire")}
          </p>
          <p className="text-xs leading-snug text-muted-foreground">
            {parts.map((p, i) => (p.em ? <em key={i} className="text-foreground">{p.text}</em> : <span key={i}>{p.text}</span>))}
          </p>
        </div>
        <Switch
          checked={trigger.enabled}
          disabled={busy !== null}
          aria-labelledby={`${ids}-title`}
          aria-describedby={`${ids}-state`}
          title={trigger.enabled ? "Actif : cliquez pour le couper" : "Coupé : cliquez pour l'activer"}
          onCheckedChange={(on) => void toggle(on)}
        />
      </header>
      <span id={`${ids}-state`} className="sr-only">
        {trigger.enabled ? "actif" : "coupé"}
      </span>

      {state.last_error && (
        <p role="alert" className="flex items-start gap-1.5 rounded-md border border-destructive/40 bg-destructive/8 px-2 py-1.5 text-xs text-destructive">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span className="min-w-0">{state.last_error}</span>
        </p>
      )}
      {state.warning && (
        <p className="flex items-start gap-1.5 rounded-md border border-warning/40 bg-warning/8 px-2 py-1.5 text-xs">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
          <span className="min-w-0">{state.warning}</span>
        </p>
      )}

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-xs">
        {trigger.kind === "schedule" && (
          <>
            <dt className="text-muted-foreground">Prochaine</dt>
            <dd>
              {!trigger.enabled ? (
                "aucune (coupé)"
              ) : state.next_fire_at ? (
                <time dateTime={state.next_fire_at} title={new Date(state.next_fire_at).toLocaleString("fr-FR")}>
                  {occurrenceText(state.next_fire_at)} <span className="text-muted-foreground">({timeUntil(state.next_fire_at)})</span>
                </time>
              ) : (
                "pas encore calculée"
              )}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">Dernière</dt>
        <dd className="flex min-w-0 flex-wrap items-center gap-1">
          {state.last_fired_at ? (
            <>
              <time dateTime={state.last_fired_at}>{timeAgo(state.last_fired_at)}</time>
              {lastStatus && <Badge variant={lastStatus.variant}>{lastStatus.label}</Badge>}
              {state.last_run_id && (
                <Button type="button" variant="link" size="sm" className="h-auto px-0 text-xs" disabled={busy !== null} onClick={() => void openLastRun()}>
                  voir le suivi
                </Button>
              )}
            </>
          ) : (
            "jamais lancé"
          )}
        </dd>
        <dt className="text-muted-foreground">Bilan</dt>
        <dd>{countersText(state.counters).join(" · ")}</dd>
        <dt className="text-muted-foreground">Limites</dt>
        <dd>{limitsText(trigger)}</dd>
      </dl>

      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}

      {testing ? (
        <TestRunner
          trigger={trigger}
          catalog={catalog}
          onCancel={() => setTesting(false)}
          onRun={(run) => {
            setTesting(false);
            bumpInbox();
            onRun(run);
          }}
        />
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-1">
          {confirming ? (
            <>
              <span className="mr-auto text-xs">Supprimer ce déclencheur ?</span>
              <Button type="button" size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Annuler
              </Button>
              <Button type="button" size="sm" variant="destructive" disabled={busy !== null} onClick={() => void remove()}>
                {busy === "delete" ? "Suppression…" : "Supprimer"}
              </Button>
            </>
          ) : (
            <>
              <Button type="button" size="icon-sm" variant="ghost" className="mr-auto size-7" aria-label="Supprimer le déclencheur" onClick={() => setConfirming(true)}>
                <Trash2 />
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={onEdit}>
                <Pencil />
                Modifier
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setTesting(true)}>
                <FlaskConical />
                Tester maintenant
              </Button>
            </>
          )}
        </div>
      )}
    </li>
  );
}

/** « Tester maintenant » : un lancement immédiat ; pour un événement, avec un exemple modifiable. */
function TestRunner({
  trigger,
  catalog,
  onCancel,
  onRun,
}: {
  trigger: Trigger;
  catalog: EventsCatalog | null;
  onCancel: () => void;
  onRun: (run: WorkflowRun) => void;
}) {
  const id = useId();
  const example = useMemo(() => {
    if (trigger.kind !== "event") return "";
    const filters: FilterDraft[] = draftFromTrigger(trigger).filters;
    return JSON.stringify(sampleEvent(catalogApp(catalog, trigger.app), trigger.types, filters), null, 2);
  }, [trigger, catalog]);
  const [text, setText] = useState(example);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const launch = async () => {
    setProblem(null);
    let event;
    if (trigger.kind === "event") {
      const parsed = parseSampleEvent(text);
      if (!parsed.ok) return setProblem(parsed.error);
      event = parsed.event;
    }
    setBusy(true);
    try {
      onRun(await api.testTrigger(trigger.id, event));
    } catch (err) {
      setProblem(errorText(err, "Test impossible."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Tester le déclencheur" className="grid grid-cols-[minmax(0,1fr)] gap-2 rounded-md border border-atelier-line bg-sunken p-2">
      <p className="text-xs">
        Lance le workflow une fois, tout de suite, comme le ferait ce déclencheur
        {trigger.kind === "event" ? " avec l'événement ci-dessous (modifiable)." : ", avec ses paramètres."}
      </p>
      {trigger.kind === "event" && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <div className="flex items-center">
            <label htmlFor={id} className="flex-1 text-[11px] font-medium">
              Événement d&apos;exemple (JSON)
            </label>
            <Button type="button" variant="ghost" size="sm" className="h-6 px-1.5 text-xs" onClick={() => setText(example)}>
              Rétablir
            </Button>
          </div>
          <Textarea
            id={id}
            rows={8}
            spellCheck={false}
            className="font-mono text-[11px]"
            value={text}
            aria-invalid={!!problem}
            aria-describedby={problem ? `${id}-err` : undefined}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
      )}
      <ApprovalReminder />
      <FieldError id={`${id}-err`} message={problem ?? undefined} />
      <div className="flex justify-end gap-1">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Annuler
        </Button>
        <Button type="button" size="sm" disabled={busy} onClick={() => void launch()}>
          <FlaskConical />
          {busy ? "Lancement…" : "Lancer le test"}
        </Button>
      </div>
    </section>
  );
}

// ─── Formulaire ──────────────────────────────────────────────────

function TriggerForm({
  initial,
  params,
  catalog,
  catalogError,
  saving,
  onCancel,
  onSubmit,
}: {
  initial: TriggerDraft;
  params: WorkflowParam[];
  catalog: EventsCatalog | null;
  catalogError: string | null;
  saving: boolean;
  onCancel: () => void;
  /** Renvoie le message d'erreur du serveur, null si enregistré */
  onSubmit: (draft: TriggerDraft) => Promise<string | null>;
}) {
  const ids = useId();
  const [draft, setDraft] = useState(initial);
  const [touched, setTouched] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const firstField = useRef<HTMLInputElement>(null);
  const app = draft.app ? catalogApp(catalog, draft.app) : null;
  const errors: TriggerErrors = validateTrigger(draft, params, app);
  const shown = touched ? errors : {};
  const set = (patch: Partial<TriggerDraft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setServerError(null);
  };
  const err = (key: string) => (shown[key] ? `${ids}-${key}-err` : undefined);

  useEffect(() => firstField.current?.focus(), []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (hasErrors(errors)) return;
    setServerError(await onSubmit(draft));
  };

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="grid grid-cols-[minmax(0,1fr)] gap-4" aria-labelledby={`${ids}-title`}>
      <div className="flex items-center gap-2">
        {draft.kind === "event" ? <Zap className="size-4 text-accent-ink" aria-hidden /> : <CalendarClock className="size-4 text-accent-ink" aria-hidden />}
        <h3 id={`${ids}-title`} className="flex-1 text-sm font-semibold">
          {draft.id ? "Modifier le déclencheur" : draft.kind === "event" ? "Nouveau déclencheur sur événement" : "Nouveau déclencheur horaire"}
        </h3>
        <Button type="button" variant="ghost" size="icon-sm" className="size-7" aria-label="Fermer sans enregistrer" onClick={onCancel}>
          <X />
        </Button>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
        <label htmlFor={`${ids}-label`} className="text-xs font-medium">
          Libellé <span className="font-normal text-muted-foreground">(facultatif)</span>
        </label>
        <Input
          ref={firstField}
          id={`${ids}-label`}
          className="h-8"
          maxLength={120}
          value={draft.label}
          placeholder={draft.kind === "event" ? "ex. Doc à écrire quand une tâche se ferme" : "ex. Bilan du matin"}
          aria-invalid={!!shown.label}
          aria-describedby={err("label")}
          onChange={(e) => set({ label: e.target.value })}
        />
        <FieldError id={`${ids}-label-err`} message={shown.label} />
      </div>

      {draft.kind === "schedule" ? (
        <ScheduleFields draft={draft} errors={shown} ids={ids} set={set} />
      ) : (
        <EventFields draft={draft} errors={shown} ids={ids} set={set} catalog={catalog} catalogError={catalogError} />
      )}

      <ParamsFields draft={draft} params={params} errors={shown} ids={ids} app={app} set={set} />

      <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-limits`}>
        <SectionTitle id={`${ids}-limits`}>Garde-fous</SectionTitle>
        <div className={cn("grid gap-2", draft.kind === "event" ? "grid-cols-2" : "grid-cols-1")}>
          <NumberField
            id={`${ids}-max`}
            label="Lancements par heure, au plus"
            value={draft.maxRunsPerHour}
            min={LIMITS.maxRunsPerHour.min}
            max={LIMITS.maxRunsPerHour.max}
            error={shown.max_runs_per_hour}
            onChange={(v) => set({ maxRunsPerHour: v })}
          />
          {draft.kind === "event" && (
            <NumberField
              id={`${ids}-debounce`}
              label="Regrouper les rafales (s)"
              value={draft.debounceSeconds}
              min={LIMITS.debounceSeconds.min}
              max={LIMITS.debounceSeconds.max}
              error={shown.debounce_seconds}
              onChange={(v) => set({ debounceSeconds: v })}
            />
          )}
        </div>
        <p className="text-[11px] text-muted-foreground">
          Au-delà du plafond, les déclenchements sont ignorés (et comptés). Une seule exécution attend votre validation à la fois.
          {draft.kind === "event" && " Une rafale d'événements regroupée ne lance qu'une exécution, avec le dernier événement."}
        </p>
      </section>

      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={draft.enabled} onCheckedChange={(c) => set({ enabled: c === true })} />
        Actif dès l&apos;enregistrement
      </label>

      <ApprovalReminder />

      {serverError && (
        <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/8 px-2 py-1.5 text-sm text-destructive">
          {serverError}
        </p>
      )}
      {touched && hasErrors(errors) && (
        <p role="alert" className="text-xs text-destructive">
          {Object.keys(errors).length === 1 ? "Un champ est à corriger." : `${Object.keys(errors).length} champs sont à corriger.`}
        </p>
      )}
      <div className="flex justify-end gap-1.5">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Annuler
        </Button>
        <Button type="submit" size="sm" disabled={saving}>
          <Save />
          {saving ? "Enregistrement…" : draft.id ? "Enregistrer" : "Créer le déclencheur"}
        </Button>
      </div>
    </form>
  );
}

type FieldsProps = {
  draft: TriggerDraft;
  errors: TriggerErrors;
  ids: string;
  set: (patch: Partial<TriggerDraft>) => void;
};

function NumberField({
  id,
  label,
  value,
  min,
  max,
  error,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  min: number;
  max: number;
  error: string | undefined;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] content-start gap-1">
      <label htmlFor={id} className="text-xs font-medium">
        {label}
      </label>
      <Input
        id={id}
        className="h-8"
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        step={1}
        value={value}
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-err` : `${id}-hint`}
        onChange={(e) => onChange(e.target.value)}
      />
      {error ? (
        <FieldError id={`${id}-err`} message={error} />
      ) : (
        <p id={`${id}-hint`} className="text-[11px] text-muted-foreground">
          {min} à {max}
        </p>
      )}
    </div>
  );
}

function ScheduleFields({ draft, errors, ids, set }: FieldsProps) {
  const toggleDay = (day: (typeof WEEKDAYS)[number]) =>
    set({ days: draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day] });
  return (
    <section className="grid grid-cols-[minmax(0,1fr)] gap-2.5" aria-labelledby={`${ids}-when`}>
      <SectionTitle id={`${ids}-when`}>Quand</SectionTitle>
      <div className="grid grid-cols-2 gap-1" role="radiogroup" aria-label="Rythme">
        {(
          [
            ["daily", "À heure fixe"],
            ["interval", "À intervalle"],
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            type="button"
            size="sm"
            role="radio"
            aria-checked={draft.scheduleKind === value}
            variant={draft.scheduleKind === value ? "default" : "outline"}
            onClick={() => set({ scheduleKind: value })}
          >
            {label}
          </Button>
        ))}
      </div>
      {draft.scheduleKind === "interval" ? (
        <NumberField
          id={`${ids}-every`}
          label="Toutes les … minutes"
          value={draft.everyMinutes}
          min={LIMITS.everyMinutes.min}
          max={LIMITS.everyMinutes.max}
          error={errors.every_minutes}
          onChange={(v) => set({ everyMinutes: v })}
        />
      ) : (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
            <label htmlFor={`${ids}-at`} className="text-xs font-medium">
              Heure (24 h)
            </label>
            {/* Champ texte plutôt que type="time" : celui-ci suit la langue du navigateur (AM / PM) */}
            <Input
              id={`${ids}-at`}
              className="h-8 w-24 font-mono tabular-nums"
              inputMode="numeric"
              autoComplete="off"
              maxLength={5}
              placeholder="08:00"
              value={draft.at}
              aria-invalid={!!errors.at}
              aria-describedby={errors.at ? `${ids}-at-err` : `${ids}-at-hint`}
              onChange={(e) => set({ at: e.target.value })}
            />
            {errors.at ? (
              <FieldError id={`${ids}-at-err`} message={errors.at} />
            ) : (
              <p id={`${ids}-at-hint`} className="text-[11px] text-muted-foreground">
                HH:MM, de 00:00 à 23:59, dans le fuseau des réglages de Nexus (Europe/Paris par défaut).
              </p>
            )}
          </div>
          <fieldset className="grid grid-cols-[minmax(0,1fr)] gap-1" aria-describedby={errors.days ? `${ids}-days-err` : undefined}>
            <legend className="mb-1 flex w-full items-center text-xs font-medium">
              <span className="flex-1">Jours</span>
              <Button type="button" variant="link" size="sm" className="h-auto px-1 text-[11px]" onClick={() => set({ days: [...WORKDAYS] })}>
                ouvrés
              </Button>
              <Button type="button" variant="link" size="sm" className="h-auto px-1 text-[11px]" onClick={() => set({ days: [...WEEKDAYS] })}>
                tous
              </Button>
            </legend>
            <div className="flex gap-1">
              {WEEKDAYS.map((day) => {
                const on = draft.days.includes(day);
                return (
                  <Button
                    key={day}
                    type="button"
                    size="icon-sm"
                    variant={on ? "default" : "outline"}
                    aria-pressed={on}
                    aria-label={WEEKDAY_LABEL[day]}
                    title={WEEKDAY_LABEL[day]}
                    className="size-8 flex-1"
                    onClick={() => toggleDay(day)}
                  >
                    {WEEKDAY_SHORT[day]}
                  </Button>
                );
              })}
            </div>
            <FieldError id={`${ids}-days-err`} message={errors.days} />
          </fieldset>
        </>
      )}
    </section>
  );
}

function EventFields({
  draft,
  errors,
  ids,
  set,
  catalog,
  catalogError,
}: FieldsProps & { catalog: EventsCatalog | null; catalogError: string | null }) {
  const app = draft.app ? catalogApp(catalog, draft.app) : null;
  const fields = filterFields(app, draft.types);
  const setFilter = (index: number, patch: Partial<FilterDraft>) =>
    set({ filters: draft.filters.map((f, i) => (i === index ? { ...f, ...patch } : f)) });
  const apps: EventsCatalogApp[] = catalog?.apps ?? [];
  // App enregistrée que le catalogue ne connaît plus : gardée visible
  const unknownApp = draft.app && !apps.some((a) => a.app === draft.app) ? draft.app : null;

  return (
    <>
      <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-app`}>
        <SectionTitle id={`${ids}-app`}>Application</SectionTitle>
        {catalogError && (
          <p role="alert" className="text-xs text-destructive">
            {catalogError}
          </p>
        )}
        {!catalog && !catalogError && (
          <p role="status" className="text-xs text-muted-foreground">
            Lecture des événements publiés par les applications…
          </p>
        )}
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1" role="radiogroup" aria-labelledby={`${ids}-app`} aria-describedby={errors.app ? `${ids}-app-err` : undefined}>
          {apps.map((a) => (
            <AppChoice
              key={a.app}
              app={a}
              checked={draft.app === a.app}
              onChoose={() => set({ app: a.app, types: draft.app === a.app ? draft.types : [], filters: draft.app === a.app ? draft.filters : [] })}
            />
          ))}
          {unknownApp && <p className="text-xs text-warning">Application « {unknownApp} » absente du catalogue.</p>}
        </div>
        <FieldError id={`${ids}-app-err`} message={errors.app} />
      </section>

      {draft.app && (
        <fieldset className="grid grid-cols-[minmax(0,1fr)] gap-1" aria-describedby={errors.types ? `${ids}-types-err` : undefined}>
          <legend className="mb-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Événements</legend>
          {app && app.events.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {app.status === "ok" ? "Cette application ne publie aucun événement." : "Application injoignable : ses événements ne sont pas connus pour le moment."}
            </p>
          )}
          {[...(app?.events ?? []), ...draft.types.filter((t) => !app?.events.some((e) => e.type === t)).map((t) => ({ type: t, label: t, fields: [] }))].map(
            (ev) => {
              const checked = draft.types.includes(ev.type);
              return (
                <label key={ev.type} className="flex items-start gap-2 rounded-md px-1 py-1 hover:bg-accent">
                  <Checkbox
                    className="mt-0.5"
                    checked={checked}
                    onCheckedChange={(c) => set({ types: c === true ? [...draft.types, ev.type] : draft.types.filter((t) => t !== ev.type) })}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm leading-tight">{ev.label}</span>
                    <span className="block truncate font-mono text-[10px] text-muted-foreground">{ev.type}</span>
                  </span>
                </label>
              );
            },
          )}
          <FieldError id={`${ids}-types-err`} message={errors.types} />
        </fieldset>
      )}

      {draft.app && (
        <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-filters`}>
          <div className="flex items-center">
            <SectionTitle id={`${ids}-filters`}>Seulement si…</SectionTitle>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto h-7"
              disabled={draft.filters.length >= LIMITS.filters.max}
              onClick={() => set({ filters: [...draft.filters, { path: fields[0] ?? "data.", op: "eq", value: "" }] })}
            >
              <Plus />
              Filtre
            </Button>
          </div>
          {draft.filters.length === 0 && <p className="text-[11px] text-muted-foreground">Aucun filtre : chaque événement coché lance le workflow.</p>}
          <datalist id={`${ids}-fields`}>
            {fields.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-2">
            {draft.filters.map((filter, i) => {
              const key = `filters.${i}`;
              return (
                <li key={i} className="grid grid-cols-[minmax(0,1fr)] gap-1 rounded-md border border-atelier-line bg-sunken p-2">
                  <div className="flex items-center gap-1">
                    <Input
                      aria-label={`Champ du filtre ${i + 1}`}
                      list={`${ids}-fields`}
                      className="h-7 flex-1 font-mono text-xs"
                      placeholder="data.to"
                      value={filter.path}
                      aria-invalid={!!errors[key]}
                      aria-describedby={errors[key] ? `${ids}-${key}-err` : undefined}
                      onChange={(e) => setFilter(i, { path: e.target.value })}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      className="size-7"
                      aria-label={`Retirer le filtre ${i + 1}`}
                      onClick={() => set({ filters: draft.filters.filter((_, j) => j !== i) })}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                  <div className="flex items-center gap-1">
                    <NativeSelect
                      aria-label={`Comparaison du filtre ${i + 1}`}
                      className="w-40 shrink-0"
                      value={filter.op}
                      onChange={(e) => setFilter(i, { op: e.target.value as FilterDraft["op"] })}
                    >
                      {FILTER_OPS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </NativeSelect>
                    {filter.op !== "exists" && (
                      <Input
                        aria-label={`Valeur du filtre ${i + 1}`}
                        className="h-8 min-w-0 flex-1"
                        placeholder={filter.op === "in" ? "CLOSED, RESOLVED" : "CLOSED"}
                        value={filter.value}
                        aria-invalid={!!errors[key]}
                        onChange={(e) => setFilter(i, { value: e.target.value })}
                      />
                    )}
                  </div>
                  <FieldError id={`${ids}-${key}-err`} message={errors[key]} />
                </li>
              );
            })}
          </ul>
          <FieldError id={`${ids}-filters-err`} message={errors.filters} />
        </section>
      )}
    </>
  );
}

function AppChoice({ app, checked, onChoose }: { app: EventsCatalogApp; checked: boolean; onChoose: () => void }) {
  const count = app.events.length;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      {...appTheme(app.app, app.color)}
      onClick={onChoose}
      className={cn(
        "flex items-center gap-2 rounded-md border px-2 py-1.5 text-left outline-none transition-colors hover:bg-signature-faint focus-visible:shadow-focus",
        checked ? "border-signature bg-signature-soft shadow-glow" : "border-atelier-line bg-card",
      )}
    >
      <AppTile app={app.app} color={app.color} size="xs" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{app.name}</span>
        <span className="flex items-center gap-2">
          <AppStatusDot status={app.status} />
          <span className="text-[11px] text-muted-foreground">
            {count === 0 ? "aucun événement" : `${count} événement${count >= 2 ? "s" : ""}`}
          </span>
        </span>
      </span>
    </button>
  );
}

function ParamsFields({ draft, params, errors, ids, app, set }: FieldsProps & { params: WorkflowParam[]; app: EventsCatalogApp | null }) {
  const groups = useMemo(() => eventTemplateOptions(app, draft.types), [app, draft.types]);
  // Valeurs d'un paramètre qui n'existe plus : signalées, on peut les retirer
  const orphans = Object.keys(draft.params).filter((name) => draft.params[name] && !params.some((p) => p.name === name));
  const setParam = (name: string, value: string) => set({ params: { ...draft.params, [name]: value } });
  return (
    <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-params`}>
      <SectionTitle id={`${ids}-params`}>Paramètres du workflow</SectionTitle>
      {params.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">Ce workflow n&apos;a pas de paramètre.</p>
      ) : (
        <p className="text-[11px] text-muted-foreground">
          Laissez vide pour garder la valeur par défaut.
          {draft.kind === "event" && " « Utiliser… » insère une valeur de l'événement, lue à chaque lancement."}
        </p>
      )}
      {params.map((param) => {
        const id = `${ids}-param-${param.name}`;
        const key = `params.${param.name}`;
        return (
          <div key={param.name} className="grid grid-cols-[minmax(0,1fr)] gap-1">
            <div className="flex items-center gap-1">
              <label htmlFor={id} className="min-w-0 flex-1 truncate text-xs font-medium">
                {param.label || param.name} <code className="font-mono text-[10px] font-normal text-muted-foreground">{param.name}</code>
              </label>
              {draft.kind === "event" && (
                <EventTemplateMenu
                  groups={groups}
                  label={param.label || param.name}
                  onPick={(tpl) => setParam(param.name, insertEventTemplate(draft.params[param.name] ?? "", tpl))}
                />
              )}
            </div>
            <Input
              id={id}
              className="h-8 font-mono text-xs"
              maxLength={500}
              value={draft.params[param.name] ?? ""}
              placeholder={param.default ? `défaut : ${param.default}` : "(vide)"}
              aria-invalid={!!errors[key]}
              aria-describedby={errors[key] ? `${id}-err` : undefined}
              onChange={(e) => setParam(param.name, e.target.value)}
            />
            <FieldError id={`${id}-err`} message={errors[key]} />
          </div>
        );
      })}
      {orphans.map((name) => (
        <div key={name} className="flex items-center gap-2 rounded-md border border-warning/40 bg-warning/8 px-2 py-1 text-xs">
          <span className="min-w-0 flex-1">
            <code className="font-mono">{name}</code> n&apos;existe plus dans le workflow.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-6"
            onClick={() => set({ params: Object.fromEntries(Object.entries(draft.params).filter(([k]) => k !== name)) })}
          >
            Retirer
          </Button>
        </div>
      ))}
    </section>
  );
}

function EventTemplateMenu({
  groups,
  label,
  onPick,
}: {
  groups: ReturnType<typeof eventTemplateOptions>;
  label: string;
  onPick: (tpl: string) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="h-6 gap-1 px-1.5 text-xs" aria-label={`Utiliser une valeur de l'événement pour ${label}`}>
          <Braces className="size-3" />
          Utiliser…
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-80 w-72 overflow-y-auto">
        {groups.map((group, i) => (
          <div key={group.label}>
            {i > 0 && <DropdownMenuSeparator />}
            <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
            {group.options.map((option) => (
              <DropdownMenuItem key={option.value} onSelect={() => onPick(option.value)} className="flex-col items-start gap-0">
                <span className="text-sm">{option.label}</span>
                <span className="flex w-full items-center gap-1.5 text-[11px] text-muted-foreground">
                  <code className="truncate font-mono">{option.value}</code>
                  {option.hint && <span className="ml-auto shrink-0">{option.hint}</span>}
                </span>
              </DropdownMenuItem>
            ))}
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
