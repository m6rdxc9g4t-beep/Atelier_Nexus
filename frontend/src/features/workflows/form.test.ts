import { describe, expect, it } from "vitest";

import type { WorkflowRunResult } from "@/types/api";

import {
  allDecided,
  initialValues,
  missingParams,
  placeholderNames,
  stepDraft,
  syncParams,
  toFields,
} from "./form";

const describeStep = stepDraft({ tool: "data_via_describe_dataset", input: { dataset_id: "{{jeu}}" }, label: "" });
const queryStep = stepDraft({
  tool: "data_via_query",
  input: { dataset_id: "{{ jeu }}", filters: [{ field: "date", op: "gte", values: ["{{debut}}"] }] },
  label: "",
});

describe("paramètres {{nom}}", () => {
  it("détecte les noms dans l'ordre, sans doublon", () => {
    expect(placeholderNames([describeStep.inputText, queryStep.inputText])).toEqual(["jeu", "debut"]);
    expect(placeholderNames(['{"x": "{{ Majuscule }}", "y": "{{1x}}"}'])).toEqual([]);
  });

  it("garde libellés et valeurs par défaut, retire les paramètres qui ne servent plus", () => {
    const kept = syncParams([describeStep, queryStep], [
      { name: "jeu", label: "Jeu de données", default: "ventes" },
      { name: "ancien", label: "", default: "" },
    ]);
    expect(kept).toEqual([
      { name: "jeu", label: "Jeu de données", default: "ventes" },
      { name: "debut", label: "", default: "" },
    ]);
  });
});

describe("étapes", () => {
  it("ont chacune un identifiant stable", () => {
    const a = stepDraft({ tool: "x", input: {}, label: "" });
    const b = stepDraft({ tool: "x", input: {}, label: "" });
    expect(a.key).not.toBe(b.key);
  });
});

describe("toFields", () => {
  it("prépare le corps envoyé à l'API", () => {
    const parsed = toFields({
      title: "  CA par région ",
      description: "",
      steps: [describeStep, queryStep],
      params: [{ name: "jeu", label: " Jeu ", default: "ventes" }],
    });
    expect(parsed.errors).toEqual({});
    expect(parsed.fields?.title).toBe("CA par région");
    expect(parsed.fields?.steps[1]?.input).toEqual({
      dataset_id: "{{ jeu }}",
      filters: [{ field: "date", op: "gte", values: ["{{debut}}"] }],
    });
    expect(parsed.fields?.params).toEqual([
      { name: "jeu", label: "Jeu", default: "ventes" },
      { name: "debut", label: "", default: "" },
    ]);
  });

  it("signale titre vide, étape absente et JSON invalide", () => {
    expect(toFields({ title: " ", description: "", steps: [], params: [] }).errors).toEqual({
      title: "Donnez un titre au workflow.",
      steps: "Il faut au moins une étape.",
    });
    const broken = { ...describeStep, inputText: "[1, 2]" };
    const parsed = toFields({ title: "x", description: "", steps: [describeStep, broken], params: [] });
    expect(parsed.fields).toBeNull();
    expect(Object.keys(parsed.errors)).toEqual(["step-1"]);
  });
});

describe("lancement", () => {
  const params = [
    { name: "jeu", label: "Jeu de données", default: "ventes" },
    { name: "mois", label: "", default: "" },
  ];

  it("part des valeurs par défaut et liste ce qui manque", () => {
    const values = initialValues(params);
    expect(values).toEqual({ jeu: "ventes", mois: "" });
    expect(missingParams(params, values)).toEqual(["mois"]);
    expect(missingParams(params, { ...values, mois: "2026-03" })).toEqual([]);
  });

  it("attend une décision pour chaque étape d'écriture", () => {
    const result: WorkflowRunResult = {
      status: "awaiting_approval",
      message: "",
      steps: [],
      artifacts: [],
      pending: [
        { index: 2, tool: "projets_create_work_item", summary: "Créer…", token: "a1" },
        { index: 4, tool: "projets_add_time_entry", summary: "Saisir…", token: "b2" },
      ],
    };
    expect(allDecided(result, { a1: true })).toBe(false);
    expect(allDecided(result, { "2": true, "4": false })).toBe(false);
    expect(allDecided(result, { a1: true, b2: false })).toBe(true);
  });
});
