import { describe, expect, it } from "vitest";

import { stable } from "./stable";

describe("stable", () => {
  const apps = [{ id: "viz", available: true, error: null as string | null }];

  it("garde la référence précédente quand la relecture rend les mêmes données", () => {
    const reread = [{ id: "viz", available: true, error: null }];
    expect(stable(apps, reread)).toBe(apps);
  });

  it("prend les nouvelles données dès qu'une valeur change", () => {
    const down = [{ id: "viz", available: false, error: "Atelier Viz est-il lancé ?" }];
    expect(stable(apps, down)).toBe(down);
    const more = [...apps, { id: "tab", available: true, error: null }];
    expect(stable(apps, more)).toBe(more);
  });

  it("première lecture : une liste vide reste la même liste vide", () => {
    const empty: unknown[] = [];
    expect(stable(empty, [])).toBe(empty);
  });
});
