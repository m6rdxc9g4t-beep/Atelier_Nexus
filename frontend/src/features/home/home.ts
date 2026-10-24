/**
 * Accueil : salutation, agents mis en avant, résumé de l'état de la suite.
 * Logique pure, testée dans home.test.ts.
 */

import type { AgentInfo, AppStatus } from "@/types/api";

/** « Bonjour » de 5 h à 18 h, « Bonsoir » ensuite. */
export const greeting = (hour: number): string => (hour >= 5 && hour < 18 ? "Bonjour" : "Bonsoir");

/**
 * Agents mis en avant : le premier de chaque catégorie, dans l'ordre du catalogue, puis les
 * suivants jusqu'à `max` (agents personnalisés compris).
 */
export function featuredAgents(agents: AgentInfo[], max = 6): AgentInfo[] {
  const seen = new Set<string>();
  const first: AgentInfo[] = [];
  for (const agent of agents) {
    const category = agent.category ?? "Agents";
    if (seen.has(category)) continue;
    seen.add(category);
    first.push(agent);
  }
  const rest = agents.filter((a) => !first.includes(a));
  return [...first, ...rest].slice(0, max);
}

/** Résumé de l'état des applications : joignables, en panne (configurées), non configurées. */
export function appsSummary(apps: AppStatus[]): { up: number; down: number; off: number; total: number } {
  let up = 0;
  let down = 0;
  let off = 0;
  for (const app of apps) {
    if (app.available) up += 1;
    else if (app.configured) down += 1;
    else off += 1;
  }
  return { up, down, off, total: apps.length };
}

/** Phrase d'état de la suite pour l'accueil. */
export function appsSentence({ up, down, total }: ReturnType<typeof appsSummary>): string {
  if (total === 0) return "Aucune application de la suite n'est déclarée.";
  if (up === total) return "Toutes les applications répondent.";
  if (up === 0) return "Aucune application ne répond pour l'instant.";
  const pannes = down > 0 ? ` · ${down} injoignable${down >= 2 ? "s" : ""}` : "";
  return `${up} sur ${total} répondent${pannes}.`;
}
