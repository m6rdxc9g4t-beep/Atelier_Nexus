import { describe, expect, it } from "vitest";

import { catalogIndex } from "./catalog";
import { catalogFixture, diamondSteps, runFixture, step } from "./fixtures";
import {
  LAYOUT,
  ancestors,
  applyLayout,
  connect,
  createStep,
  cyclicSteps,
  descendants,
  disconnect,
  graphToSteps,
  layoutSteps,
  mergeRunState,
  newStepId,
  nextPosition,
  nodeTone,
  removeSteps,
  renameStep,
  stepsToEdges,
  stepsToGraph,
  stepsToNodes,
  topoOrder,
  wouldCreateCycle,
} from "./graph";

const catalog = catalogIndex(catalogFixture);

describe("parcours du graphe", () => {
  it("calcule ancêtres et descendants transitivement", () => {
    const chain = [step("a", "x"), step("b", "x", ["a"]), step("c", "x", ["b"])];
    expect([...ancestors(chain, "c")].sort()).toEqual(["a", "b"]);
    expect([...ancestors(chain, "a")]).toEqual([]);
    expect([...descendants(chain, "a")].sort()).toEqual(["b", "c"]);
    expect([...ancestors(diamondSteps, "creer")].sort()).toEqual(["lire", "taches"]);
  });

  it("ordonne de façon stable et détecte les cycles", () => {
    expect(topoOrder(diamondSteps)).toEqual(["lire", "taches", "creer", "ajouter"]);
    const loop = [step("a", "x", ["b"]), step("b", "x", ["a"]), step("c", "x")];
    expect(topoOrder(loop)).toBeNull();
    expect(cyclicSteps(loop)).toEqual(["a", "b"]);
    expect(topoOrder([step("a", "x", ["a"])])).toBeNull();
    // Dépendance inconnue : ignorée pour l'ordre (la validation la signale)
    expect(topoOrder([step("a", "x", ["fantome"])])).toEqual(["a"]);
  });

  it("refuse une connexion qui fermerait une boucle ou existe déjà", () => {
    expect(wouldCreateCycle(diamondSteps, "creer", "lire")).toBe(true);
    expect(wouldCreateCycle(diamondSteps, "lire", "lire")).toBe(true);
    expect(connect(diamondSteps, "creer", "lire")).toBeNull();
    expect(connect(diamondSteps, "lire", "creer")).toBeNull();
    expect(connect(diamondSteps, "x", "creer")).toBeNull();
    const linked = connect(diamondSteps, "taches", "ajouter")!;
    expect(linked.find((s) => s.id === "ajouter")!.needs).toEqual(["lire", "taches"]);
    expect(disconnect(linked, "lire", "ajouter").find((s) => s.id === "ajouter")!.needs).toEqual(["taches"]);
  });
});

describe("modifications", () => {
  it("retire des étapes et les arêtes qui les citent", () => {
    const left = removeSteps(diamondSteps, ["lire"]);
    expect(left.map((s) => s.id)).toEqual(["taches", "creer", "ajouter"]);
    expect(left.find((s) => s.id === "creer")!.needs).toEqual(["taches"]);
    expect(left.find((s) => s.id === "ajouter")!.needs).toEqual([]);
  });

  it("renomme une étape dans needs et dans les gabarits", () => {
    const renamed = renameStep(diamondSteps, "lire", "ventes");
    expect(renamed[0]!.id).toBe("ventes");
    const creer = renamed.find((s) => s.id === "creer")!;
    expect(creer.needs).toEqual(["ventes", "taches"]);
    expect(creer.input.title).toBe("CA {{steps.ventes.data.rows[0].region}}");
    // Un préfixe identique n'est pas touché
    const other = renameStep([step("a", "x"), step("b", "x", ["a"], { v: "{{steps.ab.data}} {{ steps.a.content }}" })], "a", "z");
    expect(other[1]!.input.v).toBe("{{steps.ab.data}} {{ steps.z.content }}");
  });

  it("propose un identifiant libre et valide", () => {
    expect(newStepId([], "node:projets/work_items.create")).toBe("create");
    expect(newStepId([step("create", "x")], "node:projets/work_items.create")).toBe("create_2");
    expect(newStepId([], "tool:data_via_query")).toBe("data_via_query");
    expect(newStepId([], "node:x/9.Élément")).toBe("element");
    expect(newStepId([], "node:x/123")).toBe("etape");
    const created = createStep(diamondSteps, "node:tab/rows.add", { x: 1, y: 2 });
    expect(created).toMatchObject({ id: "add", label: "", needs: [], on_error: "stop", position: { x: 1, y: 2 } });
    expect(createStep(diamondSteps, "node:tab/rows.add", null, "lire").needs).toEqual(["lire"]);
    expect(createStep(diamondSteps, "node:tab/rows.add", null, "fantome").needs).toEqual([]);
  });

  it("place une étape ajoutée par clic à droite de la sélection, sans chevauchement", () => {
    const placed = applyLayout(diamondSteps);
    const lire = placed[0]!.position!;
    // creer et ajouter occupent déjà la colonne suivante
    const pos = nextPosition(placed, "lire");
    expect(pos.x).toBe(lire.x + LAYOUT.columnWidth);
    expect(placed.filter((s) => s.position!.x === pos.x).every((s) => s.position!.y < pos.y)).toBe(true);
    expect(nextPosition(placed, null)).toEqual({ x: 2 * LAYOUT.columnWidth, y: 0 });
    expect(nextPosition([], null)).toEqual({ x: 0, y: 0 });
  });
});

