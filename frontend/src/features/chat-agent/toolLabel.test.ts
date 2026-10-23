import { describe, expect, it } from "vitest";

import { registerToolLabels, toolLabel } from "./ToolCall";

describe("toolLabel", () => {
  it("garde les libellés connus et apprend ceux du backend (extensions)", () => {
    expect(toolLabel("data_via_query")).toBe("Data Via · requête");
    expect(toolLabel("convert_file")).toBe("convert_file");
    registerToolLabels([
      {
        tools: [
          { name: "convert_file", label: "Convert · conversion d'un fichier" },
          { name: "data_via_query", label: "autre libellé" },
          { name: "sans_libelle" },
        ],
      },
    ]);
    expect(toolLabel("convert_file")).toBe("Convert · conversion d'un fichier");
    expect(toolLabel("data_via_query")).toBe("Data Via · requête"); // la liste locale prime
    expect(toolLabel("sans_libelle")).toBe("sans_libelle");
  });
});
