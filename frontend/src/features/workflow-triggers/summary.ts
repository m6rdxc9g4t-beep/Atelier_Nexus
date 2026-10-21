/**
 * Résumés lisibles des déclencheurs (docs/declencheurs-api.md) : horaire (« Chaque jour à 08:00,
 * du lundi au vendredi »), événement (« Quand Projets publie « Statut changé » et data.to = CLOSED »),
 * compteurs, dates relatives. Logique pure, testée dans summary.test.ts.
 */

import type { EventFilter, EventsCatalog, Schedule, Trigger, TriggerBody, TriggerCounters, Weekday } from "@/types/api";

export const WEEKDAYS: Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export const WEEKDAY_LABEL: Record<Weekday, string> = {
  mon: "lundi",
  tue: "mardi",
  wed: "mercredi",
  thu: "jeudi",
  fri: "vendredi",
  sat: "samedi",
  sun: "dimanche",
};

/** Initiale affichée sur les cases des jours (le nom complet sert de libellé accessible). */
export const WEEKDAY_SHORT: Record<Weekday, string> = {
  mon: "L",
  tue: "M",
  wed: "M",
  thu: "J",
  fri: "V",
  sat: "S",
  sun: "D",
};

/** « 1 lancement », « 0 lancement », « 3 lancements » (règle française : 0 et 1 au singulier). */
export const plural = (n: number, one: string, many: string): string => `${n} ${Math.abs(n) >= 2 ? many : one}`;

