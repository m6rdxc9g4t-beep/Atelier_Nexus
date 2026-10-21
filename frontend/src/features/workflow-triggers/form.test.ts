import { describe, expect, it } from "vitest";

import type { WorkflowParam } from "@/types/api";

import { eventTriggerFixture, eventsCatalogFixture, scheduleTriggerFixture } from "./fixtures";
import {
  bodyFromTrigger,
  catalogApp,
  cleanParams,
  draftFromTrigger,
  emptyTriggerDraft,
  eventTemplateOptions,
  filterFields,
  filterValue,
  hasErrors,
  insertEventTemplate,
  isTriggerApp,
  normalizeTime,
  parseSampleEvent,
  sampleEvent,
  toTriggerBody,
  validateTrigger,
} from "./form";

const params: WorkflowParam[] = [
  { name: "tache", label: "Tâche", default: "" },
  { name: "jeu", label: "Jeu", default: "ventes" },
];
const projets = catalogApp(eventsCatalogFixture, "projets");

describe("brouillon ↔ corps", () => {
  it("relit un horaire et un événement sans perte", () => {
    const schedule = scheduleTriggerFixture({ params: { jeu: "achats" } });
    const body = toTriggerBody(draftFromTrigger(schedule), params);
    expect(body).toEqual({
      kind: "schedule",
      label: "Bilan du matin",
      enabled: true,
      params: { jeu: "achats" },
      max_runs_per_hour: 12,
      schedule: { kind: "daily", at: "08:00", days: ["mon", "tue", "wed", "thu", "fri"] },
    });
    const event = eventTriggerFixture({ filters: [{ path: "data.to", op: "in", value: ["CLOSED", "RESOLVED"] }] });
    const back = toTriggerBody(draftFromTrigger(event), params);
    expect(back).toMatchObject({
      kind: "event",
      app: "projets",
      types: ["projets.work_item.status_changed"],
      filters: [{ path: "data.to", op: "in", value: ["CLOSED", "RESOLVED"] }],
      params: { tache: "{{event.subject.id}}" },
      debounce_seconds: 0,
    });
  });

  it("trie les jours, normalise l'heure et retire « value » pour exists", () => {
    const draft = emptyTriggerDraft("schedule", { at: "8:05", days: ["fri", "mon", "fri"] });
    expect(toTriggerBody(draft, params)).toMatchObject({ schedule: { kind: "daily", at: "08:05", days: ["mon", "fri"] } });
    const ev = emptyTriggerDraft("event", { app: "projets", types: ["t"], filters: [{ path: "data.project_id", op: "exists", value: "x" }] });
    const body = toTriggerBody(ev, params);
    expect(body.kind === "event" && body.filters[0]).toEqual({ path: "data.project_id", op: "exists" });
  });

  it("bascule actif / coupé sans rien perdre", () => {
    const trigger = eventTriggerFixture({ params: { inconnu: "x" }, debounce_seconds: 30 });
    const body = bodyFromTrigger(trigger, { enabled: false });
    expect(body).toMatchObject({ enabled: false, params: { inconnu: "x" }, debounce_seconds: 30, filters: trigger.filters });
    expect(body).not.toHaveProperty("state");
    expect(body).not.toHaveProperty("id");
    expect(bodyFromTrigger(scheduleTriggerFixture())).toMatchObject({ kind: "schedule", schedule: { kind: "daily", at: "08:00" } });
  });

  it("n'envoie que les paramètres déclarés et différents du défaut", () => {
    expect(cleanParams({ jeu: "ventes", tache: "{{event.subject.id}}", ancien: "x" }, params)).toEqual({ tache: "{{event.subject.id}}" });
  });

  it("type les valeurs de filtre", () => {
    expect(filterValue("in", "CLOSED, RESOLVED ,")).toEqual(["CLOSED", "RESOLVED"]);
    expect(filterValue("gte", "10,5")).toBe(10.5);
    expect(filterValue("eq", "1")).toBe("1");
    expect(filterValue("eq", "true")).toBe(true);
    expect(filterValue("exists", "x")).toBeUndefined();
  });
});

