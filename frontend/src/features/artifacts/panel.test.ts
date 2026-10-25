import { describe, expect, it } from "vitest";

import {
  artifactScope,
  artifactSubtitle,
  artifactTime,
  downloadName,
  exportPayload,
  firstInScope,
  inScope,
  kindFamily,
  notesTitle,
  positionOf,
  rowCount,
  scopeCounts,
  selectionAfterRemoval,
  selectionForScope,
  showsAsCode,
} from "./panel";
import { parsePreview } from "./preview";

// Ordre du store : le plus récent en tête
const items = [
  { id: "w2", agent: "workflow:wf_ventes" },
  { id: "c2", agent: "data_analyst" },
  { id: "w1", agent: "workflow:wf_ventes" },
  { id: "c1", agent: "assistant" },
];

describe("provenance des livrables", () => {
  it("distingue les exécutions de workflow (agent « workflow: ») des conversations", () => {
    expect(artifactScope({ agent: "workflow:wf_1" })).toBe("workflow");
    expect(artifactScope({ agent: "data_analyst" })).toBe("conversation");
    // Un agent dont le nom contient « workflow » reste une conversation
    expect(artifactScope({ agent: "expert_workflow" })).toBe("conversation");
  });

  it("compte et filtre par provenance en gardant l'ordre", () => {
    expect(scopeCounts(items)).toEqual({ conversation: 2, workflow: 2 });
    expect(scopeCounts([])).toEqual({ conversation: 0, workflow: 0 });
    expect(inScope(items, "workflow").map((a) => a.id)).toEqual(["w2", "w1"]);
    expect(inScope(items, "conversation").map((a) => a.id)).toEqual(["c2", "c1"]);
  });

  it("choisir une provenance montre son livrable le plus récent", () => {
    expect(firstInScope(items, "conversation")).toBe("c2");
    expect(firstInScope(items, "workflow")).toBe("w2");
    expect(firstInScope(items.slice(1, 2), "workflow")).toBeNull();
  });

  it("recliquer la provenance affichée ne quitte pas le livrable en cours", () => {
    expect(selectionForScope(items, "conversation", "workflow")).toBe("w2");
    expect(selectionForScope(items, "workflow", "conversation")).toBe("c2");
    expect(selectionForScope(items, "conversation", "conversation")).toBeNull();
    expect(selectionForScope(items.slice(1, 2), "conversation", "workflow")).toBeNull();
  });
});

describe("position et voisins", () => {
  const list = inScope(items, "conversation");

  it("donne le rang et les voisins dans l'ordre de la liste", () => {
    expect(positionOf(list, "c2")).toEqual({ index: 1, total: 2, previous: null, next: "c1" });
    expect(positionOf(list, "c1")).toEqual({ index: 2, total: 2, previous: "c2", next: null });
  });

  it("un livrable absent n'a ni rang ni voisins", () => {
    expect(positionOf(list, "w1")).toEqual({ index: 0, total: 2, previous: null, next: null });
    expect(positionOf([], null)).toEqual({ index: 0, total: 0, previous: null, next: null });
  });

  it("après un retrait, montre le suivant, sinon le précédent, sinon rien", () => {
    const three = [{ id: "a" }, { id: "b" }, { id: "c" }];
    expect(selectionAfterRemoval(three, "a")).toBe("b");
    expect(selectionAfterRemoval(three, "b")).toBe("c");
    expect(selectionAfterRemoval(three, "c")).toBe("b");
    expect(selectionAfterRemoval([{ id: "a" }], "a")).toBeNull();
  });
});

describe("présentation", () => {
  it("range chaque type dans une famille d'icône", () => {
    expect(kindFamily("data_preview")).toBe("data");
    expect(kindFamily("markdown")).toBe("document");
    expect(kindFamily("json")).toBe("json");
    expect(["sql", "dax", "powerquery", "python", "react", "code"].map((k) => kindFamily(k as "sql"))).toEqual(
      Array(6).fill("code"),
    );
  });

  it("affiche en code tout ce qui n'est ni document ni aperçu de données lisible", () => {
    const table = parsePreview(JSON.stringify({ columns: [{ key: "a", type: "number" }], rows: [[1]] }));
    expect(showsAsCode("sql", null)).toBe(true);
    expect(showsAsCode("json", null)).toBe(true);
    expect(showsAsCode("markdown", null)).toBe(false);
    expect(showsAsCode("data_preview", table)).toBe(false);
    // Aperçu illisible : montré tel quel, en code
    expect(showsAsCode("data_preview", null)).toBe(true);
  });

  it("titre les notes d'intégration selon le type et leur contenu", () => {
    expect(notesTitle("dax", "Créer la mesure")).toBe("Intégrer dans Power BI");
    expect(notesTitle("powerquery", "")).toBe("Intégrer dans Power BI");
    expect(notesTitle("sql", "Coller dans Power BI Desktop")).toBe("Intégrer dans Power BI");
    expect(notesTitle("python", "Lancer le script")).toBe("Notes d'intégration");
  });

  it("propose un nom de fichier sans accents ni ponctuation", () => {
    expect(downloadName("Ventes par région (2024)", "sql")).toBe("ventes-par-region-2024.sql");
    expect(downloadName("Marge — Île-de-France", "dax")).toBe("marge-ile-de-france.dax");
    expect(downloadName("!!!", "data_preview")).toBe("artefact.csv");
    expect(downloadName("Notes", "markdown")).toBe("notes.md");
  });

  it("exporte un aperçu de données en CSV et le reste tel quel", () => {
    const content = JSON.stringify({ columns: [{ key: "ca", type: "number" }], rows: [[1.5]] });
    expect(exportPayload(content, parsePreview(content))).toEqual({ text: "ca\n1,5", type: "text/csv" });
    const schema = JSON.stringify({ columns: [{ name: "ca", type: "number" }], sample: [{ ca: 2 }] });
    expect(exportPayload(schema, parsePreview(schema))).toEqual({ text: "ca\n2", type: "text/csv" });
    const noSample = JSON.stringify({ columns: [{ name: "ca", type: "number" }] });
    expect(exportPayload(noSample, parsePreview(noSample))).toEqual({ text: noSample, type: "text/plain" });
    expect(exportPayload("SELECT 1", null)).toEqual({ text: "SELECT 1", type: "text/plain" });
  });

  it("date un livrable : l'heure le jour même, le jour avant, l'année si elle diffère", () => {
    const now = new Date(2026, 9, 25, 18, 0);
    expect(artifactTime(new Date(2026, 9, 25, 14, 5).getTime(), now)).toBe("14:05");
    expect(artifactTime(new Date(2026, 9, 12, 9, 30).getTime(), now)).toMatch(/^12 oct\., 09:30$/);
    expect(artifactTime(new Date(2025, 9, 12, 9, 30).getTime(), now)).toMatch(/^12 oct\. 2025, 09:30$/);
    expect(artifactTime(Number.NaN, now)).toBe("");
  });

  it("sous-titre de l'en-tête : type et heure, sans séparateur orphelin", () => {
    const now = new Date(2026, 9, 25, 18, 0);
    expect(artifactSubtitle("dax", new Date(2026, 9, 25, 14, 5).getTime(), now)).toBe("DAX · 14:05");
    expect(artifactSubtitle("data_preview", Number.NaN, now)).toBe("Données");
  });

  it("compte les lignes d'un aperçu", () => {
    expect(rowCount(0)).toBe("0 ligne");
    expect(rowCount(1)).toBe("1 ligne");
    expect(rowCount(12)).toBe("12 lignes");
  });
});
