import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

const render = (text: string) => renderToStaticMarkup(createElement(Markdown, null, text));

describe("Markdown", () => {
  it("est mémoïsé : un texte inchangé n'est pas analysé de nouveau quand le fil se re-rend", () => {
    // Sans cela, chaque fragment d'une réponse en cours ré-analyse toutes les réponses déjà affichées
    expect((Markdown as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for("react.memo"));
  });

  it("rend les tableaux GFM et ouvre les liens dans un nouvel onglet, sans accès à la page d'origine", () => {
    const html = render("| a | b |\n|---|---|\n| 1 | 2 |\n\n[doc](https://example.org)");
    expect(html).toContain("<table>");
    expect(html).toContain('<a href="https://example.org" target="_blank" rel="noopener noreferrer">doc</a>');
  });

  it("n'interprète aucun HTML brut", () => {
    const html = render('Bonjour <img src=x onerror="alert(1)"> <script>alert(2)</script>');
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script");
  });
});
