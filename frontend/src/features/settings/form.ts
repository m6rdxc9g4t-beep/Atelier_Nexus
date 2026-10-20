/**
 * Brouillon de l'écran Réglages, sans React (testé dans form.test.ts).
 * Un secret n'est jamais renvoyé par le serveur : champ vide = garder la valeur actuelle,
 * « Effacer » = retirer du fichier.
 */

import type { SettingsField, SettingsGroup, SettingsView } from "@/types/api";

export interface DraftField {
  value: string;
  /** Secret à retirer du fichier. */
  clear: boolean;
}

export type Draft = Record<string, DraftField>;

export const GROUPS: SettingsGroup[] = ["Modèles", "Applications Atelier", "GitHub"];

export function initialDraft(view: SettingsView): Draft {
  return Object.fromEntries(
    view.fields.map((f) => [f.key, { value: f.kind === "secret" ? "" : (f.value ?? ""), clear: false }]),
  );
}

/** Changements à envoyer : uniquement ce qui a bougé ; null = retirer (retour au défaut). */
export function changes(view: SettingsView, draft: Draft): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const field of view.fields) {
    const d = draft[field.key];
    if (!d || field.source === "environnement") continue;
    if (field.kind === "secret") {
      if (d.clear && field.configured) out[field.key] = null;
      else if (d.value.trim()) out[field.key] = d.value.trim();
      continue;
    }
    const next = d.value.trim();
    if (next !== (field.value ?? "")) out[field.key] = next === "" ? null : next;
  }
  return out;
}

export function byGroup(view: SettingsView): [SettingsGroup, SettingsField[]][] {
  return GROUPS.map((g) => [g, view.fields.filter((f) => f.group === g)] as [SettingsGroup, SettingsField[]]).filter(
    ([, fields]) => fields.length > 0,
  );
}

export const CHOICE_LABELS: Record<string, string> = {
  "": "Aucun",
  anthropic: "Claude",
  ollama: "Ollama (local)",
  auto: "Automatique (recommandé)",
  cli: "Abonnement Claude (Claude Code)",
  api: "Clé API Anthropic",
  sonnet: "Sonnet (recommandé)",
  opus: "Opus (le plus performant, plus lent)",
  haiku: "Haiku (le plus rapide)",
};
