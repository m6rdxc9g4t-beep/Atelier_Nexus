import { beforeEach, describe, expect, it } from "vitest";

import { templateSeed } from "@/features/workflows/studio";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { WorkflowTemplate } from "@/types/api";

import { draftFromTemplate, draftSignature, saveState } from "./draft";
import { leaveEditor } from "./leave";

const store = () => useWorkflowStudioStore.getState();

const template: WorkflowTemplate = {
  slug: "conversions-tab",
  title: "Conversions → Tab",
  description: "Copie les conversions du jour dans une table de Tab.",
  value: "Plus de copier-coller.",
  apps: ["convert", "tab"],
  params: [{ name: "table", label: "Table", default: "conversions" }],
  steps: [
    { id: "lire", label: "", uses: "node:convert/conversions.list", input: {}, needs: [], when: null, on_error: "stop", position: { x: 0, y: 0 } },
    {
      id: "ajouter",
      label: "Ajouter les lignes",
      uses: "node:tab/rows.add",
      input: { table: "{{params.table}}", rows: "{{steps.lire.data}}" },
      needs: ["lire"],
      when: null,
      on_error: "continue",
      position: { x: 300, y: 0 },
    },
  ],
  requirements: [],
  trigger_hint: null,
  available: true,
  missing: [],
};

describe("sortie de l'éditeur", () => {
  beforeEach(() =>
    useWorkflowStudioStore.setState({
      editor: null,
      returnTo: null,
      editorDirty: false,
      listOpen: false,
      listAgent: null,
      listSection: "mine",
      mapOpen: false,
      inboxOpen: false,
    }),
  );

  it("ferme simplement : retour à la fenêtre d'origine", () => {
    store().setMapOpen(true);
    store().openEditor({ kind: "new", agent: null });
    leaveEditor(store(), "close");
    expect(store()).toMatchObject({ editor: null, mapOpen: true, listOpen: false, listSection: "mine" });
  });

  it("« Partir d'un modèle » : éditeur fermé, Studio sur les modèles de la suite", () => {
    store().openList("data_analyst");
    store().openEditor({ kind: "new", agent: "data_analyst" });
    leaveEditor(store(), "templates");
    expect(store()).toMatchObject({ editor: null, listOpen: true, listAgent: null, listSection: "templates", mapOpen: false, inboxOpen: false });

    // Depuis la carte de la suite aussi : la carte cède la place aux modèles
    store().setMapOpen(true);
    store().openEditor({ kind: "new", agent: null });
    leaveEditor(store(), "templates");
    expect(store()).toMatchObject({ editor: null, listOpen: true, listSection: "templates", mapOpen: false });
  });

  it("le modèle choisi rouvre l'éditeur sur un brouillon prérempli, jamais enregistré", () => {
    leaveEditor(store(), "templates");
    store().openEditor({ kind: "new", agent: null, template: templateSeed(template) });
    const target = store().editor;
    expect(store()).toMatchObject({ listOpen: false, returnTo: "list", editorDirty: false });
    if (target?.kind !== "new" || !target.template) throw new Error("cible sans modèle");

    // Ce que l'éditeur fait de la cible (GraphEditor) : brouillon sans id, comparé à aucune version
    const draft = draftFromTemplate(target.template, target.agent);
    expect(draft).toMatchObject({ id: null, agent: null, title: "Conversions → Tab", sourceConversationId: null });
    expect(draft.params).toEqual(template.params);
    expect(draft.steps.map((s) => [s.id, s.position, s.on_error])).toEqual([
      ["lire", { x: 0, y: 0 }, "stop"],
      ["ajouter", { x: 300, y: 0 }, "continue"],
    ]);
    const saved: string | null = null;
    const dirty = draftSignature(draft) !== saved;
    expect(dirty).toBe(true);
    expect(saveState(draft, dirty)).toBe("draft");
    // Le modèle de la bibliothèque n'est jamais modifié par l'édition du brouillon
    draft.steps[1]!.input.table = "autre";
    expect(template.steps[1]!.input.table).toBe("{{params.table}}");

    // Fermer le brouillon revient aux modèles
    leaveEditor(store(), "close");
    expect(store()).toMatchObject({ editor: null, listOpen: true, listSection: "templates" });
  });
});
