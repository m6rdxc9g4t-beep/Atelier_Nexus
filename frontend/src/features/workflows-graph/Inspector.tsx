"use client";

import { Plus, Trash2, Unlink } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type {
  AgentInfo,
  CatalogEntry,
  Condition,
  ConditionOp,
  ValidationError,
  WorkflowParam,
  WorkflowStepV2,
} from "@/types/api";

import { APP_STATUS_LABEL, appKey, parseUses, usesLabel } from "./catalog";
import type { WorkflowDraftV2 } from "./draft";
import { FieldEditor, TemplateMenu } from "./FieldEditor";
import { MAX_PARAMS, STEP_ID, wouldCreateCycle } from "./graph";
import { extraKeys, fieldsFromSchema, parseFieldInput, setInputValue } from "./schemaForm";
import { AppTile, KindBadge } from "./StepBadges";
import { type TemplateGroup, insertTemplate, templateOptions } from "./templates";
import { errorsByField, globalErrors } from "./validate";

const OPS: { value: ConditionOp; label: string }[] = [
  { value: "eq", label: "est égal à" },
  { value: "ne", label: "est différent de" },
  { value: "gt", label: "est supérieur à" },
  { value: "gte", label: "est supérieur ou égal à" },
  { value: "lt", label: "est inférieur à" },
  { value: "lte", label: "est inférieur ou égal à" },
  { value: "contains", label: "contient" },
  { value: "empty", label: "est vide" },
  { value: "not_empty", label: "n'est pas vide" },
];

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{children}</h3>;
}

function Errors({ errors }: { errors: ValidationError[] | undefined }) {
  if (!errors?.length) return null;
  return (
    <ul role="alert" className="grid grid-cols-[minmax(0,1fr)] gap-0.5 text-[11px] text-destructive">
      {errors.map((e, i) => (
        <li key={`${e.code}-${i}`}>{e.message}</li>
      ))}
    </ul>
  );
}

// ─── Étape sélectionnée ──────────────────────────────────────────

