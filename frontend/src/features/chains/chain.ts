/**
 * Logique pure des chaînes d'agents (testée dans chain.test.ts) : étape affichée, état de
 * l'étape courante, libellés du bandeau.
 */

import type { ChatTurn } from "@/features/chat-agent/conversation";
import type { ChainInfo, ChainRun } from "@/types/api";

/** Raison d'arrêt d'une réponse terminée, donc validable comme livrable. */
const FINISHED = new Set(["end_turn"]);

export type StageReadiness =
  | { ready: true }
  | { ready: false; reason: string };

/**
 * L'étape peut-elle être validée ? Il faut une réponse terminée de l'agent : ni validation
 * d'action ni revue de résultat en attente, pas d'erreur, pas d'arrêt demandé.
 */
export function stageReadiness(turns: ChatTurn[], streaming: boolean, saveError: string | null = null): StageReadiness {
  if (streaming) return { ready: false, reason: "L'agent travaille encore." };
  // Le serveur valide ce qu'il a enregistré : sans enregistrement, il figerait autre chose
  if (saveError) return { ready: false, reason: "La conversation n'est pas enregistrée : impossible de valider." };
  const last = turns.at(-1);
  if (!last || last.role !== "assistant") return { ready: false, reason: "L'agent n'a pas encore répondu." };
  if (last.error) return { ready: false, reason: "La dernière réponse a échoué : relancez ou corrigez." };
  const waiting = last.parts.some(
    (p) => (p.kind === "approval" && !p.submitted) || (p.kind === "review" && !p.decision),
  );
  if (waiting) return { ready: false, reason: "Une action ou un résultat attend votre validation." };
  const stop = last.meta?.stop_reason;
  if (stop === "stopped_by_user")
    return { ready: false, reason: "Vous avez arrêté l'agent : dites-lui comment poursuivre." };
  if (stop === "max_tokens")
    return { ready: false, reason: "Réponse tronquée : demandez à l'agent de la terminer." };
  if (!stop || !FINISHED.has(stop)) return { ready: false, reason: "L'étape n'est pas terminée." };
  return { ready: true };
}

/** Index de l'étape dont la conversation est affichée, ou null. */
export function stageOfConversation(run: ChainRun, conversationId: string | null): number | null {
  if (!conversationId) return null;
  const index = run.stages.findIndex((s) => s.conversation_id === conversationId);
  return index >= 0 ? index : null;
}

/** Texte du bouton de validation de l'étape courante. */
export function advanceLabel(run: ChainRun, chain: ChainInfo | undefined): string {
  const next = run.stage_index + 1;
  if (next >= run.stages.length) return "Valider et terminer la chaîne";
  const role = chain?.stages[next]?.role ?? run.stages[next]?.role ?? "étape suivante";
  return `Valider ce livrable → ${role}`;
}

/** « Étape 2/4 — Modèle en étoile » */
export function progressLabel(run: ChainRun): string {
  const stage = run.stages[run.stage_index];
  return `Étape ${run.stage_index + 1}/${run.stages.length}${stage ? ` — ${stage.role}` : ""}`;
}

export const RUN_STATUS_LABEL: Record<ChainRun["status"], string> = {
  running: "en cours",
  completed: "terminée",
  stopped: "arrêtée",
};
