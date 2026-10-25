/**
 * Chaîne d'applications d'un workflow (cartes du Studio, modèles, accueil) : « Convert › Tab ›
 * Viz », déduite des étapes. Logique pure, testée dans chain.test.ts.
 *
 * - v2 : `uses` lu par `parseUses` (« node:tab/rows.add » → tab ; « tool:data_via_query » →
 *   application de l'outil d'après son préfixe), dans l'ordre d'exécution (dépendances `needs`) ;
 * - v1 : nom de l'outil de chaque étape, dans l'ordre des étapes ;
 * - une application n'apparaît qu'une fois (première rencontre) ; un workflow d'outils système
 *   seulement est rattaché à Nexus.
 */

import { toolApp } from "@/features/chat-agent/agentApps";
import { SYSTEM_APP, parseUses } from "@/features/workflows-graph/catalog";

/** Étape v1 (`tool`) ou v2 (`uses`, `needs`) : seuls ces champs comptent ici. */
export interface ChainStep {
  id?: string;
  uses?: string;
  tool?: string;
  needs?: string[];
}

/** Application d'une étape, ou null (outil système, étape inconnue). */
export function stepApp(step: ChainStep): string | null {
  if (step.uses !== undefined) {
    const parsed = parseUses(step.uses);
    if (parsed.source === "node") return parsed.app;
    if (parsed.source === "tool") return toolApp(parsed.name);
    return null;
  }
  return step.tool ? toolApp(step.tool) : null;
}

/**
 * Ordre d'exécution stable : une étape vient après ses `needs` ; à égalité, l'ordre de la liste.
 * Une dépendance inconnue est ignorée ; un cycle (brouillon invalide) garde l'ordre de la liste.
 */
export function executionOrder<T extends ChainStep>(steps: T[]): T[] {
  const ids = new Set(steps.map((s) => s.id).filter((id): id is string => !!id));
  const done = new Set<string>();
  const out: T[] = [];
  const left = [...steps];
  while (left.length) {
    const i = left.findIndex((s) => (s.needs ?? []).every((n) => !ids.has(n) || done.has(n)));
    // Cycle : on prend la première restante pour ne jamais boucler
    const [next] = left.splice(i === -1 ? 0 : i, 1);
    out.push(next!);
    if (next!.id) done.add(next!.id);
  }
  return out;
}

/** Applications du workflow, sans doublon, dans l'ordre d'exécution. */
export function workflowChain(steps: ChainStep[]): string[] {
  const apps: string[] = [];
  let system = false;
  for (const step of executionOrder(steps)) {
    const app = stepApp(step);
    if (!app) system = true;
    else if (!apps.includes(app)) apps.push(app);
  }
  return apps.length === 0 && system ? [SYSTEM_APP] : apps;
}

/**
 * Puces affichées : les `max` premières, puis « +n » (`rest` : leurs noms, en info-bulle). Une
 * application répétée (liste venue du serveur) n'est montrée qu'une fois.
 */
export function chainView(apps: string[], max = 4): { shown: string[]; hidden: number; rest: string[] } {
  const unique = [...new Set(apps)];
  return { shown: unique.slice(0, max), hidden: Math.max(unique.length - max, 0), rest: unique.slice(max) };
}

/** Phrase accessible de la chaîne : « Applications : Convert, puis Tab, puis Viz ». */
export function chainLabel(apps: string[], name: (app: string) => string): string {
  const unique = [...new Set(apps)];
  if (unique.length === 0) return "Aucune application";
  return `Applications : ${unique.map(name).join(", puis ")}`;
}
