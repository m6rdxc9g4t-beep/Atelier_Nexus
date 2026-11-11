import { describe, expect, it, vi } from "vitest";

import { focusAfterRetry } from "./retryFocus";

describe("focusAfterRetry", () => {
  it("au clavier, le focus passe à la zone de saisie au lieu de tomber sur <body>", () => {
    const focus = vi.fn();
    expect(focusAfterRetry({ composer: { focus }, keyboard: true, coarse: false })).toBe(true);
    expect(focus).toHaveBeenCalledOnce();
  });

  it("à la souris aussi : on peut écrire la suite sans recliquer", () => {
    const focus = vi.fn();
    expect(focusAfterRetry({ composer: { focus }, keyboard: false, coarse: false })).toBe(true);
    expect(focus).toHaveBeenCalledOnce();
  });

  it("au doigt, rien ne bouge : le clavier à l'écran ne recouvre pas la réponse", () => {
    const focus = vi.fn();
    expect(focusAfterRetry({ composer: { focus }, keyboard: false, coarse: true })).toBe(false);
    expect(focus).not.toHaveBeenCalled();
  });

  it("sur une tablette avec un clavier branché, Entrée sur « Réessayer » garde le focus dans la page", () => {
    const focus = vi.fn();
    expect(focusAfterRetry({ composer: { focus }, keyboard: true, coarse: true })).toBe(true);
    expect(focus).toHaveBeenCalledOnce();
  });

  it("ne vise jamais une zone de saisie absente ou désactivée", () => {
    const focus = vi.fn();
    expect(focusAfterRetry({ composer: null, keyboard: true, coarse: false })).toBe(false);
    expect(focusAfterRetry({ composer: { disabled: true, focus }, keyboard: true, coarse: false })).toBe(false);
    expect(focus).not.toHaveBeenCalled();
  });
});
