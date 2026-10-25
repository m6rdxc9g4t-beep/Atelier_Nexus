/**
 * Studio des workflows de suite (vue plein cadre : Workflows, Carte de la suite, À valider) :
 * onglet affiché d'après le store, recherche et portée de « Mes workflows », textes des cartes,
 * modèles de la suite mis en avant. Logique pure, testée dans studio.test.ts.
 */

import { formatWhen } from "@/features/chat-agent/formatWhen";
import { fold } from "@/features/workflows-graph/catalog";
import type { EditorTarget, TemplateSeed } from "@/stores/useWorkflowStudioStore";
import type { AnyWorkflow, WorkflowTemplate } from "@/types/api";

export type StudioTab = "workflows" | "map" | "inbox";

const WINDOW_TAB = { list: "workflows", map: "map", inbox: "inbox" } as const satisfies Record<string, StudioTab>;

/**
 * Onglet du Studio, ou null (accueil ou conversation). Pendant l'éditeur en graphe (fenêtre plein
 * écran par-dessus), le Studio reste affiché sur l'onglet de retour : recherche et défilement
 * sont retrouvés à la fermeture.
 */
export function studioTab(s: {
  listOpen: boolean;
  mapOpen: boolean;
  inboxOpen: boolean;
  editor: unknown;
  returnTo: keyof typeof WINDOW_TAB | null;
}): StudioTab | null {
  if (s.listOpen) return "workflows";
  if (s.mapOpen) return "map";
  if (s.inboxOpen) return "inbox";
  return s.editor && s.returnTo ? WINDOW_TAB[s.returnTo] : null;
}

/**
 * Section de l'onglet Workflows : un agent suivi (bouton Workflows de sa conversation, quel que
 * soit l'appelant) montre toujours ses workflows ; les modèles de la suite sont sans agent.
 */
export const shownSection = (section: "mine" | "templates", listAgent: string | null): "mine" | "templates" =>
  listAgent ? "mine" : section;

/** Portée de « Mes workflows » : tous, ceux de la suite (sans agent), ceux de l'agent suivi. */
export type Scope = "all" | "suite" | "agent";

/**
 * Workflows de la portée qui contiennent tous les mots cherchés (titre, description, agent ;
 * sans accents ni casse).
 */
export function filterWorkflows(
  items: AnyWorkflow[],
  { scope, agent, query, ownerName }: { scope: Scope; agent: string | null; query: string; ownerName: (wf: AnyWorkflow) => string },
): AnyWorkflow[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  return items.filter((wf) => {
    if (scope === "suite" && wf.agent) return false;
    if (scope === "agent" && wf.agent !== agent) return false;
    if (!words.length) return true;
    const haystack = fold(`${wf.title} ${wf.description} ${ownerName(wf)}`);
    return words.every((w) => haystack.includes(w));
  });
}

const plural = (n: number, one: string, many: string) => `${n} ${n >= 2 ? many : one}`;

/** « 4 étapes · 2 paramètres » (les paramètres seulement s'il y en a). */
export function stepsText(steps: number, params: number): string {
  const head = plural(steps, "étape", "étapes");
  return params > 0 ? `${head} · ${plural(params, "paramètre", "paramètres")}` : head;
}

/** « Lancé aujourd'hui, 14:05 », « Lancé le 12 oct. », « Jamais lancé ». */
export function lastRunText(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "Jamais lancé";
  const when = formatWhen(iso, now);
  if (!when) return "Jamais lancé";
  if (/^(Aujourd'hui|Hier)/.test(when)) return `Lancé ${when.charAt(0).toLowerCase()}${when.slice(1)}`;
  return `Lancé le ${when}`;
}

type BadgeVariant = "success" | "destructive" | "warning" | "default";

const LAST_STATUS: Record<string, { variant: BadgeVariant; label: string }> = {
  completed: { variant: "success", label: "réussi" },
  failed: { variant: "destructive", label: "échec" },
  stopped: { variant: "warning", label: "arrêté (refus)" },
  awaiting_approval: { variant: "warning", label: "à valider" },
  running: { variant: "default", label: "en cours" },
};

/** Badge du dernier lancement (v1 et v2) ; null si jamais lancé ou statut inconnu. */
export const lastStatus = (status: string | null | undefined) => (status ? (LAST_STATUS[status] ?? null) : null);

/** Modèles disponibles d'abord, dans l'ordre du serveur. */
export const orderTemplates = (templates: WorkflowTemplate[]): WorkflowTemplate[] => [
  ...templates.filter((t) => t.available),
  ...templates.filter((t) => !t.available),
];

/** Accueil : `n` modèles, les disponibles d'abord, complétés par les autres (l'accueil reste plein). */
export const homeTemplates = (templates: WorkflowTemplate[], n = 3): WorkflowTemplate[] =>
  orderTemplates(templates).slice(0, n);

/**
 * Ce qui manque à un modèle, en clair : « node:convert/conversions.list : Atelier Convert
 * injoignable » devient « Atelier Convert injoignable » (l'étape technique passe en info-bulle) ;
 * une même raison n'est dite qu'une fois.
 */
export function missingLines(missing: string[]): { text: string; detail: string | null }[] {
  const out: { text: string; detail: string[] }[] = [];
  for (const line of missing) {
    const cut = line.indexOf(" : ");
    const technical = cut > 0 && /^(node|tool):\S+$/.test(line.slice(0, cut));
    const text = technical ? line.slice(cut + 3).trim() : line.trim();
    if (!text) continue;
    const seen = out.find((o) => o.text === text);
    const detail = technical ? [line.slice(0, cut)] : [];
    if (seen) seen.detail.push(...detail);
    else out.push({ text, detail });
  }
  return out.map((o) => ({ text: o.text, detail: o.detail.length ? o.detail.join(", ") : null }));
}

/** Graine du brouillon d'un modèle (cible de l'éditeur en graphe). */
export const templateSeed = ({ slug, title, description, params, steps }: WorkflowTemplate): TemplateSeed => ({
  slug,
  title,
  description,
  params,
  steps,
});

/**
 * « Utiliser ce modèle » (galerie, accueil) : nouveau workflow de suite prérempli du modèle,
 * brouillon que l'éditeur en graphe tire de `template` (rien n'est enregistré ni lancé).
 */
export const templateTarget = (template: WorkflowTemplate): EditorTarget => ({
  kind: "new",
  agent: null,
  template: templateSeed(template),
});