describe("mise en page en couches", () => {
  it("place chaque étape après la plus lointaine de ses dépendances", () => {
    const pos = layoutSteps(diamondSteps);
    expect(pos.lire!.x).toBe(0);
    expect(pos.taches!.x).toBe(0);
    expect(pos.creer!.x).toBe(LAYOUT.columnWidth);
    expect(pos.ajouter!.x).toBe(LAYOUT.columnWidth);
    expect(pos.lire!.y).not.toBe(pos.taches!.y);
    const chain = layoutSteps([step("a", "x"), step("b", "x", ["a"]), step("c", "x", ["a", "b"])]);
    expect(chain.c!.x).toBe(2 * LAYOUT.columnWidth);
  });

  it("ne déplace que les étapes sans position si demandé", () => {
    const placed = [{ ...step("a", "x"), position: { x: 999, y: 5 } }, step("b", "x", ["a"])];
    const result = applyLayout(placed, true);
    expect(result[0]!.position).toEqual({ x: 999, y: 5 });
    expect(result[1]!.position).toEqual({ x: LAYOUT.columnWidth, y: 0 });
    expect(applyLayout(placed)[0]!.position).toEqual({ x: 0, y: 0 });
  });

  it("reste lisible en cas de cycle", () => {
    const pos = layoutSteps([step("a", "x", ["b"]), step("b", "x", ["a"])]);
    expect(pos).toEqual({ a: { x: 0, y: 0 }, b: { x: LAYOUT.columnWidth, y: 0 } });
  });
});

