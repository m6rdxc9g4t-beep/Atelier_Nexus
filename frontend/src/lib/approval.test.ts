import { describe, expect, it } from "vitest";

import type { SettingsField, SettingsView } from "@/types/api";

import {
  APPROVAL_CHOICES,
  CALL_KIND_LABEL,
  approvalModeOf,
  approvalPromise,
  callKind,
  decisionText,
  inboxTexts,
  triggerReminder,
} from "./approval";

const view = (value: string | null, extra: Partial<SettingsField> = {}): SettingsView => ({
  env_file: "/x/.env",
  fields: [
    {
      key: "APPROVAL_MODE",
      label: "Actions à valider",
      group: "Validation des actions",
      kind: "choice",
      help: "",
      choices: ["every_step", "writes_only"],
      value,
      configured: value !== null,
      hint: null,
      source: "défaut",
      ...extra,
    },
  ],
});

describe("validation des actions", () => {
  it("lit le réglage, chaque action par défaut et en cas de doute", () => {
    expect(approvalModeOf(view("every_step"))).toBe("every_step");
    expect(approvalModeOf(view("writes_only", { source: "fichier" }))).toBe("writes_only");
    expect(approvalModeOf(view(""))).toBe("every_step");
    expect(approvalModeOf(view("inconnu"))).toBe("every_step");
    expect(approvalModeOf({ env_file: "", fields: [] })).toBe("every_step");
    expect(approvalModeOf(null)).toBe("every_step");
  });

  it("nomme les choix comme demandé", () => {
    expect(APPROVAL_CHOICES.every_step.label).toBe("Chaque action (recommandé)");
    expect(APPROVAL_CHOICES.writes_only.label).toBe("Seulement les écritures");
  });

  it("étiquette les appels ; un ancien tour sans nature était une écriture", () => {
    expect(CALL_KIND_LABEL[callKind("read")]).toBe("Lecture");
    expect(CALL_KIND_LABEL[callKind("delegation")]).toBe("Délégation");
    expect(callKind(undefined)).toBe("write");
  });

  it("adapte les textes des déclencheurs et de « À valider » au réglage", () => {
    expect(triggerReminder("every_step")).toEqual({
      lead: "Chaque étape attendra votre validation dans",
      tail: " : rien ne s'exécute sans vous.",
    });
    expect(triggerReminder("writes_only").lead).toBe("Les étapes qui écrivent attendront votre validation dans");
    expect(inboxTexts("every_step").description).toContain("avant chaque étape");
    expect(inboxTexts("every_step").empty).toContain("avant chaque étape");
    expect(inboxTexts("writes_only").description).toContain("avant chaque écriture");
    expect(approvalPromise("every_step")).toContain("lectures comprises");
    expect(approvalPromise("writes_only")).toContain("modifient des données");
  });

  it("dit ce qui suit une décision", () => {
    expect(decisionText(true, true)).toBe("Autorisé : l'étape suivante attend votre validation.");
    expect(decisionText(true, false)).toBe("Autorisé : le workflow a repris.");
    expect(decisionText(false, false)).toContain("arrêtée");
  });
});
