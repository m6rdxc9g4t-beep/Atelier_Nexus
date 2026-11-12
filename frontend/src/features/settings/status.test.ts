import { describe, expect, it } from "vitest";

import type { AppStatus, ProviderStatus, SettingsField, SettingsView } from "@/types/api";

import {
  LOCKED_NOTE,
  checkLines,
  countBySection,
  fieldNote,
  firstFieldWith,
  firstSectionWith,
  hasStatus,
  pendingLabel,
  providerDetail,
  sectionStatus,
  sections,
} from "./status";

const provider = (name: ProviderStatus["name"], configured: boolean, available: boolean, isDefault = false): ProviderStatus => ({
  name,
  configured,
  available,
  is_default: isDefault,
  is_fallback: false,
  default_model: name === "anthropic" ? "sonnet" : "qwen2.5",
  models: [],
  error: available ? null : "connexion refusée",
});

const app = (id: string, configured: boolean, available: boolean): AppStatus => ({
  id,
  label: `Atelier ${id}`,
  configured,
  available,
  base_url: configured ? "http://127.0.0.1:1" : null,
  detail: available ? "en marche" : null,
  error: configured && !available ? "injoignable" : null,
});

const field = (key: string, group: SettingsField["group"]): SettingsField => ({
  key,
  label: key,
  group,
  kind: "text",
  help: "",
  choices: [],
  value: "",
  configured: false,
  hint: null,
  source: "défaut",
});

const VIEW: SettingsView = {
  env_file: "backend/.env",
  fields: [
    field("APPROVAL_MODE", "Validation des actions"),
    field("OLLAMA_MODEL", "Modèles"),
    field("ANTHROPIC_MODEL", "Modèles"),
    field("PROJETS_BASE_URL", "Applications Atelier"),
    field("GITHUB_REPO", "GitHub"),
  ],
};

