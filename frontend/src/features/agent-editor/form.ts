/** Logique pure de l'éditeur d'agents (testée dans form.test.ts). */

import type { CustomAgentDefinition, CustomAgentFields, ToolsetInfo } from "@/types/api";

export interface AgentForm extends CustomAgentFields {
  name: string;
  /** Exemples saisis un par ligne */
  startersText: string;
}

export const emptyForm = (): AgentForm => ({
  name: "",
  display_name: "",
  description: "",
  system_prompt: "",
  icon: "bot",
  category: "Mes agents",
  toolsets: ["core"],
  privacy: "standard",
  default_provider: null,
  starters: [],
  startersText: "",
});

export const formFrom = (d: CustomAgentDefinition): AgentForm => ({
  ...d,
  startersText: d.starters.join("\n"),
});

/** Identifiant dérivé du nom affiché : « Veille Réseaux » → « veille_reseaux ». */
export function slugify(label: string): string {
  const slug = label
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
  return /^[a-z]/.test(slug) ? slug : `agent_${slug}`.slice(0, 40);
}

/** Vrai si l'une des boîtes choisies impose le modèle local. */
export function forcesLocal(form: AgentForm, toolsets: ToolsetInfo[]): boolean {
  return toolsets.some((t) => t.sensitive && form.toolsets.includes(t.id));
}

export function validate(form: AgentForm, reserved: string[], editing: boolean): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!editing) {
    if (!/^[a-z][a-z0-9_]{2,40}$/.test(form.name))
      errors.name = "3 à 41 caractères : minuscules, chiffres et « _ », en commençant par une lettre.";
    else if (reserved.includes(form.name)) errors.name = "Ce nom est celui d'un agent fourni.";
  }
  if (form.display_name.trim().length < 2) errors.display_name = "Donnez un nom à l'agent.";
  if (form.description.trim().length < 5) errors.description = "Décrivez son rôle en une phrase.";
  if (form.system_prompt.trim().length < 20)
    errors.system_prompt = "Écrivez au moins quelques phrases de consignes (20 caractères minimum).";
  const starters = toStarters(form.startersText);
  if (starters.length > 6) errors.startersText = "Six exemples au maximum.";
  if (starters.some((s) => s.length > 200)) errors.startersText = "Chaque exemple fait au plus 200 caractères.";
  return errors;
}

export const toStarters = (text: string) =>
  text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

/** Corps envoyé à l'API (le verrou local est appliqué si une boîte sensible est cochée). */
export function toPayload(form: AgentForm, toolsets: ToolsetInfo[]): CustomAgentFields {
  const local = forcesLocal(form, toolsets) || form.privacy === "local_only";
  return {
    display_name: form.display_name.trim(),
    description: form.description.trim(),
    system_prompt: form.system_prompt.trim(),
    icon: form.icon,
    category: form.category.trim() || "Mes agents",
    toolsets: form.toolsets,
    privacy: local ? "local_only" : "standard",
    default_provider: local ? null : form.default_provider,
    starters: toStarters(form.startersText),
  };
}
