import { describe, expect, it } from "vitest";

import { runFixture } from "./fixtures";
import { duration, launchValues, newArtifacts, pollDelay, shouldPoll } from "./run";

describe("suivi d'une exécution", () => {
  it("interroge tant que le moteur avance", () => {
    expect(shouldPoll(runFixture())).toBe(true);
    expect(shouldPoll(runFixture({ status: "awaiting_approval" }))).toBe(false);
    expect(shouldPoll(runFixture({ status: "completed" }))).toBe(false);
    expect(shouldPoll(null)).toBe(false);
    expect(pollDelay(0)).toBe(500);
    expect(pollDelay(100)).toBe(3000);
  });

  it("n'envoie chaque livrable qu'une fois au panneau Artefacts", () => {
    const seen = new Set<string>();
    const artifact = { kind: "markdown" as const, title: "Bilan", content: "#", language: null, metadata: {} };
    const run = runFixture({ artifacts: [artifact] });
    expect(newArtifacts(run, seen)).toHaveLength(1);
    expect(newArtifacts(run, seen)).toHaveLength(0);
    expect(newArtifacts(runFixture({ artifacts: [artifact, { ...artifact, title: "Autre" }] }), seen)).toHaveLength(1);
    expect(newArtifacts(runFixture({ id: "run_2", artifacts: [artifact] }), seen)).toHaveLength(1);
  });

  it("formate les durées et prépare les valeurs de lancement", () => {
    expect(duration("2026-10-21T10:00:00Z", "2026-10-21T10:00:00.250Z")).toBe("250 ms");
    expect(duration("2026-10-21T10:00:00Z", "2026-10-21T10:00:01.5Z")).toBe("1,5 s");
    expect(duration("2026-10-21T10:00:00Z", "2026-10-21T10:02:05Z")).toBe("2 min 5 s");
    expect(duration(null, "2026-10-21T10:00:00Z")).toBeNull();
    expect(launchValues([{ name: "a", default: "1" }, { name: "b", default: "" }], { b: "x", c: "y" })).toEqual({ a: "1", b: "x" });
  });
});