describe("rubriques des Réglages", () => {
  it("place Apparence avant les groupes du serveur", () => {
    expect(sections(["Validation des actions", "Modèles"])).toEqual(["Apparence", "Validation des actions", "Modèles"]);
  });

  it("donne l'état des moteurs, configurés ou non", () => {
    const check = { providers: [provider("anthropic", true, true, true), provider("ollama", false, false)], apps: [] };
    expect(checkLines("Modèles", check).map((l) => [l.label, l.ok, l.detail])).toEqual([
      ["Claude", true, "moteur par défaut, sonnet"],
      ["Ollama (local)", false, "non configuré"],
    ]);
    // Seul le moteur configuré compte pour la pastille
    expect(sectionStatus("Modèles", check, false)).toEqual({ status: "up", label: "Joignable" });
  });

  it("dit quand Claude passe par le jeton du forfait, sans changer les autres modes", () => {
    const claude = (extra: Partial<ProviderStatus>) => ({ ...provider("anthropic", true, true, true), ...extra });
    // Jeton du forfait fourni au serveur (CLAUDE_OAUTH_TOKEN) : le mode est dit, jamais le jeton
    expect(providerDetail(claude({ access: "token" }))).toBe("moteur par défaut, sonnet (forfait, par jeton)");
    expect(providerDetail(claude({ access: "token", is_default: false }))).toBe("sonnet (forfait, par jeton)");
    // Clé API, session « claude », serveur plus ancien (champ absent) : affichage d'avant
    for (const access of ["api", "cli", null, undefined] as const)
      expect(providerDetail(claude({ access }))).toBe("moteur par défaut, sonnet");
    // Jeton refusé ou limite atteinte : le message du serveur
    const refused = claude({ access: "token", available: false, error: "Le jeton du forfait Claude est refusé ou expiré." });
    expect(providerDetail(refused)).toBe("Le jeton du forfait Claude est refusé ou expiré.");
    // Jeton fourni mais programme « claude » absent du serveur : la raison, pas « non configuré »
    const missing = { ...provider("anthropic", false, false), access: "token" as const, error: "« claude » est absent de ce serveur." };
    expect(providerDetail(missing)).toBe("« claude » est absent de ce serveur.");
    expect(checkLines("Modèles", { providers: [missing], apps: [] })[0]).toMatchObject({ ok: false, down: false });
    // Sans jeton, un moteur non configuré reste « non configuré », quelle que soit son erreur
    expect(providerDetail({ ...provider("anthropic", false, false), access: "cli" })).toBe("non configuré");
  });

  it("garde l'avertissement du serveur sous un champ, même verrouillé", () => {
    const base = field("CLAUDE_MODE", "Modèles");
    const notice = "Sans effet sur ce serveur : Claude passe par le jeton du forfait.";
    // Sans avertissement : l'aide, ou la mention du verrou — comme avant
    expect(fieldNote({ ...base, help: "Aide." })).toBe("Aide.");
    expect(fieldNote({ ...base, help: "Aide.", source: "environnement" })).toBe(LOCKED_NOTE);
    expect(fieldNote({ ...base, help: "Aide.", notice: null })).toBe("Aide.");
    // Avec : il précède l'aide ou le verrou (cas du VPS : CLAUDE_MODE fixé par l'environnement)
    expect(fieldNote({ ...base, help: "Aide.", notice })).toBe(`${notice} Aide.`);
    expect(fieldNote({ ...base, help: "Aide.", source: "environnement", notice })).toBe(`${notice} ${LOCKED_NOTE}`);
    expect(fieldNote({ ...base, notice })).toBe(notice);
  });

  it("range Cuisine et GitHub à part, les autres apps dans Applications Atelier", () => {
    const check = {
      providers: [],
      apps: [app("projets", true, true), app("tab", true, false), app("cine", false, false), app("cuisine", true, true), app("github", true, false)],
    };
    expect(checkLines("Applications Atelier", check).map((l) => l.id)).toEqual(["projets", "tab"]);
    expect(sectionStatus("Applications Atelier", check, false)).toEqual({ status: "warning", label: "1 sur 2 joignable" });
    expect(sectionStatus("Atelier Cuisine", check, false)).toEqual({ status: "up", label: "Joignable" });
    expect(sectionStatus("GitHub", check, false)).toEqual({ status: "down", label: "Injoignable" });
  });

  it("pastille grise sans rien de configuré, en attente pendant la vérification, absente sans état", () => {
    const check = { providers: [], apps: [app("cine", false, false)] };
    expect(sectionStatus("Applications Atelier", check, false)).toEqual({ status: "off", label: "Non configuré" });
    expect(sectionStatus("GitHub", null, true)?.status).toBe("pending");
    expect(sectionStatus("Apparence", check, false)).toBeNull();
    expect(sectionStatus("Validation des actions", check, false)).toBeNull();
    expect(sectionStatus("Modèles", null, false)).toBeNull();
  });

  it("toutes les apps joignables : verte, accordée au pluriel", () => {
    const check = { providers: [], apps: [app("projets", true, true), app("tab", true, true)] };
    expect(sectionStatus("Applications Atelier", check, false)).toEqual({ status: "up", label: "2 sur 2 joignables" });
  });

  it("compte modifications et erreurs par rubrique et trouve la première concernée", () => {
    expect(countBySection(VIEW, ["OLLAMA_MODEL", "ANTHROPIC_MODEL", "GITHUB_REPO", "INCONNU"])).toEqual({
      Modèles: 2,
      GitHub: 1,
    });
    const order = sections(["Validation des actions", "Modèles", "Applications Atelier", "GitHub"]);
    expect(firstSectionWith(VIEW, order, ["GITHUB_REPO", "OLLAMA_MODEL"])).toBe("Modèles");
    expect(firstSectionWith(VIEW, order, [])).toBeNull();
    // Champ à focaliser : le premier de la rubrique, dans l'ordre du serveur
    expect(firstFieldWith(VIEW, "Modèles", ["ANTHROPIC_MODEL", "OLLAMA_MODEL"])).toBe("OLLAMA_MODEL");
    expect(firstFieldWith(VIEW, "GitHub", ["OLLAMA_MODEL"])).toBeNull();
  });

  it("seules les rubriques à joindre ont une pastille (et un bouton Vérifier)", () => {
    expect(sections(["Validation des actions", "Modèles", "Applications Atelier", "Atelier Cuisine", "GitHub"]).filter(hasStatus)).toEqual([
      "Modèles",
      "Applications Atelier",
      "Atelier Cuisine",
      "GitHub",
    ]);
  });

  it("annonce les modifications non enregistrées", () => {
    expect(pendingLabel(0)).toBe("");
    expect(pendingLabel(1)).toBe("1 modification non enregistrée");
    expect(pendingLabel(3)).toBe("3 modifications non enregistrées");
  });
});
