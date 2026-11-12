/**
 * Coquille de l'application : la barre latérale occupe toute la hauteur de la fenêtre et reste en
 * place ; c'est le contenu qui défile, jamais la page. Le rendu se vérifie dans un navigateur (la
 * page ne doit pas pouvoir défiler : `document.documentElement.scrollHeight === innerHeight`) ; ce
 * test garde en place les règles qui l'assurent.
 *
 * Le défaut d'origine : un élément hors flux (`sr-only`, champ caché d'une case à cocher Radix :
 * `position: absolute`) placé dans une zone défilante NON positionnée n'est pas contenu par son
 * `overflow` — son bloc conteneur est plus haut. Il reste à sa place « sans défilement », loin sous
 * la fenêtre, allonge le document, et la page entière défile en emportant la barre latérale.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("../..", import.meta.url));
const sources = readdirSync(root, { recursive: true, encoding: "utf8" })
  .filter((file) => file.endsWith(".tsx"))
  .map((file) => ({ file, text: readFileSync(join(root, file), "utf8") }));
const read = (name: string) => readFileSync(fileURLToPath(new URL(name, import.meta.url)), "utf8");

/** Classes d'une chaîne (`"a b c"`), variantes comprises (`lg:block`). */
const classes = (literal: string) => literal.split(/\s+/).filter(Boolean);
/** Classe sans ses variantes : `sm:overflow-y-auto` → `overflow-y-auto` (une zone qui ne défile
 * qu'à partir d'une largeur suit la même règle). */
const bare = (cls: string) => cls.slice(cls.lastIndexOf(":") + 1);
const SCROLL_Y = ["overflow-y-auto", "overflow-auto", "overflow-y-scroll", "overflow-scroll"];
const POSITIONED = ["relative", "fixed", "absolute", "sticky"];

/** Chaînes littérales d'un fichier qui portent une des classes données, avec ou sans variante. */
function literalsWith(text: string, wanted: string[]): string[] {
  return [...text.matchAll(/"([^"\n]*)"/g)].map((m) => m[1] ?? "").filter((s) => classes(s).some((c) => wanted.includes(bare(c))));
}

/** Classes de l'élément qui porte `marker` (attribut ou classe) dans un fichier. */
function classNameNear(text: string, marker: string): string[] {
  const at = text.indexOf(marker);
  expect(at, `« ${marker} » introuvable`).toBeGreaterThan(0);
  const match = /className="([^"]*)"/.exec(text.slice(text.lastIndexOf("<", at)));
  return classes(match?.[1] ?? "");
}

describe("coquille : la page ne défile jamais", () => {
  const workspace = read("Workspace.tsx");
  const sidebar = read("AppSidebar.tsx");

  it("la racine fait la hauteur de la fenêtre et ne laisse rien en sortir", () => {
    const shell = classNameNear(workspace, 'data-slot="app-shell"');
    // Hauteur de la fenêtre (dynamique : barre d'adresse du téléphone comprise)
    expect(shell).toContain("h-dvh");
    // Bloc conteneur de tout élément hors flux oublié, et coupe sans jamais défiler (`clip`, pas
    // `hidden` : un focus sur un élément hors champ ferait défiler une zone `hidden`)
    expect(shell).toContain("relative");
    expect(shell).toContain("overflow-clip");
    expect(shell).not.toContain("overflow-hidden");
    // Jamais une hauteur minimale seule : la coquille grandirait avec son contenu
    expect(shell.some((c) => c.startsWith("min-h-"))).toBe(false);
  });

  it("la barre latérale occupe toute la hauteur et ne se comprime pas", () => {
    const aside = classNameNear(workspace, "<aside");
    for (const wanted of ["h-full", "shrink-0", "lg:block"]) expect(aside).toContain(wanted);
    // Ni `sticky` ni `fixed` : elle tient en place parce que la page ne défile pas
    for (const position of ["sticky", "fixed", "absolute"]) expect(aside).not.toContain(position);
  });

  it("dans la barre, seule la liste des agents défile : en-tête, navigation et pied restent visibles", () => {
    // Colonne de toute la hauteur dont un seul enfant s'étire et défile
    expect(classNameNear(sidebar, "flex h-full min-h-0 flex-col")).toEqual(["flex", "h-full", "min-h-0", "flex-col"]);
    const scrollers = literalsWith(sidebar, SCROLL_Y);
    expect(scrollers).toHaveLength(1);
    for (const wanted of ["min-h-0", "flex-1", "overflow-y-auto", "relative"]) expect(classes(scrollers[0] ?? "")).toContain(wanted);
    // La liste des agents est dans cette zone, le pied (applications, thème, réglages) après elle
    const list = sidebar.indexOf(scrollers[0] ?? "");
    const agents = sidebar.indexOf("<AgentSidebar");
    const foot = sidebar.indexOf("<ThemeToggle");
    expect(list).toBeLessThan(agents);
    expect(agents).toBeLessThan(foot);
    const footClasses = classNameNear(sidebar, "border-t border-atelier-line");
    expect(footClasses).toContain("shrink-0");
    expect(sidebar.lastIndexOf("<div", foot)).toBe(sidebar.lastIndexOf("<", sidebar.indexOf("border-t border-atelier-line")));
  });

  it("toute zone qui défile en hauteur est positionnée : ses éléments hors flux défilent avec elle", () => {
    const found = sources.flatMap(({ file, text }) => literalsWith(text, SCROLL_Y).map((literal) => ({ file, literal })));
    // Les zones de la coquille en font partie (sinon la recherche ne voit plus rien)
    for (const file of ["components/layout/AppSidebar.tsx", "features/home/HomeView.tsx", "features/chat-agent/ChatPanel.tsx", "features/workflows/WorkflowsStudio.tsx"])
      expect(found.map((f) => f.file.replaceAll("\\", "/"))).toContain(file);
    const loose = found.filter(({ literal }) => !classes(literal).some((c) => POSITIONED.includes(c)));
    expect(loose).toEqual([]);
    // Un défilement posé en style passerait sous cette règle : toujours par une classe
    for (const { file, text } of sources) expect(text, file).not.toMatch(/overflowY|overflow:\s*["'](auto|scroll)/);
  });
});
