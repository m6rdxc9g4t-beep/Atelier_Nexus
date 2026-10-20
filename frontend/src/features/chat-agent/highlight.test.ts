import { describe, expect, it } from "vitest";

import { highlight, searchTerms } from "./highlight";

describe("highlight", () => {
  it("ignore accents et casse, garde le texte d'origine", () => {
    expect(highlight("La réunion d'Équipe", "REUNION equipe")).toEqual([
      { text: "La ", match: false },
      { text: "réunion", match: true },
      { text: " d'", match: false },
      { text: "Équipe", match: true },
    ]);
  });

  it("marque toutes les occurrences, mots courts ignorés", () => {
    const segs = highlight("dax et DAX", "dax a");
    expect(segs.filter((s) => s.match).map((s) => s.text)).toEqual(["dax", "DAX"]);
    expect(searchTerms(" a  Été été ")).toEqual(["ete"]);
  });

  it("sans mot recherché : un seul segment", () => {
    expect(highlight("Bonjour", "")).toEqual([{ text: "Bonjour", match: false }]);
    expect(highlight("", "x y")).toEqual([]);
  });
});
