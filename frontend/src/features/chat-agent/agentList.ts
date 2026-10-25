/**
 * Liste des agents de la barre latérale : recherche (sans accents ni casse) et regroupement par
 * catégorie dans l'ordre du catalogue. Logique pure, testée dans agentList.test.ts.
 */

import type { AgentInfo } from "@/types/api";

/** Texte comparable : minuscules, sans accents. */
export const fold = (text: string): string =>
  text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

/** Agents dont le nom, la description ou la catégorie contient chacun des mots cherchés. */
export function filterAgents(agents: AgentInfo[], query: string): AgentInfo[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return agents;
  return agents.filter((a) => {
    const haystack = fold([a.display_name, a.name, a.description, a.category ?? ""].join(" "));
    return words.every((w) => haystack.includes(w));
  });
}

/** Catégories dans l'ordre d'apparition (« Agents » pour un agent sans catégorie). */
export function groupAgents(agents: AgentInfo[]): [string, AgentInfo[]][] {
  const groups = new Map<string, AgentInfo[]>();
  for (const agent of agents) {
    const key = agent.category ?? "Agents";
    groups.set(key, [...(groups.get(key) ?? []), agent]);
  }
  return [...groups];
}

/** Catégories repliées mémorisées (liste JSON), en ignorant une valeur illisible. */
export function parseCollapsed(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}
