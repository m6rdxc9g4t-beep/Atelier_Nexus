/**
 * Contexte affiché par la barre des petits écrans (AppHeader) : l'onglet du Studio des workflows
 * s'il est ouvert, sinon l'accueil ou l'agent de la conversation (nom, icône, verrou local).
 * Logique pure, testée dans headerContext.test.ts.
 */

import type { StudioTab } from "@/features/workflows/studio";
import type { View } from "@/stores/useNavStore";
import type { AgentInfo } from "@/types/api";

/** Onglet du Studio des workflows (vue plein cadre) : celui de `studioTab` (features/workflows/studio.ts). */
export type StudioView = StudioTab;

const STUDIO_LABEL: Record<StudioView, string> = {
  workflows: "Workflows",
  map: "Carte de la suite",
  inbox: "À valider",
};

export interface HeaderContext {
  kind: "home" | "agent" | StudioView;
  label: string;
  icon: string | null;
  localOnly: boolean;
}

/** Identifiant lisible quand le catalogue n'est pas (encore) chargé : « data_analyst » → « Data analyst ». */
export function humanizeAgent(name: string): string {
  const text = name.replace(/[_-]+/g, " ").trim();
  return text ? text[0]!.toUpperCase() + text.slice(1) : "Agent";
}

export function headerContext(
  view: View,
  agentName: string,
  agents: Pick<AgentInfo, "name" | "display_name" | "icon" | "local_only">[],
  studio: StudioView | null = null,
): HeaderContext {
  if (studio) return { kind: studio, label: STUDIO_LABEL[studio], icon: null, localOnly: false };
  if (view === "home") return { kind: "home", label: "Accueil", icon: null, localOnly: false };
  const agent = agents.find((a) => a.name === agentName);
  return {
    kind: "agent",
    label: agent?.display_name || humanizeAgent(agentName),
    icon: agent?.icon ?? null,
    localOnly: !!agent?.local_only,
  };
}
