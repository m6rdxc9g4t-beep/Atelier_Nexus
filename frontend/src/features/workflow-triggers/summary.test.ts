import { describe, expect, it } from "vitest";

import { eventTriggerFixture, eventsCatalogFixture, scheduleTriggerFixture } from "./fixtures";
import {
  countersText,
  daysText,
  filterText,
  limitsText,
  occurrenceText,
  plural,
  scheduleText,
  timeAgo,
  timeUntil,
  triggerSummary,
  triggerSummaryParts,
} from "./summary";

describe("résumé d'un horaire", () => {
  it("regroupe les jours consécutifs", () => {
    expect(daysText(["mon", "tue", "wed", "thu", "fri"])).toBe("du lundi au vendredi");
    expect(daysText(["fri", "mon", "wed"])).toBe("le lundi, le mercredi et le vendredi");
    expect(daysText(["mon", "tue"])).toBe("le lundi et le mardi");
    expect(daysText(["mon", "tue", "wed", "fri"])).toBe("du lundi au mercredi et le vendredi");
    // La semaine boucle : samedi, dimanche, lundi se suivent
    expect(daysText(["sat", "sun", "mon"])).toBe("du samedi au lundi");
    expect(daysText(["sat", "sun"])).toBe("le samedi et le dimanche");
    expect(daysText([])).toBe("");
  });

  it("écrit l'horaire en clair", () => {
    expect(scheduleText({ kind: "daily", at: "08:00", days: ["mon", "tue", "wed", "thu", "fri"] })).toBe(
      "Chaque jour à 08:00, du lundi au vendredi",
    );
    expect(scheduleText({ kind: "daily", at: "18:30", days: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] })).toBe("Chaque jour à 18:30");
    expect(scheduleText({ kind: "daily", at: "09:15", days: ["mon"] })).toBe("Chaque lundi à 09:15");
    expect(scheduleText({ kind: "interval", every_minutes: 15 })).toBe("Toutes les 15 minutes");
    expect(scheduleText({ kind: "interval", every_minutes: 60 })).toBe("Toutes les heures");
    expect(scheduleText({ kind: "interval", every_minutes: 180 })).toBe("Toutes les 3 heures");
    expect(scheduleText({ kind: "interval", every_minutes: 90 })).toBe("Toutes les 90 minutes");
    expect(triggerSummary(scheduleTriggerFixture())).toBe("Chaque jour à 08:00, du lundi au vendredi");
  });
});

describe("résumé d'un événement", () => {
  it("cite l'app, le type et les filtres", () => {
    expect(triggerSummary(eventTriggerFixture(), eventsCatalogFixture)).toBe("Quand Projets publie « Statut changé » et data.to = CLOSED");
    const parts = triggerSummaryParts(eventTriggerFixture(), eventsCatalogFixture);
    expect(parts.find((p) => p.em)?.text).toBe("Statut changé");
  });

  it("liste plusieurs types et résume au-delà de trois", () => {
    const two = eventTriggerFixture({ types: ["projets.work_item.status_changed", "projets.work_item.created"], filters: [] });
    expect(triggerSummary(two, eventsCatalogFixture)).toBe("Quand Projets publie « Statut changé » ou « Élément créé »");
    const four = eventTriggerFixture({ types: ["a", "b", "c", "d"], filters: [] });
    expect(triggerSummary(four, eventsCatalogFixture)).toBe("Quand Projets publie « a », « b » ou 2 autres");
  });

  it("garde le type technique sans catalogue", () => {
    expect(triggerSummary(eventTriggerFixture({ filters: [] }), null)).toBe("Quand Projets publie « projets.work_item.status_changed »");
  });

  it("écrit chaque opérateur de filtre", () => {
    expect(filterText({ path: "data.to", op: "in", value: ["CLOSED", "RESOLVED"] })).toBe("data.to parmi CLOSED ou RESOLVED");
    expect(filterText({ path: "data.rows", op: "gte", value: 10 })).toBe("data.rows ≥ 10");
    expect(filterText({ path: "subject.label", op: "contains", value: "doc" })).toBe("subject.label contient « doc »");
    expect(filterText({ path: "data.project_id", op: "exists" })).toBe("data.project_id est renseigné");
    expect(filterText({ path: "data.to", op: "ne", value: "OPEN" })).toBe("data.to ≠ OPEN");
  });
});

describe("compteurs et dates", () => {
  it("accorde au pluriel à partir de 2", () => {
    expect(plural(0, "lancement", "lancements")).toBe("0 lancement");
    expect(plural(1, "lancement", "lancements")).toBe("1 lancement");
    expect(plural(2, "lancement", "lancements")).toBe("2 lancements");
    expect(
      countersText({ fired: 3, throttled: 1, waiting: 2, filtered: 0, missed: 1, errors: 0 }),
    ).toEqual(["3 lancements", "2 ignorés (validation en attente)", "1 ignoré (plafond horaire)", "1 horaire manqué"]);
    expect(limitsText(eventTriggerFixture({ debounce_seconds: 30, max_runs_per_hour: 1 }))).toBe(
      "rafales regroupées sur 30 secondes · 1 lancement par heure au plus",
    );
  });

  it("écrit les durées relatives", () => {
    const now = new Date("2026-10-21T10:00:00Z");
    expect(timeAgo("2026-10-21T09:59:40Z", now)).toBe("à l'instant");
    expect(timeAgo("2026-10-21T09:55:00Z", now)).toBe("il y a 5 min");
    expect(timeAgo("2026-10-21T07:00:00Z", now)).toBe("il y a 3 h");
    expect(timeAgo("2026-10-20T09:00:00Z", now)).toBe("il y a 1 jour");
    expect(timeAgo("2026-10-18T09:00:00Z", now)).toBe("il y a 3 jours");
    expect(timeAgo(null, now)).toBe("");
    expect(timeUntil("2026-10-21T10:04:10Z", now)).toBe("dans 5 min");
    expect(timeUntil("2026-10-21T12:30:00Z", now)).toBe("dans 2 h");
    expect(timeUntil("2026-10-21T09:00:00Z", now)).toBe("imminent");
  });

  it("date une occurrence par rapport à aujourd'hui", () => {
    const now = new Date(2026, 9, 21, 10, 0);
    expect(occurrenceText(new Date(2026, 9, 21, 18, 0).toISOString(), now)).toBe("aujourd'hui à 18:00");
    expect(occurrenceText(new Date(2026, 9, 22, 8, 0).toISOString(), now)).toBe("demain à 08:00");
    expect(occurrenceText(new Date(2026, 9, 27, 8, 0).toISOString(), now)).toMatch(/27 oct\. à 08:00$/);
  });
});
