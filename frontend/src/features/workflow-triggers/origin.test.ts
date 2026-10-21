import { describe, expect, it } from "vitest";

import { runFixture } from "@/features/workflows-graph/fixtures";

import { badgeText, inboxLabel, inboxOrder, originLabel, originText } from "./origin";

const event = {
  app: "projets",
  seq: 42,
  type: "projets.work_item.status_changed",
  at: "2026-10-21T21:30:00+02:00",
  subject: { kind: "work_item", id: "123", label: "Écrire la doc" },
};

describe("origine d'une exécution", () => {
  it("donne l'étiquette de chaque origine", () => {
    expect(originLabel("manual")).toBe("Manuel");
    expect(originLabel("schedule")).toBe("Horaire");
    expect(originLabel("event")).toBe("Événement");
    expect(originLabel("test")).toBe("Test");
    expect(originLabel(undefined)).toBe("Manuel");
    expect(originLabel("webhook")).toBe("webhook");
  });

  it("écrit la phrase d'origine avec l'événement source", () => {
    expect(originText(runFixture({ trigger: "event", trigger_event: event }))).toBe(
      "Déclenché par projets.work_item.status_changed · Écrire la doc",
    );
    expect(originText(runFixture({ trigger: "event", trigger_event: { ...event, subject: { ...event.subject, label: "" } } }))).toBe(
      "Déclenché par projets.work_item.status_changed · 123",
    );
    expect(originText(runFixture({ trigger: "schedule" }))).toBe("Déclenché par l'horaire");
    expect(originText(runFixture({ trigger: "test", trigger_event: event }))).toMatch(/^Test du déclencheur avec/);
    expect(originText(runFixture({ trigger: "test" }))).toBe("Test du déclencheur");
    expect(originText(runFixture())).toBe("Lancé à la main");
  });
});

describe("boîte « À valider »", () => {
  it("formate le badge et son libellé", () => {
    expect(badgeText(3)).toBe("3");
    expect(badgeText(120)).toBe("99+");
    expect(inboxLabel(0)).toBe("À valider : rien en attente");
    expect(inboxLabel(1)).toBe("À valider : 1 exécution en attente de votre validation");
    expect(inboxLabel(2)).toMatch(/2 exécutions/);
  });

  it("ne garde que les exécutions en attente, récentes d'abord", () => {
    const runs = [
      runFixture({ id: "a", status: "awaiting_approval", updated_at: "2026-10-21T10:00:00Z" }),
      runFixture({ id: "b", status: "completed", updated_at: "2026-10-21T12:00:00Z" }),
      runFixture({ id: "c", status: "awaiting_approval", updated_at: "2026-10-21T11:00:00Z" }),
    ];
    expect(inboxOrder(runs).map((r) => r.id)).toEqual(["c", "a"]);
  });
});
