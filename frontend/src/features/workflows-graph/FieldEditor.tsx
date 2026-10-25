"use client";

import { Braces } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { ValidationError } from "@/types/api";

import { isExactTemplate } from "./refs";
import { type FormField, formatFieldValue, parseFieldInput } from "./schemaForm";
import type { TemplateGroup } from "./templates";

/** Menu « Utiliser… » : insère un paramètre ou la sortie d'une étape amont. */
export function TemplateMenu({
  groups,
  label,
  onPick,
}: {
  groups: TemplateGroup[];
  /** Nom du champ, pour le libellé accessible */
  label: string;
  onPick: (template: string) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" aria-label={`Utiliser une valeur pour ${label}`}>
          <Braces className="size-3.5" />
          Utiliser…
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-80 w-72 overflow-y-auto">
        {groups.map((group, i) => (
          <div key={`${group.label}-${i}`}>
            {i > 0 && <DropdownMenuSeparator />}
            <DropdownMenuLabel className="truncate">{group.label}</DropdownMenuLabel>
            {group.options.map((option) => (
              <DropdownMenuItem key={option.value} onSelect={() => onPick(option.value)} className="flex-col items-start gap-0">
                <span className="text-sm">{option.label}</span>
                <span className="flex w-full items-center gap-1.5 text-xs text-muted-foreground">
                  <code className="truncate font-mono">{option.value}</code>
                  {option.hint && <span className="ml-auto shrink-0">{option.hint}</span>}
                </span>
              </DropdownMenuItem>
            ))}
          </div>
        ))}
        {groups.length === 1 && (
          <p className="px-2 pb-1.5 text-xs text-muted-foreground">
            Reliez une étape en amont pour utiliser sa sortie.
          </p>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const KIND_HINT: Record<FormField["kind"], string> = {
  string: "texte",
  number: "nombre",
  integer: "entier",
  boolean: "vrai / faux",
  enum: "liste",
  array: "une valeur par ligne",
  json: "JSON",
};

/**
 * Champ d'entrée d'une étape, généré depuis son JSON Schema. La saisie en cours reste affichée
 * telle quelle (« 3, » avant « 3,5 ») ; la valeur n'est enregistrée que lisible.
 */
export function FieldEditor({
  field,
  value,
  errors,
  templates,
  onChange,
  onInsert,
}: {
  field: FormField;
  value: unknown;
  errors: ValidationError[];
  templates: TemplateGroup[];
  onChange: (value: unknown) => void;
  onInsert: (template: string) => void;
}) {
  const id = useId();
  const [raw, setRaw] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const text = raw ?? formatFieldValue(field, value);
  const templated = isExactTemplate(value);

  const change = (next: string) => {
    setRaw(next);
    const parsed = parseFieldInput(field, next);
    if (parsed.ok) {
      setProblem(null);
      onChange(parsed.value);
    } else setProblem(parsed.error);
  };
  const blur = () => {
    if (!problem) setRaw(null);
  };
  const insert = (tpl: string) => {
    setRaw(null);
    setProblem(null);
    onInsert(tpl);
  };

  const messages = [...(problem ? [problem] : []), ...errors.map((e) => e.message)];
  const describedBy = [field.description ? `${id}-desc` : "", messages.length ? `${id}-err` : ""].filter(Boolean).join(" ") || undefined;
  const common = {
    id,
    "aria-invalid": messages.length > 0,
    "aria-describedby": describedBy,
    "aria-required": field.required,
  };

  let control: React.ReactNode;
  if (field.kind === "enum" || field.kind === "boolean") {
    const options: { value: string; label: string }[] =
      field.kind === "boolean"
        ? [
            { value: "true", label: "Vrai" },
            { value: "false", label: "Faux" },
          ]
        : (field.options ?? []).map((o) => ({ value: String(o), label: String(o) }));
    control = (
      <NativeSelect
        {...common}
        className="w-full"
        value={templated ? String(value) : text}
        onChange={(e) => change(e.target.value)}
      >
        <option value="">{field.required ? "— choisir —" : "(non renseigné)"}</option>
        {templated && <option value={String(value)}>{String(value)}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
    );
  } else if (field.kind === "json" || field.kind === "array" || field.multiline) {
    control = (
      <Textarea
        {...common}
        rows={field.kind === "json" ? 3 : 2}
        spellCheck={field.kind === "string"}
        className={cn("min-h-14 text-sm", field.kind !== "string" && "font-mono text-xs")}
        value={text}
        placeholder={field.kind === "array" ? "Une valeur par ligne" : field.kind === "json" ? "{ … } ou {{steps.id.data}}" : undefined}
        onChange={(e) => change(e.target.value)}
        onBlur={blur}
      />
    );
  } else {
    control = (
      <Input
        {...common}
        className="h-8"
        inputMode={field.kind === "number" || field.kind === "integer" ? "decimal" : undefined}
        value={text}
        placeholder={field.default !== undefined ? `défaut : ${String(field.default)}` : undefined}
        onChange={(e) => change(e.target.value)}
        onBlur={blur}
      />
    );
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-1">
      <div className="flex items-center gap-1.5">
        <p className="min-w-0 flex-1 truncate text-xs">
          <label htmlFor={id} className="font-medium">
            {field.label}
            {field.required && (
              <span className="text-destructive" aria-hidden>
                {" "}
                *
              </span>
            )}
          </label>
          <span className="ml-1.5 text-muted-foreground" aria-hidden>
            {templated ? "gabarit" : KIND_HINT[field.kind]}
          </span>
        </p>
        <TemplateMenu groups={templates} label={field.label} onPick={insert} />
      </div>
      {control}
      {field.description && (
        <p id={`${id}-desc`} className="text-xs text-muted-foreground">
          {field.description}
        </p>
      )}
      {messages.length > 0 && (
        <p id={`${id}-err`} role="alert" className="text-xs text-destructive-ink">
          {messages.join(" ")}
        </p>
      )}
    </div>
  );
}
