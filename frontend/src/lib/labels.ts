/**
 * Libellés uniques des moteurs d'IA (sélecteur du composer, méta des réponses ; à reprendre par
 * les Réglages et l'éditeur d'agent) et choix du moteur effectif d'une conversation.
 * Logique pure, testée dans labels.test.ts.
 */

import type { ProviderName, ProviderStatus } from "@/types/api";

/** Nom complet, dans les listes de choix. */
export const PROVIDER_LABEL: Record<ProviderName, string> = { anthropic: "Claude", ollama: "Ollama (local)" };

/** Nom court : badges, méta d'une réponse, puce du composer. */
export const PROVIDER_SHORT: Record<ProviderName, string> = { anthropic: "Claude", ollama: "Ollama" };

/** Pourquoi un moteur n'est pas prêt (« non configuré », « injoignable »), ou null. */
export function providerProblem(p: Pick<ProviderStatus, "configured" | "available">): string | null {
  if (!p.configured) return "non configuré";
  if (!p.available) return "injoignable";
  return null;
}

/**
 * Moteur qui répondra : un agent « 100 % local » est verrouillé sur Ollama ; sinon le choix de
 * l'utilisateur, puis le défaut de l'agent, puis celui du serveur (même règle que le backend).
 */
export function effectiveProvider(
  agent: { local_only?: boolean; default_provider?: ProviderName | null } | undefined,
  choice: ProviderName | null,
  providers: Pick<ProviderStatus, "name" | "is_default">[],
): ProviderName | undefined {
  if (agent?.local_only) return "ollama";
  return choice ?? agent?.default_provider ?? providers.find((p) => p.is_default)?.name;
}
