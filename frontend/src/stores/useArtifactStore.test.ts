import { beforeEach, describe, expect, it } from "vitest";

import type { Artifact } from "@/types/api";

import { selectSelectedArtifact, useArtifactStore } from "./useArtifactStore";

const sample = (title: string): Artifact => ({
  kind: "sql",
  title,
  content: "SELECT 1",
  language: "sql",
  metadata: {},
});

describe("useArtifactStore", () => {
  beforeEach(() => useArtifactStore.getState().clear());

  it("ajoute en tête, sélectionne et ouvre le panneau", () => {
    const { add } = useArtifactStore.getState();
    add(sample("A"), "assistant");
    const b = add(sample("B"), "data_analyst");
    const state = useArtifactStore.getState();
    expect(state.artifacts.map((a) => a.title)).toEqual(["B", "A"]);
    expect(selectSelectedArtifact(state)?.id).toBe(b.id);
    expect(state.panelOpen).toBe(true);
  });

  it("sans ouverture demandée, garde le panneau fermé (petit écran)", () => {
    useArtifactStore.getState().add(sample("A"), "x", false);
    const state = useArtifactStore.getState();
    expect(state.panelOpen).toBe(false);
    expect(state.artifacts).toHaveLength(1);
  });

  it("à la suppression de l'artefact sélectionné, sélectionne le suivant puis ferme quand c'est vide", () => {
    const { add, remove } = useArtifactStore.getState();
    const a = add(sample("A"), "x");
    const b = add(sample("B"), "x");
    remove(b.id);
    expect(useArtifactStore.getState().selectedId).toBe(a.id);
    remove(a.id);
    const state = useArtifactStore.getState();
    expect(state.selectedId).toBeNull();
    expect(state.panelOpen).toBe(false);
  });

  it("remplace les artefacts d'un seul agent quand on change de conversation", () => {
    const { add, replaceForAgent } = useArtifactStore.getState();
    add(sample("Autre agent"), "data_analyst");
    const old = add(sample("Ancien"), "assistant");
    replaceForAgent("assistant", [
      { ...sample("Rouvert"), id: "srv_1", agent: "assistant", createdAt: 1 },
    ]);
    const state = useArtifactStore.getState();
    expect(state.artifacts.map((a) => a.title)).toEqual(["Rouvert", "Autre agent"]);
    expect(state.artifacts.some((a) => a.id === old.id)).toBe(false);
    expect(state.selectedId).toBe("srv_1");
  });
});
