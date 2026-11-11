/**
 * Règles « au doigt » de globals.css (pointeur grossier : téléphone, tablette). Le rendu se vérifie
 * dans un navigateur ; ce test garde les règles en place et hors d'atteinte des utilitaires.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("globals.css", import.meta.url)), "utf8");

/** Composants de l'application (hors tests) : les règles au doigt s'appuient sur leur balisage. */
const root = fileURLToPath(new URL("..", import.meta.url));
const sources = readdirSync(root, { recursive: true, encoding: "utf8" })
  .filter((file) => file.endsWith(".tsx"))
  .map((file) => ({ file, text: readFileSync(join(root, file), "utf8") }));

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

  it("boutons, entrées de menu et champs font au moins 40 px, sans toucher à la densité à la souris", () => {
    const at = css.indexOf("min-height: 2.5rem;");
    expect(at).toBeGreaterThan(0);
    const media = css.lastIndexOf("@media (pointer: coarse)", at);
    const rules = block(css, media);
    for (const target of ["button:not(", 'a[data-slot="button"]', '[role="menuitem"]', "summary", "input:not(", "select"])
      expect(rules).toContain(target);
    expect(rules).toContain("min-width: 2.5rem;");
    // Cases à cocher et interrupteurs (boutons Radix) gardent leur taille : leur libellé est cliquable
    expect(rules.match(/button:not\(\[role="checkbox"\], \[role="switch"\]\)/g)).toHaveLength(2);
    // Aucune taille minimale hors du bloc « au doigt » : la souris garde les 24 à 30 px de la charte
    expect(css.replace(rules, "")).not.toContain("min-height: 2.5rem;");
    // Couche « components » : un utilitaire explicite (min-h-*, min-w-*) garde la main
    expect(layerAt(css, media)).toBe("components");
  });

  it("un bouton radio est lui-même la cible : il fait 40 px comme les autres boutons", () => {
    const rules = block(css, css.lastIndexOf("@media (pointer: coarse)", css.indexOf("min-height: 2.5rem;")));
    // Les `[type="radio"]` restants sont ceux des champs natifs, dont le libellé est cliquable
    expect(rules).not.toContain('[role="radio"]');
    // La règle ne vaut que si chaque `role="radio"` de l'application est un vrai bouton
    const radios = sources.flatMap(({ file, text }) =>
      [...text.matchAll(/role="radio"/g)].map((match) => {
        const open = text.lastIndexOf("<", match.index);
        return { file, tag: /^<([A-Za-z.]+)/.exec(text.slice(open))?.[1] };
      }),
    );
    expect(radios.length).toBeGreaterThan(0);
    for (const radio of radios) expect(["button", "Button"], radio.file).toContain(radio.tag);
  });
});