describe("étapes ↔ nœuds et arêtes", () => {
  it("convertit les étapes en nœuds colorés par application et arêtes needs", () => {
    const { nodes, edges } = stepsToGraph(diamondSteps, { catalog });
    expect(nodes.map((n) => n.id)).toEqual(["lire", "taches", "creer", "ajouter"]);
    expect(nodes[0]!.data).toMatchObject({ app: "viz", kind: "read", outputFormat: "atelier-table/1", label: "Interroger un jeu" });
    expect(nodes[2]!.data).toMatchObject({ app: "projets", kind: "write" });
    expect(edges.map((e) => e.id)).toEqual(["lire->creer", "taches->creer", "lire->ajouter"]);
  });

  it("signale étape inconnue, indisponible, erreurs et état d'exécution", () => {
    const steps = [step("a", "node:projets/milestones.list"), step("b", "node:inconnue/x")];
    const nodes = stepsToNodes(steps, {
      catalog,
      errors: [{ step_id: "b", field: null, code: "UNKNOWN_USES", message: "?" }],
      run: { a: { status: "ok", errorCode: null } },
      selected: new Set(["b"]),
    });
    expect(nodes[0]!.data.unavailable).toBe("Atelier Projets ne répond pas.");
    expect(nodes[0]!.data.run?.status).toBe("ok");
    expect(nodes[1]!.data).toMatchObject({ unknown: true, app: "inconnue" });
    expect(nodes[1]!.data.errors).toHaveLength(1);
    expect(nodes.map((n) => n.selected)).toEqual([false, true]);
  });

  it("ne dit aucune étape inconnue tant que le catalogue se charge", () => {
    const steps = [step("a", "node:projets/milestones.list")];
    expect(stepsToNodes(steps, { catalog: new Map(), catalogReady: false })[0]!.data.unknown).toBe(false);
    expect(stepsToNodes(steps, { catalog: new Map() })[0]!.data.unknown).toBe(true);
  });

  it("une seule teinte de nœud : exécution d'abord, puis validation", () => {
    const bad = [{ step_id: "a", field: null, code: "CYCLE", message: "" }];
    const run = (status: NonNullable<Parameters<typeof nodeTone>[0]["run"]>["status"]) => ({ status, errorCode: null });
    expect(nodeTone({ run: null, errors: [] })).toBe("idle");
    expect(nodeTone({ run: null, errors: bad })).toBe("invalid");
    expect(nodeTone({ run: run("awaiting_approval"), errors: bad })).toBe("awaiting");
    expect(nodeTone({ run: run("running"), errors: [] })).toBe("running");
    expect(nodeTone({ run: run("error"), errors: [] })).toBe("failed");
    expect(nodeTone({ run: run("ok"), errors: bad })).toBe("invalid");
    expect(nodeTone({ run: run("ok"), errors: [] })).toBe("done");
    expect(nodeTone({ run: run("skipped"), errors: [] })).toBe("faded");
  });

  it("garde les dimensions mesurées des nœuds affichés", () => {
    const nodes = stepsToNodes(diamondSteps, { catalog, measured: { lire: { width: 240, height: 80 } } });
    expect(nodes[0]!.measured).toEqual({ width: 240, height: 80 });
    expect(nodes[1]!.measured).toBeUndefined();
    expect(stepsToEdges(diamondSteps, {}, new Set(["lire->creer"])).map((e) => e.selected)).toEqual([true, false, false]);
  });

  it("reconstruit positions et needs depuis le graphe", () => {
    const nodes = [
      { id: "lire", position: { x: 10.4, y: 20.6 } },
      { id: "creer", position: { x: 300, y: 0 } },
      { id: "ajouter", position: { x: 300, y: 100 } },
    ];
    const edges = [
      { source: "lire", target: "creer" },
      { source: "creer", target: "ajouter" },
      { source: "lire", target: "ajouter" },
      { source: "taches", target: "creer" },
    ];
    const steps = graphToSteps(diamondSteps, nodes, edges);
    expect(steps.map((s) => s.id)).toEqual(["lire", "creer", "ajouter"]);
    expect(steps[0]!.position).toEqual({ x: 10, y: 21 });
    // « taches » n'a plus de nœud : sa dépendance tombe ; ordre existant conservé, nouvelles à la suite
    expect(steps[1]!.needs).toEqual(["lire"]);
    expect(steps[2]!.needs).toEqual(["lire", "creer"]);
    // Aller-retour sans perte
    const graph = stepsToGraph(applyLayout(diamondSteps), { catalog });
    expect(graphToSteps(diamondSteps, graph.nodes, graph.edges).map((s) => s.needs)).toEqual(diamondSteps.map((s) => s.needs));
  });
});

describe("état d'exécution sur le graphe", () => {
  it("montre l'étape en cours tant que l'exécution tourne", () => {
    const view = mergeRunState(diamondSteps, runFixture());
    expect(view.lire!.status).toBe("ok");
    // taches n'attend rien, creer attend taches, ajouter n'attend que lire (terminée)
    expect(view.taches!.status).toBe("running");
    expect(view.creer!.status).toBe("pending");
    expect(view.ajouter!.status).toBe("running");
    expect(stepsToEdges(diamondSteps, view).find((e) => e.id === "lire->ajouter")!.animated).toBe(true);
  });

  it("reprend les statuts du moteur une fois l'exécution arrêtée", () => {
    const run = runFixture({ status: "awaiting_approval" });
    run.steps[2] = { ...run.steps[2]!, status: "awaiting_approval" };
    run.steps[1] = { ...run.steps[1]!, status: "error", error_code: "REF_NOT_FOUND" };
    const view = mergeRunState(diamondSteps, run);
    expect(view.taches).toEqual({ status: "error", errorCode: "REF_NOT_FOUND" });
    expect(view.creer!.status).toBe("awaiting_approval");
    expect(view.ajouter!.status).toBe("pending");
    expect(mergeRunState(diamondSteps, null)).toEqual({});
  });
});
