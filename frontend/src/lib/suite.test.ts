import { afterEach, describe, expect, it, vi } from "vitest";

import { ONLINE_LABEL, checkHealth, suiteApps } from "./suite";

afterEach(() => vi.unstubAllEnvs());

describe("sélecteur « Suite Atelier »", () => {
  it("liste les dix applications, Nexus en tête", () => {
    expect(suiteApps().map((a) => a.id)).toEqual([
      "nexus",
      "viz",
      "tab",
      "projets",
      "wiki",
      "formulaire",
      "tresorerie",
      "cine",
      "savoir",
      "cuisine",
    ]);
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

  it("checkHealth ne lève jamais", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(checkHealth("http://127.0.0.1:1/api/health", 50, down)).resolves.toBe("down");
    const up = vi.fn(async () => new Response(null));
    await expect(checkHealth("http://127.0.0.1:8000/api/health", 50, up)).resolves.toBe("up");
  });
});
