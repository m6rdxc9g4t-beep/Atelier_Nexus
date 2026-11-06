/**
 * Contrat de la suite (SUITE.md §1.1) : copies verbatim du design system d'Atelier Projets.
 * Vérifie la présence des variables de fondation et des 15 couleurs officielles, et le
 * branchement de l'app sur la charte v2 « Linear » (styles/brand/atelier-brand.css).
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
    // Charte v2 : fond de page uni, police Inter de la marque, aucun halo ni texte lumineux
    expect(css).toContain("background: var(--atelier-bg);");
    expect(css).not.toContain("--atelier-backdrop");
    expect(css).toContain("--font-ui: var(--atelier-font);");
    expect(css).toContain("--shadow-glow: none;");
    expect(css).toContain("--text-shadow-glow: none;");
    // Aucune couleur de structure en dur : seules les palettes porteuses de sens (oklch des graphiques)
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/fonts\.googleapis/);
  });

  it("la marque v2 donne l'orange de Nexus, avec la police Inter embarquée", () => {
    const brand = read("../brand/atelier-brand.css");
    expect(brand).toContain("Atelier — marque commune et palette de la suite (v2");
    expect(brand).toContain("--atelier-sig-nexus: #c84f00;");
    expect(brand).toContain('url("./inter-latin-wght-normal.woff2")');
    expect(brand).toContain('url("./inter-latin-ext-wght-normal.woff2")');
    expect(read("../brand/LICENSE-Inter.txt")).toContain("SIL Open Font License");
    expect(read("../../app/layout.tsx")).toContain('data-atelier-app="nexus"');
  });

  it("la préférence de thème commune est posée avant l'affichage", () => {
    expect(read("../brand/atelier-theme.js")).toContain("window.atelierTheme = {");
    const script = read("../../components/theme/theme-script.tsx");
    expect(script).toContain("src/styles/brand/atelier-theme.js");
    expect(read("../../app/layout.tsx")).toContain("<ThemeScript />");
  });
});
