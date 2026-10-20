import { describe, expect, it } from "vitest";

import type { ToolsetInfo } from "@/types/api";

import { emptyForm, forcesLocal, slugify, toPayload, validate } from "./form";

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
});
