import { describe, expect, it } from "vitest";

import type { SettingsField, SettingsView } from "@/types/api";

import { GROUP_NOTES, byGroup, changes, initialDraft } from "./form";

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: "K",
  label: "K",
  group: "Modèles",
  kind: "text",
  help: "",
  choices: [],
  value: "",
  configured: false,
  hint: null,
  source: "défaut",
  ...over,
});

const view: SettingsView = {
  env_file: "/x/.env",
  fields: [
    f({ key: "ANTHROPIC_API_KEY", kind: "secret", value: null, configured: true, hint: "…1234" }),
    f({ key: "OLLAMA_MODEL", value: "llama3.1:8b" }),
    f({ key: "GITHUB_REPO", group: "GitHub", value: "moi/repo", source: "fichier" }),
    f({ key: "OLLAMA_BASE_URL", kind: "url", value: "http://localhost:11434", source: "environnement" }),
  ],
};

describe("réglages", () => {
  it("le brouillon ne contient jamais de secret", () => {
    const draft = initialDraft(view);
    expect(draft.ANTHROPIC_API_KEY).toEqual({ value: "", clear: false });
    expect(draft.OLLAMA_MODEL!.value).toBe("llama3.1:8b");
  });

  it("n'envoie que ce qui change", () => {
    const draft = initialDraft(view);
    expect(changes(view, draft)).toEqual({});
    draft.OLLAMA_MODEL!.value = " gemma3:12b ";
    draft.GITHUB_REPO!.value = "";
    draft.ANTHROPIC_API_KEY!.value = "sk-ant-nouvelle";
    draft.OLLAMA_BASE_URL!.value = "http://ailleurs:11434"; // fixé par l'environnement : ignoré
    expect(changes(view, draft)).toEqual({
      ANTHROPIC_API_KEY: "sk-ant-nouvelle",
      OLLAMA_MODEL: "gemma3:12b",
      GITHUB_REPO: null,
    });
  });

  it("effacer un secret configuré", () => {
    const draft = initialDraft(view);
    draft.ANTHROPIC_API_KEY!.clear = true;
    expect(changes(view, draft)).toEqual({ ANTHROPIC_API_KEY: null });
  });

  it("regroupe dans l'ordre", () => {
    expect(byGroup(view).map(([g, fields]) => [g, fields.length])).toEqual([
      ["Modèles", 3],
      ["GitHub", 1],
    ]);
  });

  it("Atelier Cuisine : groupe entre les apps et GitHub, mot de passe jamais renvoyé", () => {
    const cuisine: SettingsView = {
      env_file: "/x/.env",
      fields: [
        f({ key: "GITHUB_REPO", group: "GitHub" }),
        f({ key: "CUISINE_SUPABASE_URL", group: "Atelier Cuisine", kind: "url", value: "https://p.supabase.co" }),
        f({ key: "CUISINE_PASSWORD", group: "Atelier Cuisine", kind: "secret", value: null, configured: true }),
        f({ key: "CINE_BASE_URL", group: "Applications Atelier", kind: "url" }),
      ],
    };
    expect(byGroup(cuisine).map(([g]) => g)).toEqual(["Applications Atelier", "Atelier Cuisine", "GitHub"]);
    const draft = initialDraft(cuisine);
    expect(draft.CUISINE_PASSWORD).toEqual({ value: "", clear: false });
    draft.CUISINE_PASSWORD!.value = "nouveau";
    expect(changes(cuisine, draft)).toEqual({ CUISINE_PASSWORD: "nouveau" });
    expect(GROUP_NOTES["Atelier Cuisine"]).toContain("lecture seule");
  });
});
