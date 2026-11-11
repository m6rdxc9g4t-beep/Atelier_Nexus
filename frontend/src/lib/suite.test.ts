import { afterEach, describe, expect, it, vi } from "vitest";

import { ONLINE_LABEL, checkHealth, suiteApps } from "./suite";

afterEach(() => vi.unstubAllEnvs());

describe("sélecteur « Suite Atelier »", () => {
  it("liste les onze applications, Nexus en tête", () => {
    expect(suiteApps().map((a) => a.id)).toEqual([
      "nexus",
      "viz",
      "tab",
      "projets",
      "convert",
      "wiki",
      "formulaire",
      "tresorerie",
      "cine",
      "savoir",
      "cuisine",
    ]);
  });

  it("Wiki et Formulaire, que Nexus orchestre, sont sondés sur leur API (3200 et 3300)", () => {
    expect(suiteApps().find((a) => a.id === "wiki")).toMatchObject({
      name: "Atelier Wiki",
      short: "Wiki",
      url: "http://127.0.0.1:3200",
      healthUrl: "http://127.0.0.1:3200/api/health",
    });
    expect(suiteApps().find((a) => a.id === "formulaire")).toMatchObject({
      name: "Atelier Formulaire",
      short: "Formulaire",
      url: "http://127.0.0.1:3300",
      healthUrl: "http://127.0.0.1:3300/api/health",
    });
  });

  it("les adresses de Wiki et Formulaire se surchargent (sans barre finale)", () => {
    vi.stubEnv("NEXT_PUBLIC_ATELIER_WIKI_URL", " https://wiki.example.org/ ");
    vi.stubEnv("NEXT_PUBLIC_ATELIER_FORMULAIRE_URL", "https://formulaire.example.org//");
    const wiki = suiteApps().find((a) => a.id === "wiki");
    expect(wiki?.url).toBe("https://wiki.example.org");
    expect(wiki?.healthUrl).toBe("https://wiki.example.org/api/health");
    expect(suiteApps().find((a) => a.id === "formulaire")?.url).toBe("https://formulaire.example.org");
  });

  it("Atelier Cuisine est une app en ligne, jamais sondée", () => {
    const cuisine = suiteApps().find((a) => a.id === "cuisine");
    expect(cuisine).toMatchObject({
      name: "Atelier Cuisine",
      short: "Cuisine",
      description: "Stock, repas, courses et budget du foyer",
      url: "https://atelier-cuisine-iota.vercel.app",
      healthUrl: null,
      online: true,
    });
    expect(ONLINE_LABEL).toBe("en ligne");
    // Les applications locales restent sondées
    expect(suiteApps().filter((a) => a.online).map((a) => a.id)).toEqual(["cuisine"]);
  });

  it("l'adresse de Cuisine se surcharge (sans barre finale)", () => {
    vi.stubEnv("NEXT_PUBLIC_ATELIER_CUISINE_URL", " https://cuisine.example.org/ ");
    expect(suiteApps().find((a) => a.id === "cuisine")?.url).toBe("https://cuisine.example.org");
  });

  it("Atelier Convert est une app locale sondée sur son API (8010)", () => {
    const convert = suiteApps().find((a) => a.id === "convert");
    expect(convert).toMatchObject({
      name: "Atelier Convert",
      short: "Convert",
      description: "Relevés et fichiers en tables",
      url: "http://127.0.0.1:8010",
      healthUrl: "http://127.0.0.1:8010/api/health",
    });
    expect(convert?.online).toBeFalsy();
  });

  it("l'adresse de Convert se surcharge (sans barre finale)", () => {
    vi.stubEnv("NEXT_PUBLIC_ATELIER_CONVERT_URL", " http://127.0.0.1:8011/ ");
    const convert = suiteApps().find((a) => a.id === "convert");
    expect(convert?.url).toBe("http://127.0.0.1:8011");
    expect(convert?.healthUrl).toBe("http://127.0.0.1:8011/api/health");
  });

  it("checkHealth ne lève jamais", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(checkHealth("http://127.0.0.1:1/api/health", 50, down)).resolves.toBe("down");
    const up = vi.fn(async () => new Response(null));
    await expect(checkHealth("http://127.0.0.1:8000/api/health", 50, up)).resolves.toBe("up");
  });
});
