import { afterEach, describe, expect, it, vi } from "vitest";

import { isDesktop, openExternal, saveFile, textToBase64 } from "./desktop";

afterEach(() => vi.unstubAllGlobals());

describe("pont de l'application de bureau", () => {
  it("encode le texte en UTF-8", () => {
    expect(atob(textToBase64("Coût TTC €"))).toBe(
      String.fromCharCode(...new TextEncoder().encode("Coût TTC €")),
    );
  });

  it("passe par pywebview quand il est présent", async () => {
    const save_file = vi.fn(async () => ({ saved: "/Users/f/Downloads/mesure.dax" }));
    const open_external = vi.fn(async () => true);
    vi.stubGlobal("window", { pywebview: { api: { save_file, open_external } } });
    expect(isDesktop()).toBe(true);
    await expect(saveFile("mesure.dax", "CA = 1", "text/plain")).resolves.toEqual({
      kind: "saved",
      path: "/Users/f/Downloads/mesure.dax",
    });
    expect(save_file).toHaveBeenCalledWith("mesure.dax", textToBase64("CA = 1"));
    openExternal("http://127.0.0.1:8000");
    expect(open_external).toHaveBeenCalledWith("http://127.0.0.1:8000");
  });

  it("annulation et erreur de la boîte native", async () => {
    const api = { save_file: vi.fn(async () => ({ saved: null })), open_external: vi.fn() };
    vi.stubGlobal("window", { pywebview: { api } });
    await expect(saveFile("a.txt", "x", "text/plain")).resolves.toEqual({ kind: "cancelled" });
    api.save_file.mockResolvedValueOnce({ saved: null, error: "Écriture impossible" } as never);
    await expect(saveFile("a.txt", "x", "text/plain")).rejects.toThrow("Écriture impossible");
  });

  it("sans pont : window.open", () => {
    const open = vi.fn();
    vi.stubGlobal("window", { open });
    expect(isDesktop()).toBe(false);
    openExternal("https://example.org");
    expect(open).toHaveBeenCalledWith("https://example.org", "_blank", "noopener,noreferrer");
  });
});
