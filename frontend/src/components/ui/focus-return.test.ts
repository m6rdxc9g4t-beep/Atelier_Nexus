import { describe, expect, it, vi } from "vitest";

import { rememberOpener, returnFocus } from "./focus-return";

describe("rememberOpener", () => {
  const body = { name: "body" };
  const button = { name: "bouton Réglages" };
  const field = { name: "champ de la fenêtre" };
  const content = { contains: (node: { name: string }) => node === field };

  it("retient l'élément qui avait le focus à l'ouverture", () => {
    expect(rememberOpener(button, content, body)).toBe(button);
  });

  it("ignore <body> : rien n'avait le focus (clic sur un bouton dans Safari)", () => {
    expect(rememberOpener(body, content, body)).toBeNull();
    expect(rememberOpener(null, content, body)).toBeNull();
  });

  it("ignore un élément de la fenêtre elle-même (champ en autoFocus)", () => {
    expect(rememberOpener(field, content, body)).toBeNull();
  });
});

describe("returnFocus", () => {
  it("rend le focus à l'élément d'origine", () => {
    const focus = vi.fn();
    expect(returnFocus({ isConnected: true, focus })).toBe(true);
    expect(focus).toHaveBeenCalledOnce();
  });

  it("laisse la main à Radix si l'élément a disparu ou n'a pas été retenu", () => {
    const focus = vi.fn();
    expect(returnFocus({ isConnected: false, focus })).toBe(false);
    expect(returnFocus(null)).toBe(false);
    expect(focus).not.toHaveBeenCalled();
  });
});
