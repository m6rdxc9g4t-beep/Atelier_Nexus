/**
 * Règles « au doigt » de globals.css (pointeur grossier : téléphone, tablette). Le rendu se vérifie
 * dans un navigateur ; ce test garde les règles en place et hors d'atteinte des utilitaires.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("globals.css", import.meta.url)), "utf8");

/** Contenu d'un bloc `{ … }` à partir de l'accolade ouvrante qui suit `from`. */
function block(source: string, from: number): string {
  const start = source.indexOf("{", from);
  let depth = 0;
  for (let i = start; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return source.slice(start + 1, i);
  }
  throw new Error("bloc non fermé");
}

/** Couche CSS (`@layer x`) qui contient la position donnée, ou null hors couche. */
function layerAt(source: string, index: number): string | null {
  for (const match of source.matchAll(/@layer\s+([a-z]+)\s*\{/g)) {
    const body = block(source, match.index);
    const start = source.indexOf("{", match.index) + 1;
    if (index >= start && index < start + body.length) return match[1] ?? null;
  }
  return null;
}

describe("au doigt (pointer: coarse)", () => {
  it("les champs de saisie font 16 px : iOS n'agrandit plus la page au focus", () => {
    const at = css.indexOf("font-size: 1rem;");
    expect(at).toBeGreaterThan(0);
    const media = css.lastIndexOf("@media (pointer: coarse)", at);
    const rules = block(css, media);
    expect(rules).toContain("font-size: 1rem;");
    for (const field of ["input:not(", "textarea", "select"]) expect(rules).toContain(field);
    // Cases, boutons radio, curseurs et sélecteurs de fichier ne sont pas des champs de texte
    expect(rules).toMatch(/input:not\(\[type="checkbox"\], \[type="radio"\], \[type="range"\], \[type="file"\]\)/);
    // Hors couche : sinon `text-sm` (couche des utilitaires) l'emporterait et le zoom reviendrait
    expect(layerAt(css, media)).toBeNull();
  });
});