export function StepInspector({
  step,
  draft,
  catalog,
  apps,
  errors,
  onChange,
  onRename,
  onRemove,
  onDisconnect,
  onConnect,
}: {
  step: WorkflowStepV2;
  draft: WorkflowDraftV2;
  catalog: Map<string, CatalogEntry>;
  apps: Map<string, { name: string; color: string; status?: keyof typeof APP_STATUS_LABEL }>;
  errors: ValidationError[];
  onChange: (patch: Partial<WorkflowStepV2>) => void;
  /** Renvoie un message si l'identifiant est refusé */
  onRename: (to: string) => string | null;
  onRemove: () => void;
  onDisconnect: (source: string) => void;
  onConnect: (source: string) => void;
}) {
  const ids = useId();
  const entry = catalog.get(step.uses) ?? null;
  const app = appKey(entry ? entry.app : parseUses(step.uses).app);
  const meta = apps.get(app);
  const fields = useMemo(() => fieldsFromSchema(entry?.input_schema), [entry]);
  const extras = extraKeys(step.input, fields);
  const templates = useMemo(() => templateOptions(draft.steps, draft.params, step.id, catalog), [draft.steps, draft.params, step.id, catalog]);
  const byField = errorsByField(errors, step.id);
  const [idText, setIdText] = useState(step.id);
  const [idProblem, setIdProblem] = useState<string | null>(null);

  const commitId = () => {
    if (idText === step.id) return setIdProblem(null);
    const problem = onRename(idText);
    setIdProblem(problem);
    if (problem) return;
  };

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <div className="flex items-start gap-2.5">
        <AppTile app={app} color={meta?.color} />
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-tight font-semibold">{usesLabel(step.uses, entry)}</p>
          <p className="truncate text-xs text-muted-foreground">
            {meta?.name ?? (app === "nexus" ? "Outil Nexus" : app)} · <code className="font-mono">{step.uses}</code>
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            {entry && <KindBadge kind={entry.kind} />}
            {entry && <span className="text-[11px] text-muted-foreground">sortie : {entry.output_format}</span>}
          </div>
        </div>
        <Button type="button" variant="ghost" size="icon-sm" aria-label={`Supprimer l'étape ${step.id}`} onClick={onRemove}>
          <Trash2 />
        </Button>
      </div>
      {entry?.description && <p className="text-xs text-muted-foreground">{entry.description}</p>}
      {!entry && <p className="text-xs text-warning">Cette étape n&apos;est pas dans le catalogue : son entrée est éditée en JSON.</p>}
      {entry && !entry.available && <p className="text-xs text-warning">{entry.unavailable_reason ?? "Indisponible pour le moment."}</p>}
      <Errors errors={byField.get(null)} />

      <section className="grid grid-cols-[minmax(0,1fr)] gap-2.5" aria-labelledby={`${ids}-general`}>
        <h3 id={`${ids}-general`} className="sr-only">
          Réglages de l&apos;étape
        </h3>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <label htmlFor={`${ids}-id`} className="text-xs font-medium">
            Identifiant
          </label>
          <Input
            id={`${ids}-id`}
            className="h-8 font-mono text-xs"
            value={idText}
            maxLength={40}
            aria-invalid={!!idProblem || !!byField.get("id")}
            aria-describedby={`${ids}-id-help`}
            onChange={(e) => setIdText(e.target.value)}
            onBlur={commitId}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitId();
            }}
          />
          <p id={`${ids}-id-help`} className="text-[11px] text-muted-foreground">
            Cité dans les gabarits : <code className="font-mono">{`{{steps.${step.id}.data}}`}</code>
          </p>
          {idProblem && (
            <p role="alert" className="text-[11px] text-destructive">
              {idProblem}
            </p>
          )}
          <Errors errors={byField.get("id")} />
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <label htmlFor={`${ids}-label`} className="text-xs font-medium">
            Libellé <span className="font-normal text-muted-foreground">(facultatif)</span>
          </label>
          <Input
            id={`${ids}-label`}
            className="h-8"
            value={step.label}
            maxLength={120}
            placeholder={entry?.label}
            onChange={(e) => onChange({ label: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <label htmlFor={`${ids}-onerror`} className="text-xs font-medium">
            En cas d&apos;erreur
          </label>
          <NativeSelect
            id={`${ids}-onerror`}
            className="w-full"
            value={step.on_error}
            onChange={(e) => onChange({ on_error: e.target.value as WorkflowStepV2["on_error"] })}
          >
            <option value="stop">Arrêter le workflow</option>
            <option value="continue">Continuer avec la suite</option>
          </NativeSelect>
        </div>
        <NeedsList
          step={step}
          candidates={draft.steps.filter((s) => !step.needs.includes(s.id) && !wouldCreateCycle(draft.steps, s.id, step.id))}
          errors={byField.get("needs")}
          onDisconnect={onDisconnect}
          onConnect={onConnect}
        />
      </section>

      <ConditionEditor when={step.when ?? null} templates={templates} errors={byField.get("when")} onChange={(when) => onChange({ when })} />

      <section className="grid grid-cols-[minmax(0,1fr)] gap-3" aria-labelledby={`${ids}-input`}>
        <SectionTitle>
          <span id={`${ids}-input`}>Entrée</span>
        </SectionTitle>
        {fields.length === 0 && entry && extras.length === 0 && (
          <p className="text-xs text-muted-foreground">Cette étape ne prend aucun paramètre.</p>
        )}
        {fields.map((field) => (
          <FieldEditor
            key={`${step.id}-${field.name}`}
            field={field}
            value={step.input[field.name]}
            errors={byField.get(field.name) ?? []}
            templates={templates}
            onChange={(value) => onChange({ input: setInputValue(step.input, field.name, value) })}
            onInsert={(tpl) =>
              onChange({ input: setInputValue(step.input, field.name, insertTemplate(step.input[field.name], tpl, field.kind)) })
            }
          />
        ))}
        {(extras.length > 0 || !entry) && (
          <RawInput
            key={step.id}
            input={entry ? Object.fromEntries(extras.map((k) => [k, step.input[k]])) : step.input}
            label={entry ? "Autres champs (JSON)" : "Entrée (JSON)"}
            errors={extras.flatMap((k) => byField.get(k) ?? [])}
            templates={templates}
            onChange={(obj) => {
              const kept = entry ? Object.fromEntries(Object.entries(step.input).filter(([k]) => !extras.includes(k))) : {};
              onChange({ input: { ...kept, ...obj } });
            }}
          />
        )}
      </section>
    </div>
  );
}

function NeedsList({
  step,
  candidates,
  errors,
  onDisconnect,
  onConnect,
}: {
  step: WorkflowStepV2;
  /** Étapes qu'on peut ajouter en amont sans boucle */
  candidates: WorkflowStepV2[];
  errors: ValidationError[] | undefined;
  onDisconnect: (source: string) => void;
  onConnect: (source: string) => void;
}) {
  const id = useId();
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
      <p className="text-xs font-medium">Attend</p>
      {step.needs.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          Rien : l&apos;étape démarre tout de suite. Reliez la sortie d&apos;une étape à son entrée pour la faire attendre.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1">
          {step.needs.map((need) => (
            <li key={need} className="inline-flex items-center gap-1 rounded-sm border border-atelier-line bg-sunken py-0.5 pr-0.5 pl-1.5">
              <code className="font-mono text-[11px]">{need}</code>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="size-5"
                aria-label={`Ne plus attendre ${need}`}
                onClick={() => onDisconnect(need)}
              >
                <Unlink className="size-3" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {candidates.length > 0 && (
        <>
          <label htmlFor={id} className="sr-only">
            Ajouter une étape amont
          </label>
          <NativeSelect
            id={id}
            className="w-full"
            value=""
            onChange={(e) => {
              if (e.target.value) onConnect(e.target.value);
            }}
          >
            <option value="">Attendre aussi…</option>
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label ? `${c.label} (${c.id})` : c.id}
              </option>
            ))}
          </NativeSelect>
        </>
      )}
      <Errors errors={errors} />
    </div>
  );
}

