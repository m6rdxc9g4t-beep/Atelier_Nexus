import { beforeEach, describe, expect, it } from "vitest";

import { useWorkflowStudioStore } from "./useWorkflowStudioStore";

describe("useWorkflowStudioStore", () => {
  beforeEach(() => useWorkflowStudioStore.setState({ editor: null, returnTo: null, editorDirty: false, editorKey: 0, listOpen: false, listAgent: null, mapOpen: false, inboxOpen: false, inboxVersion: 0, lastWorkflow: null, version: 0 }));

  it("ouvre l'éditeur avec une nouvelle clé à chaque fois", () => {
    const { openEditor } = useWorkflowStudioStore.getState();
    openEditor({ kind: "new", agent: null, uses: "node:tab/rows.add" });
    const first = useWorkflowStudioStore.getState().editorKey;
    openEditor({ kind: "new", agent: null, uses: "node:tab/rows.add" });
    expect(useWorkflowStudioStore.getState().editorKey).toBe(first + 1);
    expect(useWorkflowStudioStore.getState().editor).toEqual({ kind: "new", agent: null, uses: "node:tab/rows.add" });
    useWorkflowStudioStore.getState().closeEditor();
    expect(useWorkflowStudioStore.getState().editor).toBeNull();
  });

  it("remplace la carte par l'éditeur, puis la rouvre", () => {
    const store = useWorkflowStudioStore.getState();
    store.setMapOpen(true);
    store.openEditor({ kind: "new", agent: null });
    expect(useWorkflowStudioStore.getState()).toMatchObject({ mapOpen: false, returnTo: "map" });
    // Ouvrir un autre workflow depuis l'éditeur garde la fenêtre de retour
    useWorkflowStudioStore.getState().openEditor({ kind: "open", id: "wf_1" });
    expect(useWorkflowStudioStore.getState().returnTo).toBe("map");
    useWorkflowStudioStore.getState().closeEditor();
    expect(useWorkflowStudioStore.getState()).toMatchObject({ mapOpen: true, listOpen: false, returnTo: null });
  });

  it("ouvre la liste d'un agent ou de toute la suite, puis y revient", () => {
    useWorkflowStudioStore.getState().openList("data_analyst");
    expect(useWorkflowStudioStore.getState()).toMatchObject({ listOpen: true, listAgent: "data_analyst" });
    useWorkflowStudioStore.getState().openEditor({ kind: "open", id: "wf_1", panel: "run" });
    expect(useWorkflowStudioStore.getState()).toMatchObject({ listOpen: false, returnTo: "list" });
    useWorkflowStudioStore.getState().closeEditor();
    expect(useWorkflowStudioStore.getState()).toMatchObject({ listOpen: true, listAgent: "data_analyst" });
    useWorkflowStudioStore.getState().openList(null);
    expect(useWorkflowStudioStore.getState().listAgent).toBeNull();
  });

  it("oublie les modifications en cours à la fermeture ou à l'ouverture d'un autre workflow", () => {
    const store = useWorkflowStudioStore.getState();
    store.openEditor({ kind: "new", agent: null });
    useWorkflowStudioStore.getState().setEditorDirty(true);
    useWorkflowStudioStore.getState().openEditor({ kind: "open", id: "wf_2" });
    expect(useWorkflowStudioStore.getState().editorDirty).toBe(false);
    useWorkflowStudioStore.getState().setEditorDirty(true);
    useWorkflowStudioStore.getState().closeEditor();
    expect(useWorkflowStudioStore.getState().editorDirty).toBe(false);
  });

  it("signale les changements aux listes", () => {
    useWorkflowStudioStore.getState().bump();
    useWorkflowStudioStore.getState().setMapOpen(true);
    expect(useWorkflowStudioStore.getState()).toMatchObject({ version: 1, mapOpen: true });
  });

  it("rouvre la boîte « À valider » après l'éditeur", () => {
    const store = useWorkflowStudioStore.getState();
    store.setInboxOpen(true);
    expect(useWorkflowStudioStore.getState().inboxOpen).toBe(true);
    store.openEditor({ kind: "open", id: "wf_1", panel: "run", runId: "run_1" });
    expect(useWorkflowStudioStore.getState()).toMatchObject({ inboxOpen: false, returnTo: "inbox" });
    useWorkflowStudioStore.getState().closeEditor();
    expect(useWorkflowStudioStore.getState()).toMatchObject({ inboxOpen: true, mapOpen: false, listOpen: false });
    // Une fenêtre à la fois
    useWorkflowStudioStore.getState().setMapOpen(true);
    expect(useWorkflowStudioStore.getState()).toMatchObject({ inboxOpen: false, mapOpen: true });
  });

  it("garde un déclencheur prérempli dans la cible de l'éditeur", () => {
    const preset = { app: "projets" as const, types: ["projets.work_item.status_changed"] };
    useWorkflowStudioStore.getState().openEditor({ kind: "new", agent: null, trigger: preset });
    expect(useWorkflowStudioStore.getState().editor).toEqual({ kind: "new", agent: null, trigger: preset });
    useWorkflowStudioStore.getState().setLastWorkflow({ id: "wf_1", title: "Doc" });
    expect(useWorkflowStudioStore.getState().lastWorkflow).toEqual({ id: "wf_1", title: "Doc" });
  });
});
