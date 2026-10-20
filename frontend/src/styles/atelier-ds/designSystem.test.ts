/**
 * Contrat de la suite (SUITE.md §1.1) : copies verbatim du design system d'Atelier Projets.
 * Vérifie la présence des variables de fondation et des 15 couleurs officielles.
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

  it("globals.css importe les trois fichiers et dérive l'accent de --type-epic", () => {
    const css = read("../../app/globals.css");
    for (const f of ["light.css", "dark.css", "colors.css"]) expect(css).toContain(`atelier-ds/${f}`);
    expect(css).toContain("--primary: var(--type-epic);");
    expect(css).not.toMatch(/fonts\.googleapis/);
  });
});