describe("validation locale", () => {
  it("accepte un horaire et un événement valides", () => {
    expect(validateTrigger(draftFromTrigger(scheduleTriggerFixture()), params)).toEqual({});
    expect(validateTrigger(draftFromTrigger(eventTriggerFixture()), params, projets)).toEqual({});
  });

  it("vérifie les bornes du contrat", () => {
    const interval = (every: string) => validateTrigger(emptyTriggerDraft("schedule", { scheduleKind: "interval", everyMinutes: every }), params);
    expect(interval("4").every_minutes).toBe("Entre 5 et 1440 minutes.");
    expect(interval("1441").every_minutes).toBeDefined();
    expect(interval("5")).toEqual({});
    expect(interval("1440")).toEqual({});
    expect(interval("7.5").every_minutes).toMatch(/entier/);
    expect(validateTrigger(emptyTriggerDraft("schedule", { maxRunsPerHour: "0" }), params).max_runs_per_hour).toBeDefined();
    expect(validateTrigger(emptyTriggerDraft("schedule", { maxRunsPerHour: "121" }), params).max_runs_per_hour).toBeDefined();
    expect(validateTrigger(emptyTriggerDraft("schedule", { maxRunsPerHour: "120" }), params)).toEqual({});
    const ev = (patch: Parameters<typeof emptyTriggerDraft>[1]) =>
      validateTrigger(emptyTriggerDraft("event", { app: "projets", types: ["projets.work_item.created"], ...patch }), params, projets);
    expect(ev({ debounceSeconds: "3601" }).debounce_seconds).toBeDefined();
    expect(ev({ debounceSeconds: "3600" })).toEqual({});
    expect(ev({ types: Array.from({ length: 11 }, (_, i) => `t${i}`) }).types).toBe("10 types au plus.");
    expect(ev({ filters: Array.from({ length: 11 }, () => ({ path: "data.to", op: "exists" as const, value: "" })) }).filters).toBeDefined();
  });

  it("exige une heure HH:MM et au moins un jour", () => {
    expect(normalizeTime("08:00")).toBe("08:00");
    expect(normalizeTime("7:30")).toBe("07:30");
    expect(normalizeTime("24:00")).toBeNull();
    expect(normalizeTime("08:60")).toBeNull();
    expect(normalizeTime("8h")).toBeNull();
    const errors = validateTrigger(emptyTriggerDraft("schedule", { at: "25:00", days: [] }), params);
    expect(Object.keys(errors).sort()).toEqual(["at", "days"]);
  });

  it("exige une app et au moins un type, connus du catalogue", () => {
    expect(Object.keys(validateTrigger(emptyTriggerDraft("event"), params)).sort()).toEqual(["app", "types"]);
    expect(validateTrigger(emptyTriggerDraft("event", { app: "projets", types: ["projets.inconnu"] }), params, projets).types).toMatch(/inconnu/);
    // App injoignable (catalogue vide) : le serveur tranchera
    const tab = catalogApp(eventsCatalogFixture, "tab");
    expect(validateTrigger(emptyTriggerDraft("event", { app: "tab", types: ["tab.table.changed"] }), params, tab)).toEqual({});
  });

  it("contrôle les filtres", () => {
    const check = (filter: { path: string; op: "eq" | "in" | "exists"; value: string }) =>
      validateTrigger(emptyTriggerDraft("event", { app: "projets", types: ["projets.work_item.created"], filters: [filter] }), params, projets)["filters.0"];
    expect(check({ path: "", op: "eq", value: "x" })).toBeDefined();
    expect(check({ path: "data.to", op: "eq", value: "" })).toBeDefined();
    expect(check({ path: "data.to", op: "in", value: " , " })).toBeDefined();
    expect(check({ path: "data.to", op: "exists", value: "" })).toBeUndefined();
    expect(check({ path: "ailleurs.x", op: "eq", value: "1" })).toBeDefined();
    expect(check({ path: "data.to", op: "eq", value: "{{event.data.to}}" })).toMatch(/paramètres/);
  });

  it("n'autorise les gabarits {{event…}} que dans les paramètres d'un déclencheur événement", () => {
    const schedule = validateTrigger(emptyTriggerDraft("schedule", { params: { tache: "{{event.subject.id}}" } }), params);
    expect(schedule["params.tache"]).toMatch(/horaire/);
    const ok = validateTrigger(
      emptyTriggerDraft("event", { app: "projets", types: ["projets.work_item.created"], params: { tache: "Tâche {{event.subject.id}} : {{event.data.to}}" } }),
      params,
      projets,
    );
    expect(hasErrors(ok)).toBe(false);
    const bad = validateTrigger(
      emptyTriggerDraft("event", { app: "projets", types: ["projets.work_item.created"], params: { tache: "{{event.subject.nom}}" } }),
      params,
      projets,
    );
    expect(bad["params.tache"]).toMatch(/inconnu/);
    expect(validateTrigger(emptyTriggerDraft("schedule", { label: "{{event.type}}" }), params).label).toBeDefined();
    expect(validateTrigger(emptyTriggerDraft("schedule", { params: { disparu: "x" } }), params)["params.disparu"]).toBeDefined();
    // {{params.x}} n'est pas un gabarit d'événement
    expect(validateTrigger(emptyTriggerDraft("schedule", { params: { tache: "{{params.jeu}}" } }), params)).toEqual({});
  });
});

