/**
 * Brouillon de l'écran Réglages, sans React (testé dans form.test.ts).
 * Un secret n'est jamais renvoyé par le serveur : champ vide = garder la valeur actuelle,
 * « Effacer » = retirer du fichier.
 */

import { APPROVAL_CHOICES, APPROVAL_MODE_KEY } from "@/lib/approval";
import type { SettingsField, SettingsGroup, SettingsView } from "@/types/api";

export interface DraftField {
  value: string;
  /** Secret à retirer du fichier. */
  clear: boolean;
}

export type Draft = Record<string, DraftField>;

export const GROUPS: SettingsGroup[] = ["Validation des actions", "Modèles", "Applications Atelier", "Atelier Cuisine", "GitHub"];

/** Choix affichés en boutons radio (avec l'aide de chaque option) plutôt qu'en liste. */
export const RADIO_FIELDS = new Set([APPROVAL_MODE_KEY]);

/** Aide propre à chaque option d'un champ radio. */
export const CHOICE_HELP: Record<string, string> = {
  every_step: APPROVAL_CHOICES.every_step.help,
  writes_only: APPROVAL_CHOICES.writes_only.help,
};

/** Phrase affichée sous le titre d'un groupe. */
export const GROUP_NOTES: Partial<Record<SettingsGroup, string>> = {
  "Validation des actions":
    "Ce que les agents et les workflows (lancés à la main, par un horaire ou un événement) doivent vous faire " +
    "valider avant d'agir. Aucune autorisation n'est jamais permanente : chaque action se valide une par une.",
  "Atelier Cuisine":
    "App en ligne (Supabase). Nexus lit le stock, les repas, les courses et le budget du foyer, en lecture seule, " +
    "avec la clé publique et le compte du foyer : seules ses données sont visibles. Le budget n'est lu que par " +
    "l'agent Finance, sur le modèle local.",
};

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
  every_step: APPROVAL_CHOICES.every_step.label,
  writes_only: APPROVAL_CHOICES.writes_only.label,
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
