import { describe, expect, it } from "vitest";

import type { ToolsetInfo } from "@/types/api";

import { MAX_TOOLSETS, emptyForm, forcesLocal, missingToolsets, slugify, toPayload, validate } from "./form";

const toolset = (id: string, sensitive = false): ToolsetInfo => ({
  id,
  label: id,
  description: "",
  app: null,
  configured: true,
  sensitive,
  writes: false,
  tools: [],
});
const TOOLSETS = [toolset("core"), toolset("data_via"), toolset("tresorerie", true)];

describe("éditeur d'agents", () => {
  it("dérive un identifiant valide du nom affiché", () => {
    expect(slugify("Veille Réseaux & Co")).toBe("veille_reseaux_co");
    expect(slugify("2026 : bilan")).toBe("agent_2026_bilan");
  });

  it("valide les champs et refuse les noms réservés", () => {
    const form = { ...emptyForm(), name: "assistant", display_name: "A", system_prompt: "court" };
    const errors = validate(form, ["assistant"], false);
    expect(Object.keys(errors).sort()).toEqual(["description", "display_name", "name", "system_prompt"]);
    expect(validate(form, ["assistant"], true).name).toBeUndefined(); // identifiant figé en modification
  });

  it("une boîte sensible impose le modèle local et efface le moteur par défaut", () => {
    const form = {
      ...emptyForm(),
      toolsets: ["core", "tresorerie"],
      default_provider: "anthropic" as const,
      startersText: "Mon budget ?\n\n  Mes dépenses ?  ",
    };
    expect(forcesLocal(form, TOOLSETS)).toBe(true);
    const payload = toPayload(form, TOOLSETS);
    expect(payload.privacy).toBe("local_only");
    expect(payload.default_provider).toBeNull();
    expect(payload.starters).toEqual(["Mon budget ?", "Mes dépenses ?"]);
  });

  it("isole les boîtes absentes du catalogue (extension retirée) et les garde à l'envoi", () => {
    const form = { ...emptyForm(), toolsets: ["core", "data_via", "extension_x", "extension_x", "tresorerie"] };
    expect(missingToolsets(form.toolsets, TOOLSETS)).toEqual(["extension_x"]);
    expect(missingToolsets(["core", "data_via"], TOOLSETS)).toEqual([]);
    // Ni retirée ni rendue sensible à l'insu de l'utilisateur : elle part telle quelle
    expect(toPayload(form, TOOLSETS).toolsets).toContain("extension_x");
  });

  it("limite le nombre de boîtes à outils, Essentiels compris", () => {
    const base = { ...emptyForm(), display_name: "Veille", description: "Résume la veille.", system_prompt: "Tu résumes la veille chaque lundi." };
    const ids = (n: number) => ["core", ...Array.from({ length: n - 1 }, (_, i) => `boite_${i}`)];
    expect(validate({ ...base, toolsets: ids(MAX_TOOLSETS) }, [], true).toolsets).toBeUndefined();
    expect(validate({ ...base, toolsets: ids(MAX_TOOLSETS + 1) }, [], true).toolsets).toMatch(/au plus/);
  });
});
