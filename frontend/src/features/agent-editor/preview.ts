/**
 * Aperçu de l'éditeur d'agents, sans React (testé dans preview.test.ts) : nom français de chaque
 * icône (annoncé par les lecteurs d'écran au lieu de l'identifiant Lucide) et applications que
 * l'agent touchera d'après les boîtes à outils cochées.
 */

import { agentApps } from "@/features/chat-agent/agentApps";
import type { ToolsetInfo } from "@/types/api";

/** Nom de chaque icône proposée (liste de app/schemas/agents.py). */
export const ICON_LABELS: Record<string, string> = {
  bot: "Robot",
  sparkles: "Étincelles",
  network: "Réseau",
  "chart-column": "Graphique",
  "list-checks": "Liste de tâches",
  code: "Code",
  landmark: "Banque",
  receipt: "Reçu",
  megaphone: "Mégaphone",
  "pen-line": "Stylo",
  briefcase: "Mallette",
  scale: "Balance",
  users: "Équipe",
  lightbulb: "Idée",
  "graduation-cap": "Diplôme",
  clapperboard: "Cinéma",
  headset: "Casque d'assistance",
  "shield-check": "Bouclier",
  "calendar-check": "Calendrier",
  "table-2": "Tableau",
  "cooking-pot": "Cuisine",
};

/** Nom affiché d'une icône ; une icône inconnue (extension) garde son identifiant, lisible. */
export function iconLabel(icon: string): string {
  return ICON_LABELS[icon] ?? `Icône ${icon.replaceAll("-", " ")}`;
}

/**
 * Applications de la suite touchées par les boîtes cochées, dans l'ordre du catalogue : l'app
 * déclarée par le serveur, sinon déduite des noms d'outils (boîtes des extensions).
 */
export function previewApps(selected: string[], toolsets: ToolsetInfo[]): string[] {
  const out: string[] = [];
  for (const toolset of toolsets) {
    if (!selected.includes(toolset.id)) continue;
    const apps = toolset.app ? [toolset.app] : agentApps({ toolsets: [toolset.id], tools: toolset.tools });
    for (const app of apps) if (!out.includes(app)) out.push(app);
  }
  return out;
}
