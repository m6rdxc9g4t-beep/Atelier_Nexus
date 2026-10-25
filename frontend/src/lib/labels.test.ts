import { describe, expect, it } from "vitest";

import { PROVIDER_LABEL, PROVIDER_SHORT, effectiveProvider, providerProblem } from "./labels";

const providers = [
  { name: "anthropic" as const, is_default: true },
  { name: "ollama" as const, is_default: false },
];

describe("libellés des moteurs", () => {
  it("nomme chaque moteur en long et en court", () => {
    expect(PROVIDER_LABEL.ollama).toBe("Ollama (local)");
    expect(PROVIDER_SHORT.ollama).toBe("Ollama");
    expect(PROVIDER_SHORT.anthropic).toBe("Claude");
  });

  it("dit pourquoi un moteur n'est pas prêt", () => {
    expect(providerProblem({ configured: false, available: false })).toBe("non configuré");
    expect(providerProblem({ configured: true, available: false })).toBe("injoignable");
    expect(providerProblem({ configured: true, available: true })).toBeNull();
  });
});

describe("effectiveProvider", () => {
  it("verrouille un agent local sur Ollama, quel que soit le choix", () => {
    expect(effectiveProvider({ local_only: true }, "anthropic", providers)).toBe("ollama");
  });

  it("prend le choix, puis le défaut de l'agent, puis celui du serveur", () => {
    expect(effectiveProvider({ default_provider: "ollama" }, "anthropic", providers)).toBe("anthropic");
    expect(effectiveProvider({ default_provider: "ollama" }, null, providers)).toBe("ollama");
    expect(effectiveProvider(undefined, null, providers)).toBe("anthropic");
    expect(effectiveProvider(undefined, null, [])).toBeUndefined();
  });
});
