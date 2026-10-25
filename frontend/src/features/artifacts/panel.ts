/**
 * Logique d'affichage du panneau Livrables (fonctions pures, testées dans panel.test.ts) :
 * provenance d'un livrable (conversation ou workflow), liste filtrée, position et voisins
 * précédent / suivant, livrable montré après un retrait, libellés, heure et nom de fichier.
 */

import type { ArtifactKind } from "@/types/api";

import { type PreviewData, toCsv } from "./preview";

/** Préfixe de `agent` des livrables d'une exécution de workflow (RunPanel : `workflow:<id>`). */
export const WORKFLOW_AGENT_PREFIX = "workflow:";

/** Provenance d'un livrable : réponse d'agent (conversation) ou exécution de workflow de suite. */
export type ArtifactScope = "conversation" | "workflow";

interface Listed {
  id: string;
  agent: string;
}

export const artifactScope = (artifact: { agent: string }): ArtifactScope =>
  artifact.agent.startsWith(WORKFLOW_AGENT_PREFIX) ? "workflow" : "conversation";

/** Nombre de livrables par provenance (le filtre n'est proposé que si les deux existent). */
export function scopeCounts(items: { agent: string }[]): Record<ArtifactScope, number> {
  const counts: Record<ArtifactScope, number> = { conversation: 0, workflow: 0 };
  for (const item of items) counts[artifactScope(item)] += 1;
  return counts;
}

/** Livrables d'une provenance, dans l'ordre du store (le plus récent en tête). */
export const inScope = <T extends { agent: string }>(items: T[], scope: ArtifactScope): T[] =>
  items.filter((item) => artifactScope(item) === scope);

/** Livrable à montrer quand on choisit une provenance : le plus récent, ou null. */
export const firstInScope = (items: Listed[], scope: ArtifactScope): string | null =>
  inScope(items, scope)[0]?.id ?? null;

/**
 * Filtre « Conversations / Workflows » choisi : le livrable le plus récent de l'autre provenance,
 * ou null (rien à changer) quand on reclique la provenance déjà affichée, pour ne pas quitter
 * le livrable en cours.
 */
export const selectionForScope = (items: Listed[], current: ArtifactScope, next: ArtifactScope): string | null =>
  next === current ? null : firstInScope(items, next);

export interface Position {
  /** Rang affiché, à partir de 1 (0 si le livrable n'est pas dans la liste). */
  index: number;
  total: number;
  /** Voisins dans l'ordre de la liste : « précédent » est au-dessus, « suivant » au-dessous. */
  previous: string | null;
  next: string | null;
}

export function positionOf(items: { id: string }[], id: string | null): Position {
  const at = items.findIndex((item) => item.id === id);
  if (at < 0) return { index: 0, total: items.length, previous: null, next: null };
  return {
    index: at + 1,
    total: items.length,
    previous: items[at - 1]?.id ?? null,
    next: items[at + 1]?.id ?? null,
  };
}

/** Après le retrait de `id` : son suivant dans la liste, sinon son précédent, sinon null. */
export function selectionAfterRemoval(items: { id: string }[], id: string): string | null {
  const { next, previous } = positionOf(items, id);
  return next ?? previous;
}

export const KIND_LABELS: Record<ArtifactKind, string> = {
  sql: "SQL",
  dax: "DAX",
  powerquery: "Power Query (M)",
  python: "Python",
  react: "React",
  code: "Code",
  markdown: "Document",
  json: "JSON",
  data_preview: "Données",
};

const EXTENSIONS: Record<ArtifactKind, string> = {
  sql: "sql",
  dax: "dax",
  powerquery: "pq",
  python: "py",
  react: "tsx",
  code: "txt",
  markdown: "md",
  json: "json",
  data_preview: "csv",
};

/** Famille d'un type, pour son icône : données, code, document ou JSON. */
export type KindFamily = "data" | "code" | "document" | "json";

export function kindFamily(kind: ArtifactKind): KindFamily {
  if (kind === "data_preview") return "data";
  if (kind === "markdown") return "document";
  if (kind === "json") return "json";
  return "code";
}

/** Le contenu s'affiche en code (numéros de ligne, retour à la ligne au choix). */
export const showsAsCode = (kind: ArtifactKind, preview: PreviewData | null): boolean =>
  !preview && kind !== "markdown";

/** Titre des notes d'intégration (`metadata.notes`) : Power BI pour DAX, Power Query ou s'il est cité. */
export function notesTitle(kind: ArtifactKind, notes: string): string {
  return kind === "dax" || kind === "powerquery" || /power\s*bi/i.test(notes)
    ? "Intégrer dans Power BI"
    : "Notes d'intégration";
}

/** Nom de fichier proposé à l'enregistrement : titre sans accents ni ponctuation + extension du type. */
export function downloadName(title: string, kind: ArtifactKind): string {
  const slug =
    title
      .normalize("NFD")
      .replace(/\p{M}/gu, "")
      .replace(/[^a-zA-Z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .toLowerCase() || "artefact";
  return `${slug}.${EXTENSIONS[kind]}`;
}

/** Texte copié ou enregistré : CSV pour un aperçu de données (ou son échantillon), sinon le contenu. */
export function exportPayload(content: string, preview: PreviewData | null): { text: string; type: string } {
  if (preview?.view === "table") return { text: toCsv(preview.table), type: "text/csv" };
  if (preview?.view === "schema" && preview.schema.sample) return { text: toCsv(preview.schema.sample), type: "text/csv" };
  return { text: content, type: "text/plain" };
}

/** Heure d'un livrable : « 14:05 » le jour même, « 12 oct., 14:05 » avant, l'année si elle diffère. */
export function artifactTime(createdAt: number, now: Date = new Date()): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const sameDay =
    date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
  if (sameDay) return time;
  const day = date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${day}, ${time}`;
}

/** Sous-titre de l'en-tête : « SQL · 14:05 », ou le type seul si la date est illisible. */
export const artifactSubtitle = (kind: ArtifactKind, createdAt: number, now?: Date): string =>
  [KIND_LABELS[kind], artifactTime(createdAt, now)].filter(Boolean).join(" · ");

/** « 1 ligne », « 12 lignes » (aperçus de données). */
export const rowCount = (n: number): string => `${n.toLocaleString("fr-FR")} ligne${n > 1 ? "s" : ""}`;
