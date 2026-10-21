/**
 * Gabarits proposés par « Utiliser… » dans l'inspecteur : paramètres, sorties des étapes
 * ancêtres, insertion dans un champ. Logique pure, testée dans templates.test.ts.
 */

import type { CatalogEntry, WorkflowParam, WorkflowStepV2 } from "@/types/api";

import { usesLabel } from "./catalog";
import { ancestors, topoOrder } from "./graph";
import { isExactTemplate, template } from "./refs";

export interface TemplateOption {
  label: string;
  value: string;
  hint?: string;
}

export interface TemplateGroup {
  /** Titre du groupe (« Paramètres », « Lire les tâches (lire) »…) */
  label: string;
  /** Étape source, null pour les paramètres et l'exécution */
  stepId: string | null;
  options: TemplateOption[];
}

/**
 * Propositions « Utiliser… » d'un champ de l'étape `stepId` : paramètres déclarés, puis la sortie
 * de chaque étape ANCÊTRE (seules citables), dans l'ordre d'exécution. Pour une sortie
 * `atelier-table/1` qui annonce ses colonnes : valeur de la première ligne et nombre total.
 */
export function templateOptions(
  steps: WorkflowStepV2[],
  params: WorkflowParam[],
  stepId: string,
  catalog: Map<string, CatalogEntry>,
): TemplateGroup[] {
  const groups: TemplateGroup[] = [];
  if (params.length) {
    groups.push({
      label: "Paramètres",
      stepId: null,
      options: params.map((p) => ({
        label: p.label || p.name,
        value: template(`params.${p.name}`),
        hint: p.default ? `défaut : ${p.default}` : undefined,
      })),
    });
  }
  const upstream = ancestors(steps, stepId);
  const order = topoOrder(steps) ?? steps.map((s) => s.id);
  for (const id of order) {
    if (!upstream.has(id)) continue;
    const step = steps.find((s) => s.id === id);
    if (!step) continue;
    const entry = catalog.get(step.uses);
    const options: TemplateOption[] = [
      { label: "Sortie structurée", value: template(`steps.${id}.data`), hint: "JSON" },
      { label: "Texte", value: template(`steps.${id}.content`) },
    ];
    if (entry?.output_format === "atelier-table/1" && entry.output_hint?.columns?.length) {
      for (const column of entry.output_hint.columns) {
        options.push({
          label: `1re ligne · ${column.label || column.key}`,
          value: template(`steps.${id}.data.rows[0].${column.key}`),
          hint: column.type,
        });
      }
      options.push({ label: "Nombre de lignes", value: template(`steps.${id}.data.total`), hint: "number" });
    } else if (entry?.output_hint?.fields?.length) {
      for (const field of entry.output_hint.fields) {
        options.push({ label: `Champ ${field}`, value: template(`steps.${id}.data.${field}`) });
      }
    }
    options.push({ label: "Statut", value: template(`steps.${id}.status`), hint: "ok / error / refused / skipped" });
    groups.push({ label: `${step.label || usesLabel(step.uses, entry)} (${id})`, stepId: id, options });
  }
  groups.push({ label: "Exécution", stepId: null, options: [{ label: "Identifiant", value: template("run.id") }] });
  return groups;
}

/**
 * Valeur d'un champ après insertion d'un gabarit. Texte : ajouté à la suite (un gabarit inclus
 * dans un texte devient du texte). Autres natures (nombre, booléen, liste, objet) : le champ
 * devient exactement le gabarit, qui garde le type de sa cible.
 */
export function insertTemplate(current: unknown, tpl: string, kind: string): string {
  if (kind !== "string" || typeof current !== "string" || current === "" || isExactTemplate(current)) return tpl;
  return /\s$/.test(current) ? `${current}${tpl}` : `${current} ${tpl}`;
}

