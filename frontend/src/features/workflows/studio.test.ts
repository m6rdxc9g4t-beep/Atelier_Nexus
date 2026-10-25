import { beforeEach, describe, expect, it } from "vitest";

import { draftFromTemplate } from "@/features/workflows-graph/draft";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AnyWorkflow, WorkflowTemplate } from "@/types/api";

import {
  filterWorkflows,
  homeTemplates,
  lastRunText,
  lastStatus,
  missingLines,
  shownSection,
  orderTemplates,
  stepsText,
  studioTab,
  templateSeed,
  templateTarget,
} from "./studio";

const closed = { listOpen: false, mapOpen: false, inboxOpen: false, editor: null, returnTo: null };

describe("onglet du Studio", () => {
  it("suit la fenêtre ouverte dans le store", () => {
    expect(studioTab(closed)).toBeNull();
    expect(studioTab({ ...closed, listOpen: true })).toBe("workflows");
    expect(studioTab({ ...closed, mapOpen: true })).toBe("map");
    expect(studioTab({ ...closed, inboxOpen: true })).toBe("inbox");
  });

  it("reste sur l'onglet de retour pendant l'éditeur en graphe", () => {
    expect(studioTab({ ...closed, editor: { kind: "new", agent: null }, returnTo: "map" })).toBe("map");
    // Éditeur ouvert depuis l'accueil ou la conversation : pas de Studio derrière
    expect(studioTab({ ...closed, editor: { kind: "new", agent: null }, returnTo: null })).toBeNull();
  });

  describe("avec le store", () => {
    beforeEach(() =>
      useWorkflowStudioStore.setState({ editor: null, returnTo: null, listOpen: false, listAgent: null, listSection: "mine", mapOpen: false, inboxOpen: false }),
    );

    it("ouvre les modèles de la suite, les garde pendant l'éditeur, puis les retrouve", () => {
      useWorkflowStudioStore.getState().openList("data_analyst");
      useWorkflowStudioStore.getState().openTemplates();
      expect(useWorkflowStudioStore.getState()).toMatchObject({ listOpen: true, listAgent: null, listSection: "templates" });
      useWorkflowStudioStore.getState().openEditor({ kind: "new", agent: null });
      expect(studioTab(useWorkflowStudioStore.getState())).toBe("workflows");
      useWorkflowStudioStore.getState().closeEditor();
      expect(useWorkflowStudioStore.getState()).toMatchObject({ listOpen: true, listSection: "templates" });
    });

    it("montre les workflows d'un agent suivi, même si les modèles étaient affichés", () => {
      useWorkflowStudioStore.getState().openTemplates();
      useWorkflowStudioStore.getState().openList("data_analyst");
      const s = useWorkflowStudioStore.getState();
      expect(shownSection(s.listSection, s.listAgent)).toBe("mine");
      expect(shownSection("templates", null)).toBe("templates");
    });

    it("se ferme vers l'accueil ou la conversation", () => {
      useWorkflowStudioStore.getState().setInboxOpen(true);
      useWorkflowStudioStore.getState().closeStudio();
      expect(studioTab(useWorkflowStudioStore.getState())).toBeNull();
    });
  });
});

const wf = (id: string, agent: string | null, title: string, description = ""): AnyWorkflow =>
  ({ id, agent, title, description, version: 2, steps: [], params: [] }) as unknown as AnyWorkflow;

describe("Mes workflows", () => {
  const items = [
    wf("a", null, "Relevé vers Tab", "Convertit le dernier relevé"),
    wf("b", "data_analyst", "Ventes du mois"),
    wf("c", "projets", "Écrire la doc"),
  ];
  const ownerName = (w: AnyWorkflow) => (w.agent === "data_analyst" ? "Data Analyst" : w.agent ? "Projets" : "Suite");
  const ids = (list: AnyWorkflow[]) => list.map((w) => w.id);

  it("filtre par portée", () => {
    expect(ids(filterWorkflows(items, { scope: "all", agent: null, query: "", ownerName }))).toEqual(["a", "b", "c"]);
    expect(ids(filterWorkflows(items, { scope: "suite", agent: null, query: "", ownerName }))).toEqual(["a"]);
    expect(ids(filterWorkflows(items, { scope: "agent", agent: "data_analyst", query: "", ownerName }))).toEqual(["b"]);
  });

  it("cherche tous les mots, sans accents ni casse, jusque dans le nom de l'agent", () => {
    expect(ids(filterWorkflows(items, { scope: "all", agent: null, query: "ecrire", ownerName }))).toEqual(["c"]);
    expect(ids(filterWorkflows(items, { scope: "all", agent: null, query: "dernier RELEVÉ", ownerName }))).toEqual(["a"]);
    expect(ids(filterWorkflows(items, { scope: "all", agent: null, query: "data ventes", ownerName }))).toEqual(["b"]);
    expect(ids(filterWorkflows(items, { scope: "all", agent: null, query: "rien", ownerName }))).toEqual([]);
  });

  it("résume étapes et paramètres", () => {
    expect(stepsText(1, 0)).toBe("1 étape");
    expect(stepsText(4, 2)).toBe("4 étapes · 2 paramètres");
    expect(stepsText(2, 1)).toBe("2 étapes · 1 paramètre");
  });

  it("dit le dernier lancement", () => {
    const now = new Date(2026, 9, 25, 16, 0);
    expect(lastRunText(null, now)).toBe("Jamais lancé");
    expect(lastRunText("pas une date", now)).toBe("Jamais lancé");
    expect(lastRunText(new Date(2026, 9, 25, 14, 5).toISOString(), now)).toBe("Lancé aujourd'hui, 14:05");
    expect(lastRunText(new Date(2026, 9, 24, 9, 30).toISOString(), now)).toBe("Lancé hier, 09:30");
    expect(lastRunText(new Date(2026, 9, 12, 9, 30).toISOString(), now)).toBe("Lancé le 12 oct.");
  });

  it("traduit le statut du dernier lancement, v1 comme v2", () => {
    expect(lastStatus("completed")).toEqual({ variant: "success", label: "réussi" });
    expect(lastStatus("awaiting_approval")?.label).toBe("à valider");
    expect(lastStatus("inconnu")).toBeNull();
    expect(lastStatus(null)).toBeNull();
  });
});

