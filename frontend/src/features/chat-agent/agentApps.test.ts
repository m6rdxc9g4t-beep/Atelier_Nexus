import { describe, expect, it } from "vitest";

import { agentApps, toolApp } from "./agentApps";

describe("applications d'un agent", () => {
  it("déduit les applications des boîtes, sans doublon ni outils système", () => {
    expect(agentApps({ toolsets: ["core", "data_via", "tab", "tab_write"] })).toEqual(["viz", "tab"]);
    expect(agentApps({ toolsets: ["core", "delegation"] })).toEqual([]);
  });

  it("rattache les outils d'une boîte inconnue par leur préfixe", () => {
    expect(
      agentApps({ toolsets: ["extension_x"], tools: [{ name: "projets_list_projects" }, { name: "publish_artifact" }] }),
    ).toEqual(["projets"]);
  });

  it("reconnaît l'application d'un outil", () => {
    expect(toolApp("data_via_query")).toBe("viz");
    expect(toolApp("github_commit_files")).toBe("github");
    expect(toolApp("current_datetime")).toBeNull();
  });
});
