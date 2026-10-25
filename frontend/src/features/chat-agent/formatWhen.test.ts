import { describe, expect, it } from "vitest";

import { formatWhen, formatWhenIn, groupByDay } from "./formatWhen";

const now = new Date(2026, 9, 25, 15, 0);
const at = (day: number, hour = 10) => new Date(2026, 9, day, hour, 5).toISOString();

describe("formatWhen", () => {
  it("dit aujourd'hui, hier, puis la date", () => {
    expect(formatWhen(at(25), now)).toMatch(/^Aujourd'hui, 10:05$/);
    expect(formatWhen(at(24), now)).toMatch(/^Hier, 10:05$/);
    expect(formatWhen(at(12), now)).toBe("12 oct.");
    expect(formatWhen("pas une date", now)).toBe("");
  });
});

describe("groupByDay", () => {
  it("range les conversations par jour en gardant leur ordre, sans groupe vide", () => {
    const items = [
      { id: "a", updated_at: at(25, 14) },
      { id: "b", updated_at: at(25, 9) },
      { id: "c", updated_at: at(23) },
      { id: "d", updated_at: "illisible" },
    ];
    const groups = groupByDay(items, now);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ["Aujourd'hui", ["a", "b"]],
      ["Plus ancien", ["c", "d"]],
    ]);
    expect(groupByDay([{ updated_at: at(24, 23) }], now)[0]!.label).toBe("Hier");
    expect(groupByDay([], now)).toEqual([]);
  });
});

describe("formatWhenIn", () => {
  it("ne répète pas le jour du titre du groupe", () => {
    expect(formatWhenIn(at(25), "Aujourd'hui", now)).toBe("10:05");
    expect(formatWhenIn(at(24), "Hier", now)).toBe("10:05");
    expect(formatWhenIn(at(12), "Plus ancien", now)).toBe("12 oct.");
    expect(formatWhenIn("illisible", "Aujourd'hui", now)).toBe("");
  });
});