function ConditionEditor({
  when,
  templates,
  errors,
  onChange,
}: {
  when: Condition | null;
  templates: TemplateGroup[];
  errors: ValidationError[] | undefined;
  onChange: (when: Condition | null) => void;
}) {
  const ids = useId();
  const unary = when?.op === "empty" || when?.op === "not_empty";
  const rightText = when?.right === undefined || when.right === null ? "" : typeof when.right === "string" ? when.right : JSON.stringify(when.right);
  const setRight = (text: string) => {
    if (!when) return;
    // Nombre ou booléen saisi : gardé typé ; sinon texte (ou gabarit)
    let right: unknown = text;
    if (text.trim() !== "" && !Number.isNaN(Number(text))) right = Number(text);
    else if (text === "true" || text === "false") right = text === "true";
    onChange({ ...when, right });
  };
  return (
    <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-title`}>
      <div className="flex items-center gap-2">
        <SectionTitle>
          <span id={`${ids}-title`}>Condition</span>
        </SectionTitle>
        <label className="ml-auto flex items-center gap-1.5 text-xs">
          <Checkbox
            checked={!!when}
            onCheckedChange={(checked) => onChange(checked === true ? { left: "", op: "not_empty" } : null)}
          />
          Exécuter seulement si…
        </label>
      </div>
      {when && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5 rounded-md border border-atelier-line bg-sunken p-2">
          <div className="flex items-center gap-1">
            <label htmlFor={`${ids}-left`} className="flex-1 text-[11px] text-muted-foreground">
              Valeur testée
            </label>
            <TemplateMenu groups={templates} label="la valeur testée" onPick={(tpl) => onChange({ ...when, left: tpl })} />
          </div>
          <Input
            id={`${ids}-left`}
            className="h-8 font-mono text-xs"
            placeholder="{{steps.lire.data.total}}"
            value={when.left}
            onChange={(e) => onChange({ ...when, left: e.target.value })}
          />
          <label htmlFor={`${ids}-op`} className="sr-only">
            Comparaison
          </label>
          <NativeSelect
            id={`${ids}-op`}
            className="w-full"
            value={when.op}
            onChange={(e) => {
              const op = e.target.value as ConditionOp;
              const next: Condition = { left: when.left, op };
              if (op !== "empty" && op !== "not_empty") next.right = when.right ?? "";
              onChange(next);
            }}
          >
            {OPS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
          {!unary && (
            <>
              <label htmlFor={`${ids}-right`} className="sr-only">
                Valeur de comparaison
              </label>
              <Input
                id={`${ids}-right`}
                className="h-8"
                placeholder="Valeur (nombre, texte ou {{…}})"
                value={rightText}
                onChange={(e) => setRight(e.target.value)}
              />
            </>
          )}
          <Errors errors={errors} />
        </div>
      )}
    </section>
  );
}

function RawInput({
  input,
  label,
  errors,
  templates,
  onChange,
}: {
  input: Record<string, unknown>;
  label: string;
  errors: ValidationError[];
  templates: TemplateGroup[];
  onChange: (input: Record<string, unknown>) => void;
}) {
  const id = useId();
  const [text, setText] = useState(() => JSON.stringify(input, null, 2));
  const [problem, setProblem] = useState<string | null>(null);
  const apply = (next: string) => {
    setText(next);
    const parsed = parseFieldInput({ name: "", label: "", description: "", kind: "json", required: false }, next || "{}");
    if (!parsed.ok || !parsed.value || typeof parsed.value !== "object" || Array.isArray(parsed.value)) {
      setProblem("Objet JSON { … } attendu.");
      return;
    }
    setProblem(null);
    onChange(parsed.value as Record<string, unknown>);
  };
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
      <div className="flex items-center gap-1">
        <label htmlFor={id} className="flex-1 text-xs font-medium">
          {label}
        </label>
        <TemplateMenu
          groups={templates}
          label={label}
          onPick={(tpl) => {
            void navigator.clipboard?.writeText(tpl).catch(() => undefined);
            setProblem(`Copié : ${tpl} — collez-le à l'endroit voulu.`);
          }}
        />
      </div>
      <Textarea
        id={id}
        rows={4}
        spellCheck={false}
        className="font-mono text-xs"
        value={text}
        aria-invalid={!!problem || errors.length > 0}
        onChange={(e) => apply(e.target.value)}
      />
      {problem && (
        <p role="status" className="text-[11px] text-muted-foreground">
          {problem}
        </p>
      )}
      <Errors errors={errors} />
    </div>
  );
}

