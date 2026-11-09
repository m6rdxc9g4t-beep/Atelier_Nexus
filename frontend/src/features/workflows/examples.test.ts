import { describe, expect, it } from "vitest";

import type { ExampleStory } from "@/types/api";

import { pickStory, stepsAround } from "./examples";

const story = (id: string): ExampleStory => ({
  id,
  titre: id,
  sous_titre: "",
  secteur: "",
  resume: "",
  workflows: [],
  parcours: ["convert", "tab", "viz", "tresorerie", "nexus", "projets", "wiki"].map((app) => ({
    app,
    titre: app,
    texte: `Dans ${app}`,
  })),
});

describe("exemples de la suite", () => {
  it("retient l'histoire mémorisée, sinon la première", () => {
    const list = [story("a"), story("b")];
    expect(pickStory(list, "b")?.id).toBe("b");
    expect(pickStory(list, "disparue")?.id).toBe("a");
    expect(pickStory([], "a")).toBeUndefined();
  });

  it("situe Nexus dans le parcours et donne l'application suivante", () => {
    const { current, next } = stepsAround(story("a"));
    expect(current?.app).toBe("nexus");
    expect(next?.app).toBe("projets");
    expect(stepsAround(story("a"), "wiki").next).toBeUndefined();
    expect(stepsAround({ ...story("a"), parcours: [] })).toEqual({});
  });
});
