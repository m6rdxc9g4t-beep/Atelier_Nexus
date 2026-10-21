/**
 * Origine d'une exécution (Manuel, Horaire, Événement, Test) et boîte « À valider » : étiquettes,
 * phrase d'origine, interrogation du badge. Logique pure, testée dans origin.test.ts.
 */

import type { RunTrigger, WorkflowRun } from "@/types/api";

export const ORIGIN_LABEL: Record<RunTrigger, string> = {
  manual: "Manuel",
  schedule: "Horaire",
  event: "Événement",
  test: "Test",
};

/** Étiquette d'origine ; une valeur inconnue (backend plus récent) est affichée telle quelle. */
export const originLabel = (trigger: string | null | undefined): string =>
  trigger ? (ORIGIN_LABEL[trigger as RunTrigger] ?? trigger) : ORIGIN_LABEL.manual;

/**
 * Phrase d'origine : « Déclenché par projets.work_item.status_changed · Écrire la doc »,
 * « Déclenché par l'horaire », « Test du déclencheur », « Lancé à la main ».
 */
export function originText(run: Pick<WorkflowRun, "trigger" | "trigger_event">): string {
  const ev = run.trigger_event;
  const subject = ev ? ev.subject.label || ev.subject.id : "";
  const withEvent = ev ? `${ev.type}${subject ? ` · ${subject}` : ""}` : "";
  switch (run.trigger) {
    case "event":
      return ev ? `Déclenché par ${withEvent}` : "Déclenché par un événement";
    case "schedule":
      return "Déclenché par l'horaire";
    case "test":
      return ev ? `Test du déclencheur avec ${withEvent}` : "Test du déclencheur";
    case "manual":
    default:
      return "Lancé à la main";
  }
}

/** Délai de rafraîchissement du badge « À valider ». */
export const INBOX_POLL_MS = 20_000;

/** Texte du badge : au-delà de 99, « 99+ ». */
export const badgeText = (count: number): string => (count > 99 ? "99+" : String(count));

/** Libellé accessible du bouton « À valider ». */
export const inboxLabel = (count: number): string =>
  count === 0
    ? "À valider : rien en attente"
    : `À valider : ${count} exécution${count >= 2 ? "s" : ""} en attente de votre validation`;

/** Exécutions en attente, les plus récentes d'abord (le serveur trie déjà ; on garantit l'ordre). */
export function inboxOrder(runs: WorkflowRun[]): WorkflowRun[] {
  const time = (r: WorkflowRun) => {
    const t = new Date(r.updated_at || r.created_at).getTime();
    return Number.isFinite(t) ? t : 0;
  };
  return runs.filter((r) => r.status === "awaiting_approval").sort((a, b) => time(b) - time(a));
}