describe("gabarits et événement d'exemple", () => {
  it("propose le sujet puis les champs data des types cochés", () => {
    const groups = eventTemplateOptions(projets, ["projets.work_item.status_changed"]);
    expect(groups[0]!.options.map((o) => o.value)).toContain("{{event.subject.id}}");
    expect(groups[1]!.options.map((o) => o.value)).toEqual(["{{event.data.from}}", "{{event.data.to}}", "{{event.data.project_id}}"]);
    expect(groups.at(-1)!.options.map((o) => o.value)).toEqual(["{{event.type}}", "{{event.at}}", "{{event.seq}}"]);
    // Sans données annoncées : pas de groupe « Données »
    expect(eventTemplateOptions(null, [])).toHaveLength(2);
  });

  it("insère un gabarit à la suite du texte", () => {
    expect(insertEventTemplate("", "{{event.subject.id}}")).toBe("{{event.subject.id}}");
    expect(insertEventTemplate("Tâche", "{{event.subject.id}}")).toBe("Tâche {{event.subject.id}}");
    expect(insertEventTemplate("Tâche ", "{{event.subject.id}}")).toBe("Tâche {{event.subject.id}}");
  });

  it("reconnaît les applications qui publient des événements", () => {
    expect(isTriggerApp("projets")).toBe(true);
    expect(isTriggerApp("cine")).toBe(false);
  });

  it("propose les champs de filtre du catalogue", () => {
    expect(filterFields(projets, ["projets.work_item.created"])).toEqual(["data.project_id", "subject.id", "subject.label", "type"]);
    expect(filterFields(null, [])).toEqual(["subject.id", "subject.label", "type"]);
  });

  it("construit un exemple qui passe les filtres d'égalité", () => {
    const now = new Date("2026-10-21T08:00:00Z");
    const ev = sampleEvent(projets, ["projets.work_item.status_changed"], [{ path: "data.to", op: "eq", value: "RESOLVED" }], now);
    expect(ev).toEqual({
      seq: 0,
      type: "projets.work_item.status_changed",
      at: "2026-10-21T08:00:00.000Z",
      subject: { kind: "work_item", id: "1", label: "Exemple" },
      data: { from: "IN_PROGRESS", to: "RESOLVED", project_id: "1" },
    });
    const listed = sampleEvent(projets, ["projets.work_item.created"], [
      { path: "data.to", op: "in", value: "CLOSED, RESOLVED" },
      { path: "subject.label", op: "eq", value: "Écrire la doc" },
    ]);
    expect(listed.data.to).toBe("CLOSED");
    expect(listed.subject.label).toBe("Écrire la doc");
    expect(sampleEvent(null, []).type).toBe("evenement");
  });

  it("relit un exemple modifié en JSON", () => {
    const ev = sampleEvent(projets, ["projets.work_item.status_changed"]);
    expect(parseSampleEvent(JSON.stringify(ev))).toEqual({ ok: true, event: ev });
    expect(parseSampleEvent("{").ok).toBe(false);
    expect(parseSampleEvent("[]").ok).toBe(false);
    expect(parseSampleEvent('{"type":"x"}').ok).toBe(false);
    expect(parseSampleEvent('{"type":"x","subject":{"kind":"a","id":"1","label":""},"data":[]}').ok).toBe(false);
    const minimal = parseSampleEvent('{"type":"x","subject":{"kind":"a","id":"1","label":""}}');
    expect(minimal.ok && minimal.event.data).toEqual({});
  });
});
