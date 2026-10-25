import { describe, expect, it } from "vitest";

import { headerContext, humanizeAgent } from "./headerContext";

const AGENTS = [
  { name: "data_analyst", display_name: "Data Analyst", icon: "chart-column", local_only: false },
  { name: "finance", display_name: "Finance", icon: "landmark", local_only: true },
];

describe("barre des petits écrans", () => {
  it("affiche l'accueil sur la vue d'accueil, quel que soit l'agent", () => {
    expect(headerContext("home", "finance", AGENTS)).toEqual({ kind: "home", label: "Accueil", icon: null, localOnly: false });
  });

  it("affiche le nom, l'icône et le verrou local de l'agent courant", () => {
    expect(headerContext("agents", "finance", AGENTS)).toEqual({
      kind: "agent",
      label: "Finance",
      icon: "landmark",
      localOnly: true,
    });
  });

  it("le Studio des workflows ouvert l'emporte sur la vue", () => {
    expect(headerContext("agents", "finance", AGENTS, "map")).toMatchObject({ kind: "map", label: "Carte de la suite" });
    expect(headerContext("home", "finance", AGENTS, "inbox")).toMatchObject({ kind: "inbox", label: "À valider" });
    expect(headerContext("home", "finance", AGENTS, null).kind).toBe("home");
  });

  it("garde un nom lisible avant le chargement du catalogue", () => {
    expect(headerContext("agents", "data_analyst", [])).toMatchObject({ label: "Data analyst", icon: null });
    expect(humanizeAgent("veille-reseaux")).toBe("Veille reseaux");
    expect(humanizeAgent("")).toBe("Agent");
  });
});
