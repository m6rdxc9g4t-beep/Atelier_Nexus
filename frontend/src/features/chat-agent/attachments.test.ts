import { describe, expect, it } from "vitest";

import {
  ACCEPT,
  MAX_BYTES,
  describe as describeFile,
  fileFamily,
  formatSize,
  pastedName,
  precheck,
  toBlock,
} from "./attachments";

describe("pièces jointes", () => {
  it("contrôle les fichiers avant l'envoi", () => {
    expect(precheck({ name: "Bilan.XLSX", size: 10 })).toBeNull();
    expect(precheck({ name: "capture.png", size: 10 })).toBeNull();
    expect(precheck({ name: "photo.HEIC", size: 10 })).toMatch(/JPEG/);
    expect(precheck({ name: "vieux.doc", size: 10 })).toMatch(/\.docx/);
    expect(precheck({ name: "app.exe", size: 10 })).toMatch(/non pris en charge/);
    expect(precheck({ name: "gros.pdf", size: MAX_BYTES + 1 })).toMatch(/20 Mo/);
    expect(precheck({ name: "vide.txt", size: 0 })).toBe("Fichier vide.");
    expect(ACCEPT).toContain(".pdf");
  });

  it("nomme les captures collées", () => {
    const at = new Date(2026, 9, 21, 9, 5, 7);
    expect(pastedName({ name: "image.png", type: "image/png" }, at)).toBe("capture-20261021-090507.png");
    expect(pastedName({ name: "", type: "image/jpeg" }, at)).toBe("capture-20261021-090507.jpg");
    expect(pastedName({ name: "schema.png", type: "image/png" }, at)).toBe("schema.png");
  });

  it("décrit le fichier", () => {
    expect(formatSize(512)).toBe("512 o");
    expect(formatSize(2048)).toBe("2 Ko");
    expect(formatSize(3.5 * 1024 * 1024)).toBe("3,5 Mo");
    expect(describeFile({ kind: "document", size: 1, meta: { pages: 3 } })).toBe("3 pages");
    expect(describeFile({ kind: "document", size: 1, meta: { sheets: ["A"] } })).toBe("1 feuille");
    expect(describeFile({ kind: "image", size: 1, meta: { width: 1568, height: 882 } })).toMatch(
      /1\s568 × 882/,
    );
    expect(describeFile({ kind: "document", size: 2048, meta: {} })).toBe("2 Ko");
    expect(fileFamily("ventes.csv", "text/csv")).toBe("sheet");
    expect(fileFamily("logo.svg", "image/svg+xml")).toBe("code");
  });

  it("produit le bloc du message", () => {
    const info = {
      id: "a".repeat(32),
      name: "n.pdf",
      media_type: "application/pdf",
      kind: "document" as const,
      size: 9,
      meta: {},
      created_at: "2026-10-21T00:00:00Z",
    };
    expect(toBlock(info)).toEqual({
      type: "attachment",
      id: info.id,
      name: "n.pdf",
      media_type: "application/pdf",
      kind: "document",
      size: 9,
    });
  });
});
