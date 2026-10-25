import { describe, expect, it } from "vitest";

import type { ConversationDetail } from "@/types/api";

import {
  type ApprovalPart,
  type Part,
  type ToolCallPart,
  applyEvent,
  fromStored,
  pendingApproval,
  submitApprovals,
} from "./conversation";
import { activitySummary, formatParams, groupParts, liveMessage } from "./thread";

const tool = (id: string, name: string, status: ToolCallPart["status"] = "done", result = "ok"): ToolCallPart => ({
  kind: "tool",
  id,
  name,
  input: { id },
  status,
  result: status === "running" ? undefined : result,
});

const approval = (ids: string[], decisions: Record<string, boolean> = {}, submitted = true): ApprovalPart => ({
  kind: "approval",
  calls: ids.map((id) => ({ id, name: "projets_create_work_item", input: { id }, summary: `Créer ${id}`, kind: "write" })),
  decisions,
  submitted,
});

describe("groupParts", () => {
  it("regroupe les appels consécutifs en une ligne d'activité entre les textes", () => {
    const parts: Part[] = [
      { kind: "text", text: "Je regarde." },
      tool("a", "data_via_query"),
      { kind: "text", text: "  \n" },
      tool("b", "projets_list_projects"),
      { kind: "text", text: "Voilà." },
      tool("c", "tab_read_table"),
    ];
    const segments = groupParts(parts);
    expect(segments.map((s) => s.kind)).toEqual(["text", "activity", "text", "activity"]);
    const first = segments[1]!;
    expect(first.kind === "activity" && first.entries.map((e) => e.id)).toEqual(["a", "b"]);
    expect(first.key).toBe("activity-a");
  });

  it("garde seule la validation en attente, et fond une validation envoyée dans l'activité", () => {
    const pending = groupParts([tool("a", "data_via_query"), approval(["b"], {}, false)]);
    expect(pending.map((s) => s.kind)).toEqual(["activity", "approval"]);

    // Même tour après « Autoriser » puis l'exécution : un seul groupe, même clé qu'avant
    const after = groupParts(
      [tool("a", "data_via_query"), approval(["b"], { b: true }), tool("b", "projets_create_work_item")],
      { live: true },
    );
    expect(after).toHaveLength(1);
    const group = after[0]!;
    expect(group.key).toBe("activity-a");
    if (group.kind !== "activity") throw new Error("activité attendue");
    expect(group.entries[1]).toMatchObject({ id: "b", summary: "Créer b", decision: true, status: "done" });
  });

  it("donne l'état de chaque action : autorisée pas encore lancée, refusée, en erreur", () => {
    const parts: Part[] = [
      approval(["x", "y", "z"], { x: true, y: false, z: true }),
      tool("y", "projets_create_work_item", "error", "L'utilisateur a refusé cette action : ne la relance pas."),
      tool("z", "projets_create_work_item", "error", "Projet introuvable"),
    ];
    const [group] = groupParts(parts, { live: true });
    if (group?.kind !== "activity") throw new Error("activité attendue");
    expect(group.entries.map((e) => [e.id, e.status])).toEqual([
      ["x", "queued"],
      ["y", "refused"],
      ["z", "error"],
    ]);

    // Réponse arrêtée ou en échec avant x : autorisée mais jamais lancée, plus jamais « en cours »
    const [ended] = groupParts(parts);
    if (ended?.kind !== "activity") throw new Error("activité attendue");
    expect(ended.entries[0]!.status).toBe("interrupted");
    expect(activitySummary(ended.entries)).toMatchObject({ status: "error", interrupted: 1, current: undefined });
  });

  it("montre une action validée là où elle s'exécute, même après un livrable publié entre deux appels", () => {
    // Deux appels validés ensemble ; le premier publie un livrable (événement entre son appel et son résultat)
    const parts: Part[] = [
      approval(["a", "b"], { a: true, b: true }),
      tool("a", "publish_artifact"),
      { kind: "artifact", artifactId: "art-1", title: "Rapport" },
      tool("b", "projets_create_work_item"),
    ];
    const segments = groupParts(parts);
    expect(segments.map((s) => s.key)).toEqual(["activity-a", "artifact-art-1", "activity-b"]);
    const [first, , second] = segments;
    if (first?.kind !== "activity" || second?.kind !== "activity") throw new Error("activités attendues");
    // b n'est pas resté « autorisée, en attente » dans la première ligne
    expect(first.entries.map((e) => e.id)).toEqual(["a"]);
    expect(second.entries[0]).toMatchObject({ id: "b", summary: "Créer b", decision: true, status: "done" });
    expect(activitySummary(first.entries).status).toBe("done");

    // Avant l'arrivée de b : la première ligne le montre encore, en attente, sans changer de clé
    const [early] = groupParts(parts.slice(0, 2), { live: true });
    expect(early?.key).toBe("activity-a");
    expect(early?.kind === "activity" && early.entries.map((e) => [e.id, e.status])).toEqual([
      ["a", "done"],
      ["b", "queued"],
    ]);
  });

  it("ne donne jamais deux fois la même clé, même si un moteur répète un identifiant", () => {
    const keys = groupParts([tool("a", "tab_read_table"), { kind: "text", text: "Puis :" }, tool("a", "tab_read_table")]).map(
      (s) => s.key,
    );
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("reconnaît un refus dans une conversation rouverte (décision non enregistrée)", () => {
    const [group] = groupParts([tool("a", "tab_set_cells", "error", "L'utilisateur a refusé cette action : propose autre chose.")]);
    if (group?.kind !== "activity") throw new Error("activité attendue");
    expect(group.entries[0]!.status).toBe("refused");
  });
});

describe("activitySummary", () => {
  const entriesOf = (parts: Part[]) => {
    const [group] = groupParts(parts);
    if (group?.kind !== "activity") throw new Error("activité attendue");
    return group.entries;
  };

  it("compte les actions et liste les applications sans doublon", () => {
    const summary = activitySummary(
      entriesOf([tool("a", "data_via_query"), tool("b", "projets_dashboard"), tool("c", "data_via_list_datasets"), tool("d", "current_datetime")]),
    );
    expect(summary).toMatchObject({ count: 4, apps: ["viz", "projets"], status: "done", refused: 0, errors: 0 });
  });

  it("est en cours tant qu'une action tourne, et nomme celle-ci", () => {
    const summary = activitySummary(entriesOf([tool("a", "data_via_query"), tool("b", "tab_read_table", "running")]));
    expect(summary.status).toBe("running");
    expect(summary.current?.id).toBe("b");
  });

  it("signale les erreurs, et un groupe entièrement refusé", () => {
    expect(activitySummary(entriesOf([tool("a", "tab_read_table", "error", "boom")])).status).toBe("error");
    const refused = activitySummary(entriesOf([approval(["a"], { a: false }), tool("a", "tab_set_cells", "error", "refus")]));
    expect(refused).toMatchObject({ status: "refused", refused: 1, errors: 0 });
  });
});

describe("formatParams", () => {
  it("met les valeurs simples sur la ligne de leur clé", () => {
    expect(formatParams({ branch: "feat/x", draft: true, count: 3, note: "" })).toBe(
      "branch : feat/x\ndraft : oui\ncount : 3\nnote : (vide)",
    );
    expect(formatParams({})).toBe("(aucun paramètre)");
  });

  it("déplie listes et objets, et garde les textes longs tels qu'ils seront écrits", () => {
    const text = formatParams({
      message: "Corrige le calcul",
      files: [{ path: "a.py", content: "x = 1\nfiles :\n- path: piege" }],
      tags: [],
    });
    expect(text).toBe(
      [
        "message : Corrige le calcul",
        "files :",
        "  - path : a.py",
        "    content :",
        "      │ x = 1",
        "      │ files :",
        "      │ - path: piege",
        "tags : (aucun)",
      ].join("\n"),
    );
  });

  it("met entre guillemets une clé qui pourrait se faire passer pour une autre ligne", () => {
    expect(formatParams({ "message : ok\nbranch": "main", " note": "x", "": 1 })).toBe(
      ['"message : ok\\nbranch" : main', '" note" : x', '"" : 1'].join("\n"),
    );
  });

  it("coupe aussi les textes sur les retours à la ligne CR et U+2028, sous la gouttière", () => {
    expect(formatParams({ body: "un\rdeux\u2028trois" })).toBe(["body :", "  │ un", "  │ deux", "  │ trois"].join("\n"));
  });

  it("montre telle quelle une entrée qui n'est pas un objet", () => {
    expect(formatParams(null)).toBe("(aucun paramètre)");
    expect(formatParams("texte brut")).toBe("texte brut");
    expect(formatParams([1, 2])).toBe("- 1\n- 2");
  });

  it("liste des valeurs simples à puces", () => {
    expect(formatParams({ ids: [12, 15], questions: ["Capitale ?", "Deux\nlignes"] })).toBe(
      ["ids :", "  - 12", "  - 15", "questions :", "  - Capitale ?", "  -", "    │ Deux", "    │ lignes"].join("\n"),
    );
  });
});

describe("liveMessage", () => {
  const idle = { streaming: false, pending: null, failed: false };

  it("annonce une validation demandée, une seule fois", () => {
    const asked = { streaming: true, pending: "a-b", failed: false };
    expect(liveMessage({ ...idle, streaming: true }, asked)).toBe("Validation demandée");
    expect(liveMessage(asked, { ...asked, streaming: false })).toBeNull();
  });

  it("annonce la fin d'une réponse, ou son échec", () => {
    expect(liveMessage({ ...idle, streaming: true }, idle)).toBe("Réponse terminée");
    expect(liveMessage({ ...idle, streaming: true }, { ...idle, failed: true })).toBe("La réponse a échoué");
    expect(liveMessage(idle, idle)).toBeNull();
  });
});

describe("conversation rouverte depuis l'historique", () => {
  // Lecture déjà faite, puis une écriture restée en attente de validation à la fermeture
  const write = { id: "w1", name: "projets_create_work_item", input: { title: "Recette" }, summary: "Créer « Recette »" };
  const detail: ConversationDetail = {
    id: "c1",
    agent: "projets",
    title: "Recette",
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:00:00Z",
    message_count: 4,
    artifact_count: 0,
    history: [
      { role: "user", content: [{ type: "text", text: "Crée la tâche Recette" }] },
      {
        role: "assistant",
        content: [
          { type: "text", text: "Je regarde le projet." },
          { type: "tool_use", id: "r1", name: "projets_structure", input: { project_id: 3 } },
        ],
      },
      {
        role: "user",
        content: [{ type: "tool_result", tool_use_id: "r1", tool_name: "projets_structure", content: "ok", is_error: false }],
      },
      { role: "assistant", content: [{ type: "tool_use", id: "w1", name: "projets_create_work_item", input: write.input }] },
    ],
    artifacts: [],
    turn_meta: {},
    pending_approvals: [write],
  };

  it("montre la carte, l'annonce, puis le reçu une fois la décision envoyée", () => {
    const conv = fromStored(detail, {});
    const turn = conv.turns.at(-1)!;
    const segments = groupParts(turn.parts);
    expect(segments.map((s) => s.kind)).toEqual(["text", "activity", "approval"]);
    // Carte : paramètres de l'appel visibles avant de décider
    const card = segments[2]!;
    if (card.kind !== "approval") throw new Error("carte attendue");
    expect(formatParams(card.part.calls[0]!.input)).toBe("title : Recette");

    // Dock et région aria-live : la validation est en attente, comme en direct
    const pending = pendingApproval(conv);
    expect(pending?.calls.map((c) => c.id)).toEqual(["w1"]);
    const idle = { streaming: false, pending: null, failed: false };
    expect(liveMessage(idle, { ...idle, pending: "w1" })).toBe("Validation demandée");

    // « Autoriser », puis la reprise exécute l'appel : la carte devient un reçu dans l'activité
    const submitted = submitApprovals(conv, { w1: true });
    expect(submitted?.approvals).toEqual({ w1: true });
    let next = submitted!.conv;
    next = applyEvent(next, { type: "tool_call", id: "w1", name: write.name, input: write.input });
    next = applyEvent(next, { type: "tool_result", id: "w1", name: write.name, content: "Créé #12", is_error: false });
    expect(pendingApproval(next)).toBeNull();
    const after = groupParts(next.turns.at(-1)!.parts, { live: true });
    expect(after.map((s) => s.key)).toEqual([segments[0]!.key, segments[1]!.key]);
    const activity = after[1]!;
    if (activity.kind !== "activity") throw new Error("activité attendue");
    expect(activity.entries.map((e) => [e.id, e.status, e.decision])).toEqual([
      ["r1", "done", undefined],
      ["w1", "done", true],
    ]);
  });
});