/** Liste française : « a », « a et b », « a, b et c ». */
export function joinFr(items: string[], last = "et"): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} ${last} ${items[items.length - 1]}`;
}

/** « Toutes les 5 minutes », « Toutes les heures », « Toutes les 2 heures ». */
export function intervalText(minutes: number): string {
  if (minutes === 60) return "Toutes les heures";
  if (minutes > 60 && minutes % 60 === 0) return `Toutes les ${minutes / 60} heures`;
  if (minutes === 1) return "Toutes les minutes";
  return `Toutes les ${minutes} minutes`;
}

/**
 * Jours cochés en clair : les suites d'au moins trois jours consécutifs deviennent « du lundi au
 * vendredi » (le dimanche et le lundi se suivent : « du samedi au lundi »), les autres « le mardi ».
 */
export function daysText(days: Weekday[]): string {
  const set = new Set(days.filter((d) => WEEKDAYS.includes(d)));
  if (set.size === 0) return "";
  const has = (i: number) => set.has(WEEKDAYS[((i % 7) + 7) % 7]!);
  // Départ : premier jour coché dont la veille ne l'est pas (gère la semaine qui boucle)
  const start = WEEKDAYS.findIndex((_, i) => has(i) && !has(i - 1));
  const runs: Weekday[][] = [];
  let current: Weekday[] = [];
  for (let k = 0; k < 7; k++) {
    const i = start + k;
    if (has(i)) current.push(WEEKDAYS[i % 7]!);
    else if (current.length) {
      runs.push(current);
      current = [];
    }
  }
  if (current.length) runs.push(current);
  const parts = runs.flatMap((run) =>
    run.length >= 3
      ? [`du ${WEEKDAY_LABEL[run[0]!]} au ${WEEKDAY_LABEL[run[run.length - 1]!]}`]
      : run.map((d) => `le ${WEEKDAY_LABEL[d]}`),
  );
  return joinFr(parts);
}

/** « Chaque jour à 08:00, du lundi au vendredi » ; « Chaque lundi à 08:00 » ; « Toutes les 15 minutes ». */
export function scheduleText(schedule: Schedule): string {
  if (schedule.kind === "interval") return intervalText(schedule.every_minutes);
  const days = [...new Set(schedule.days)];
  if (days.length === 0 || days.length >= 7) return `Chaque jour à ${schedule.at}`;
  if (days.length === 1) return `Chaque ${WEEKDAY_LABEL[days[0]!]} à ${schedule.at}`;
  return `Chaque jour à ${schedule.at}, ${daysText(days)}`;
}

const FILTER_OP_TEXT: Record<Exclude<EventFilter["op"], "in" | "exists" | "contains">, string> = {
  eq: "=",
  ne: "≠",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
};

const valueText = (value: unknown): string =>
  value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value);

/** « data.to = CLOSED », « data.to parmi CLOSED ou RESOLVED », « subject.label contient « doc » ». */
export function filterText(filter: EventFilter): string {
  if (filter.op === "exists") return `${filter.path} est renseigné`;
  if (filter.op === "in") {
    const values = Array.isArray(filter.value) ? filter.value.map(valueText) : [valueText(filter.value)];
    return `${filter.path} parmi ${joinFr(values, "ou")}`;
  }
  if (filter.op === "contains") return `${filter.path} contient « ${valueText(filter.value)} »`;
  return `${filter.path} ${FILTER_OP_TEXT[filter.op]} ${valueText(filter.value)}`;
}

/** Nom court de l'application (« Atelier Projets » → « Projets »). */
export function appShortName(app: string, catalog?: EventsCatalog | null): string {
  const name = catalog?.apps.find((a) => a.app === app)?.name;
  if (name) return name.replace(/^Atelier\s+/i, "");
  return app.charAt(0).toUpperCase() + app.slice(1);
}

/** Libellé d'un type d'événement : celui du catalogue, sinon le type technique. */
export function eventTypeLabel(app: string, type: string, catalog?: EventsCatalog | null): string {
  return catalog?.apps.find((a) => a.app === app)?.events.find((e) => e.type === type)?.label ?? type;
}

/** Morceau de résumé ; `em` : nom d'événement mis en valeur. */
export interface SummaryPart {
  text: string;
  em?: boolean;
}

/** Résumé en morceaux (le composant met les noms d'événements en italique). */
export function triggerSummaryParts(trigger: TriggerBody | Trigger, catalog?: EventsCatalog | null): SummaryPart[] {
  if (trigger.kind === "schedule") return [{ text: scheduleText(trigger.schedule) }];
  const labels = trigger.types.map((t) => eventTypeLabel(trigger.app, t, catalog));
  const shown = labels.length > 3 ? labels.slice(0, 2) : labels;
  const parts: SummaryPart[] = [{ text: `Quand ${appShortName(trigger.app, catalog)} publie ` }];
  if (shown.length === 0) parts.push({ text: "un événement" });
  shown.forEach((label, i) => {
    if (i > 0) parts.push({ text: i === shown.length - 1 && labels.length <= 3 ? " ou " : ", " });
    parts.push({ text: label, em: true });
  });
  if (labels.length > 3) parts.push({ text: ` ou ${plural(labels.length - 2, "autre", "autres")}` });
  if (trigger.filters.length) parts.push({ text: ` et ${trigger.filters.map(filterText).join(" et ")}` });
  return parts;
}

/** Résumé en une ligne de texte, noms d'événements entre guillemets. */
export const triggerSummary = (trigger: TriggerBody | Trigger, catalog?: EventsCatalog | null): string =>
  triggerSummaryParts(trigger, catalog)
    .map((p) => (p.em ? `« ${p.text} »` : p.text))
    .join("");

/** Garde-fous en clair : regroupement des rafales et plafond horaire. */
export function limitsText(trigger: TriggerBody | Trigger): string {
  const parts: string[] = [];
  if (trigger.kind === "event" && trigger.debounce_seconds > 0)
    parts.push(`rafales regroupées sur ${plural(trigger.debounce_seconds, "seconde", "secondes")}`);
  parts.push(`${plural(trigger.max_runs_per_hour, "lancement", "lancements")} par heure au plus`);
  return parts.join(" · ");
}

/** Compteurs non nuls en clair (les lancements sont toujours cités). */
export function countersText(counters: TriggerCounters): string[] {
  const out = [plural(counters.fired, "lancement", "lancements")];
  if (counters.waiting) out.push(`${plural(counters.waiting, "ignoré", "ignorés")} (validation en attente)`);
  if (counters.throttled) out.push(`${plural(counters.throttled, "ignoré", "ignorés")} (plafond horaire)`);
  if (counters.filtered) out.push(`${plural(counters.filtered, "événement filtré", "événements filtrés")}`);
  if (counters.missed) out.push(`${plural(counters.missed, "horaire manqué", "horaires manqués")}`);
  if (counters.errors) out.push(plural(counters.errors, "erreur", "erreurs"));
  return out;
}

// ─── Dates relatives ─────────────────────────────────────────────

const parse = (iso: string | null | undefined): number | null => {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isFinite(t) ? t : null;
};

/** « à l'instant », « il y a 5 min », « il y a 2 h », « il y a 3 jours ». */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  const t = parse(iso);
  if (t === null) return "";
  const minutes = Math.floor((now.getTime() - t) / 60_000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${plural(Math.floor(hours / 24), "jour", "jours")}`;
}

/** « dans 5 min », « dans 2 h », « dans 3 jours » ; une date passée donne « imminent ». */
export function timeUntil(iso: string | null | undefined, now: Date = new Date()): string {
  const t = parse(iso);
  if (t === null) return "";
  const minutes = Math.ceil((t - now.getTime()) / 60_000);
  if (minutes <= 0) return "imminent";
  if (minutes < 60) return `dans ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `dans ${hours} h`;
  return `dans ${plural(Math.floor(hours / 24), "jour", "jours")}`;
}

/** Date d'une occurrence : « aujourd'hui à 08:00 », « demain à 08:00 », « lun. 27 oct. à 08:00 » (heure locale). */
export function occurrenceText(iso: string | null | undefined, now: Date = new Date()): string {
  const t = parse(iso);
  if (t === null) return "";
  const date = new Date(t);
  const time = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(date) - day(now)) / 86_400_000);
  if (days === 0) return `aujourd'hui à ${time}`;
  if (days === 1) return `demain à ${time}`;
  if (days === -1) return `hier à ${time}`;
  const label = date.toLocaleDateString("fr-FR", {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${label} à ${time}`;
}
