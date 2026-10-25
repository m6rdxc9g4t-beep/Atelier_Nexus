/** Jours écoulés entre deux dates, au calendrier local (0 : même jour). */
function daysBetween(date: Date, now: Date): number {
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((day(now) - day(date)) / 86_400_000);
}

/** Date lisible d'une conversation : « Aujourd'hui, 14:05 », « Hier, 14:05 », puis « 12 oct. » ou « 12 oct. 2025 ». */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const days = daysBetween(date, now);
  if (days === 0) return `Aujourd'hui, ${time}`;
  if (days === 1) return `Hier, ${time}`;
  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

export type DayGroup = "Aujourd'hui" | "Hier" | "Plus ancien";

/**
 * Historique groupé par date (Aujourd'hui, Hier, Plus ancien), groupes vides omis ; l'ordre des
 * conversations (les plus récentes d'abord, côté serveur) est gardé. Une date illisible va avec
 * les plus anciennes.
 */
export function groupByDay<T extends { updated_at: string }>(
  items: T[],
  now: Date = new Date(),
): { label: DayGroup; items: T[] }[] {
  const groups: { label: DayGroup; items: T[] }[] = [
    { label: "Aujourd'hui", items: [] },
    { label: "Hier", items: [] },
    { label: "Plus ancien", items: [] },
  ];
  for (const item of items) {
    const date = new Date(item.updated_at);
    const days = Number.isNaN(date.getTime()) ? Infinity : daysBetween(date, now);
    groups[days <= 0 ? 0 : days === 1 ? 1 : 2]!.items.push(item);
  }
  return groups.filter((g) => g.items.length > 0);
}

/** Date d'une ligne sous le titre de son groupe : l'heure seule pour « Aujourd'hui » et « Hier »
 * (le jour est déjà dans le titre), la date sinon. */
export function formatWhenIn(iso: string, group: DayGroup, now: Date = new Date()): string {
  if (group === "Plus ancien") return formatWhen(iso, now);
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
