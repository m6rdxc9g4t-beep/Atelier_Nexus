import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

describe("état des moteurs et des applications", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("ne demande une relecture au serveur que sur demande explicite", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", async (url: string | URL) => {
      paths.push(String(url).replace(/^.*?\/api\//, "/api/"));
      return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
    });
    // Rafraîchissement périodique : servi par le cache du serveur (60 s, 25 s, 10 min)
    await api.providers();
    await api.appsStatus();
    // « Réessayer », réglages enregistrés : état relu
    await api.providers(undefined, true);
    await api.appsStatus(undefined, true);
    expect(paths).toEqual([
      "/api/llm/providers",
      "/api/apps/status",
      "/api/llm/providers?refresh=true",
      "/api/apps/status?refresh=true",
    ]);
  });
});