// ─── Workflow (aucune étape sélectionnée) ────────────────────────

export function WorkflowSettings({
  draft,
  agents,
  errors,
  undeclared,
  onChange,
  onDeclareMissing,
}: {
  draft: WorkflowDraftV2;
  agents: AgentInfo[];
  errors: ValidationError[];
  undeclared: string[];
  onChange: (patch: Partial<WorkflowDraftV2>) => void;
  onDeclareMissing: () => void;
}) {
  const ids = useId();
  const global = globalErrors(errors);
  const setParam = (index: number, patch: Partial<WorkflowParam>) =>
    onChange({ params: draft.params.map((p, i) => (i === index ? { ...p, ...patch } : p)) });

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
      <section className="grid grid-cols-[minmax(0,1fr)] gap-2.5">
        <SectionTitle>Workflow</SectionTitle>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <label htmlFor={`${ids}-title`} className="text-xs font-medium">
            Titre
          </label>
          <Input
            id={`${ids}-title`}
            className="h-8"
            value={draft.title}
            maxLength={120}
            aria-required
            placeholder="ex. CA du mois → tâches Projets"
            onChange={(e) => onChange({ title: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <label htmlFor={`${ids}-desc`} className="text-xs font-medium">
            Description <span className="font-normal text-muted-foreground">(facultatif)</span>
          </label>
          <Textarea
            id={`${ids}-desc`}
            rows={2}
            maxLength={500}
            className="text-sm"
            value={draft.description}
            onChange={(e) => onChange({ description: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <label htmlFor={`${ids}-agent`} className="text-xs font-medium">
            Agent
          </label>
          <NativeSelect
            id={`${ids}-agent`}
            className="w-full"
            value={draft.agent ?? ""}
            onChange={(e) => onChange({ agent: e.target.value || null })}
          >
            <option value="">Workflow de suite (toutes les boîtes configurées)</option>
            {agents.map((a) => (
              <option key={a.name} value={a.name}>
                {a.display_name}
              </option>
            ))}
            {draft.agent && !agents.some((a) => a.name === draft.agent) && <option value={draft.agent}>{draft.agent}</option>}
          </NativeSelect>
          <p className="text-[11px] text-muted-foreground">
            Un agent limite le catalogue à ses boîtes à outils ; un workflow de suite peut tout enchaîner.
          </p>
        </div>
      </section>

      <section className="grid grid-cols-[minmax(0,1fr)] gap-2" aria-labelledby={`${ids}-params`}>
        <div className="flex items-center gap-2">
          <SectionTitle>
            <span id={`${ids}-params`}>Paramètres</span>
          </SectionTitle>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto h-7"
            disabled={draft.params.length >= MAX_PARAMS}
            onClick={() => {
              let n = draft.params.length + 1;
              while (draft.params.some((p) => p.name === `param${n}`)) n++;
              onChange({ params: [...draft.params, { name: `param${n}`, label: "", default: "" }] });
            }}
          >
            <Plus />
            Ajouter
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Demandés à chaque lancement ; dans une étape : <code className="font-mono">{"{{params.nom}}"}</code> via « Utiliser… ».
        </p>
        {undeclared.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning/8 px-2 py-1.5 text-xs">
            <span className="min-w-0 flex-1">Cités sans être déclarés : {undeclared.join(", ")}.</span>
            <Button type="button" size="sm" variant="outline" className="h-7" onClick={onDeclareMissing}>
              Déclarer
            </Button>
          </div>
        )}
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-2">
          {draft.params.map((param, index) => {
            const bad = !STEP_ID.test(param.name);
            return (
              <li key={index} className="grid grid-cols-[minmax(0,1fr)] gap-1.5 rounded-md border border-atelier-line bg-card p-2">
                <div className="flex items-center gap-1">
                  <Input
                    aria-label={`Nom du paramètre ${index + 1}`}
                    className="h-7 flex-1 font-mono text-xs"
                    value={param.name}
                    maxLength={40}
                    aria-invalid={bad}
                    onChange={(e) => setParam(index, { name: e.target.value })}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="size-7"
                    aria-label={`Retirer le paramètre ${param.name}`}
                    onClick={() => onChange({ params: draft.params.filter((_, i) => i !== index) })}
                  >
                    <Trash2 />
                  </Button>
                </div>
                <Input
                  aria-label={`Libellé de ${param.name}`}
                  className="h-7"
                  placeholder="Libellé (ex. Jeu de données)"
                  maxLength={80}
                  value={param.label}
                  onChange={(e) => setParam(index, { label: e.target.value })}
                />
                <Input
                  aria-label={`Valeur par défaut de ${param.name}`}
                  className="h-7"
                  placeholder="Valeur par défaut"
                  maxLength={500}
                  value={param.default}
                  onChange={(e) => setParam(index, { default: e.target.value })}
                />
                {bad && <p className="text-[11px] text-destructive">Nom : minuscule en tête, puis a-z, 0-9 ou _.</p>}
              </li>
            );
          })}
        </ul>
      </section>

      {global.length > 0 && (
        <section className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <SectionTitle>À corriger</SectionTitle>
          <Errors errors={global} />
        </section>
      )}
    </div>
  );
}