const template = (slug: string, available: boolean, missing: string[] = []): WorkflowTemplate => ({
  slug,
  title: slug,
  description: "",
  value: "",
  apps: ["convert", "tab"],
  params: [],
  steps: [],
  requirements: [],
  trigger_hint: null,
  available,
  missing,
});

describe("modèles de la suite", () => {
  const all = [template("a", false), template("b", true), template("c", false), template("d", true), template("e", true), template("f", true)];

  it("met les modèles disponibles d'abord", () => {
    expect(orderTemplates(all).map((t) => t.slug)).toEqual(["b", "d", "e", "f", "a", "c"]);
  });

  it("met en avant trois modèles, les disponibles d'abord, complétés par les autres", () => {
    expect(homeTemplates(all).map((t) => t.slug)).toEqual(["b", "d", "e"]);
    expect(homeTemplates([template("a", false), template("b", true), template("c", false)]).map((t) => t.slug)).toEqual([
      "b",
      "a",
      "c",
    ]);
    expect(homeTemplates([template("x", false), template("y", false), template("z", false), template("w", false)]).map((t) => t.slug)).toEqual([
      "x",
      "y",
      "z",
    ]);
    expect(homeTemplates([])).toEqual([]);
  });

  it("dit ce qui manque en clair, l'étape technique à part, sans répéter une raison", () => {
    expect(
      missingLines([
        "node:convert/conversions.list : Atelier Convert injoignable",
        "node:convert/conversions.get : Atelier Convert injoignable",
        "tool:tab_add_rows : boîte « tab_write » non configurée",
        "Serveur MCP de Tab absent",
      ]),
    ).toEqual([
      { text: "Atelier Convert injoignable", detail: "node:convert/conversions.list, node:convert/conversions.get" },
      { text: "boîte « tab_write » non configurée", detail: "tool:tab_add_rows" },
      { text: "Serveur MCP de Tab absent", detail: null },
    ]);
  });

  it("« Utiliser ce modèle » ouvre l'éditeur sur un brouillon prérempli, puis revient aux modèles", () => {
    const releve: WorkflowTemplate = {
      ...template("releve", true),
      title: "Relevé → Tab",
      description: "Copie le dernier relevé dans une table.",
      params: [{ name: "table", label: "Table", default: "releves" }],
      steps: [
        { id: "lire", label: "Lire", uses: "node:convert/conversions.list", input: {}, needs: [], on_error: "stop", position: null },
        { id: "ecrire", label: "Écrire", uses: "node:tab/rows.add", input: { table: "{{params.table}}" }, needs: ["lire"], on_error: "stop", position: null },
      ],
    };
    const target = templateTarget(releve);
    expect(target).toEqual({ kind: "new", agent: null, template: templateSeed(releve) });
    // Ce que l'éditeur en graphe tire de la cible : un brouillon de suite, non enregistré
    const draft = draftFromTemplate(target.kind === "new" ? target.template! : templateSeed(releve), null);
    expect(draft).toMatchObject({ id: null, agent: null, title: "Relevé → Tab", description: "Copie le dernier relevé dans une table." });
    expect(draft.steps.map((s) => s.id)).toEqual(["lire", "ecrire"]);
    expect(draft.params).toEqual([{ name: "table", label: "Table", default: "releves" }]);

    useWorkflowStudioStore.setState({ editor: null, returnTo: null, listOpen: false, listAgent: null, listSection: "mine", mapOpen: false, inboxOpen: false });
    useWorkflowStudioStore.getState().openTemplates();
    useWorkflowStudioStore.getState().openEditor(target);
    expect(useWorkflowStudioStore.getState()).toMatchObject({ editor: target, returnTo: "list" });
    useWorkflowStudioStore.getState().closeEditor();
    expect(useWorkflowStudioStore.getState()).toMatchObject({ listOpen: true, listSection: "templates" });
  });

  it("copie seulement le contenu du modèle dans la graine du brouillon", () => {
    const seed = templateSeed({ ...template("releve", true), title: "Relevé", description: "d", params: [{ name: "n", label: "N", default: "" }] });
    expect(seed).toEqual({ slug: "releve", title: "Relevé", description: "d", params: [{ name: "n", label: "N", default: "" }], steps: [] });
  });
});
