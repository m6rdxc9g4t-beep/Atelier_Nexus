/**
 * Contrat de la suite (SUITE.md §1.1) : copies verbatim du design system d'Atelier Projets.
 * Vérifie la présence des variables de fondation et des 15 couleurs officielles, et le
 * branchement de l'app sur la charte « néon monochrome » (styles/brand/atelier-brand.css).
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const read = (name: string) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

const FOUNDATION = ["--bg-main", "--bg-surface", "--bg-elevated", "--text-primary", "--text-muted", "--border-color"];

const OFFICIAL: Record<string, string> = {
  "--type-phase": "#FF8F2B",
  "--type-milestone": "#2A9A30",
  "--type-epic": "#8250DF",
  "--type-story": "#6F42C1",
  "--type-feature": "#2A9A30",
  "--type-task": "#1B66A3",
  "--type-bug": "#D64545",
  "--status-open": "#64748B",
  "--status-progress": "#2563EB",
  "--status-review": "#8B5CF6",
  "--status-hold": "#F59E0B",
  "--status-blocked": "#EA580C",
  "--status-resolved": "#0D9488",
  "--status-closed": "#16A34A",
  "--status-rejected": "#DC2626",
};

describe("design system de la suite Atelier", () => {
  it.each(["light.css", "dark.css"])("%s définit les 6 variables de fondation", (file) => {
    const css = read(file);
    expect(css).toContain("Atelier_Projets · Design System");
    for (const v of FOUNDATION) expect(css).toMatch(new RegExp(`${v}:\\s*#[0-9A-Fa-f]{6}`));
  });

  it("colors.css contient les 15 couleurs officielles", () => {
    const css = read("colors.css");
    for (const [name, hex] of Object.entries(OFFICIAL)) expect(css).toContain(`${name}: ${hex};`);
  });

  it("globals.css importe le design system et la marque, et branche Shadcn sur les jetons --atelier-*", () => {
    const css = read("../../app/globals.css");
    for (const f of ["light.css", "dark.css", "colors.css"]) expect(css).toContain(`atelier-ds/${f}`);
    expect(css).toContain("styles/brand/atelier-brand.css");
    for (const decl of [
      "--background: var(--atelier-bg);",
      "--foreground: var(--atelier-text);",
      "--card: var(--atelier-surface);",
      "--primary: var(--atelier-signature);",
      "--muted-foreground: var(--atelier-muted);",
      "--border: var(--atelier-line);",
      "--sidebar: var(--atelier-sidebar);",
    ])
      expect(css).toContain(decl);
    // Fond de page : raccourci background (jamais background-image), fixé au défilement
    expect(css).toContain("background: var(--atelier-backdrop), var(--atelier-bg);");
    expect(css).toContain("background-attachment: fixed;");
    expect(css).not.toMatch(/background-image:\s*var\(--atelier-backdrop\)/);
    // Aucune couleur de structure en dur : seules les palettes porteuses de sens (oklch des graphiques)
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/fonts\.googleapis/);
  });

  it("la marque est dans l'orange de Nexus, avec sa police embarquée", () => {
    const brand = read("../brand/atelier-brand.css");
    expect(brand).toContain("--atelier-sig-nexus: #e8590c;");
    expect(brand).toContain('url("./nunito-latin-wght-normal.woff2")');
    expect(read("../brand/OFL-Nunito.txt")).toContain("SIL OPEN FONT LICENSE");
    expect(read("../../app/layout.tsx")).toContain('data-atelier-app="nexus"');
  });
});
