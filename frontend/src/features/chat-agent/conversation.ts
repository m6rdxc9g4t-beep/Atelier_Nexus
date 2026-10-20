/**
 * Logique pure d'une conversation : application des événements du flux d'agent
 * sur l'état affiché. Sans React ni réseau, donc testable (conversation.test.ts).
 */

import type { AgentEvent, AgentResult, Message, PendingCall } from "@/types/api";

export interface ToolCallPart {
  kind: "tool";
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: "running" | "done" | "error";
  result?: string;
}

export interface TextPart {
  kind: "text";
  text: string;
}

export interface ArtifactRefPart {
  kind: "artifact";
  artifactId: string;
  title: string;
}

/** Actions en attente de la validation de l'utilisateur. */
export interface ApprovalPart {
  kind: "approval";
  calls: PendingCall[];
  /** Décision par appel, une fois prise ; tant qu'il en manque, la carte reste active. */
  decisions: Record<string, boolean>;
  submitted: boolean;
}

export type Part = TextPart | ToolCallPart | ArtifactRefPart | ApprovalPart;

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  parts: Part[];
  /** Méta du tour assistant, connue à la fin du flux. */
  meta?: Pick<AgentResult, "provider" | "model" | "usage" | "stop_reason" | "iterations">;
  error?: string;
}

export interface Conversation {
  turns: ChatTurn[];
  /** Historique au format API, renvoyé au backend à chaque tour. */
  history: Message[];
}

export const emptyConversation = (): Conversation => ({ turns: [], history: [] });

let seq = 0;
export const turnId = () => `t_${Date.now().toString(36)}_${(seq++).toString(36)}`;

export function addUserTurn(conv: Conversation, text: string): Conversation {
  const message: Message = { role: "user", content: [{ type: "text", text }] };
  return {
    turns: [
      ...conv.turns,
      { id: turnId(), role: "user", parts: [{ kind: "text", text }] },
      { id: turnId(), role: "assistant", parts: [] },
    ],
    history: [...conv.history, message],
  };
}

function updateLast(conv: Conversation, update: (turn: ChatTurn) => ChatTurn): Conversation {
  const turns = conv.turns.slice();
  const last = turns.at(-1);
  if (!last || last.role !== "assistant") return conv;
  turns[turns.length - 1] = update(last);
  return { ...conv, turns };
}

/**
 * Applique un événement au dernier tour assistant.
 * `artifactId` : identifiant attribué par le store d'artefacts (événement `artifact`).
 */
export function applyEvent(
  conv: Conversation,
  event: AgentEvent,
  artifactId?: string,
): Conversation {
  switch (event.type) {
    case "text_delta":
      return updateLast(conv, (turn) => {
        const parts = turn.parts.slice();
        const tail = parts.at(-1);
        if (tail?.kind === "text") parts[parts.length - 1] = { ...tail, text: tail.text + event.text };
        else parts.push({ kind: "text", text: event.text });
        return { ...turn, parts };
      });

    case "tool_call":
      return updateLast(conv, (turn) => ({
        ...turn,
        parts: [
          ...turn.parts,
          { kind: "tool", id: event.id, name: event.name, input: event.input, status: "running" },
        ],
      }));

    case "tool_result":
      return updateLast(conv, (turn) => ({
        ...turn,
        parts: turn.parts.map((p) =>
          p.kind === "tool" && p.id === event.id
            ? { ...p, status: event.is_error ? "error" : "done", result: event.content }
            : p,
        ),
      }));

    case "approval_required":
      return updateLast(conv, (turn) => ({
        ...turn,
        parts: [...turn.parts, { kind: "approval", calls: event.calls, decisions: {}, submitted: false }],
      }));

    case "artifact":
      if (!artifactId) return conv;
      return updateLast(conv, (turn) => ({
        ...turn,
        parts: [...turn.parts, { kind: "artifact", artifactId, title: event.artifact.title }],
      }));

    case "done": {
      const { provider, model, usage, stop_reason, iterations, new_messages } = event.result;
      const next = updateLast(conv, (turn) => ({
        ...turn,
        meta: { provider, model, usage, stop_reason, iterations },
      }));
      return { ...next, history: [...conv.history, ...new_messages] };
    }

    case "error":
      return failLastTurn(conv, event.message);
  }
}

/**
 * Échec du tour : le message utilisateur sans réponse est retiré de l'historique API
 * (il reste affiché), pour que la conversation puisse continuer.
 */
export function failLastTurn(conv: Conversation, message: string): Conversation {
  const failed = updateLast(conv, (turn) => ({
    ...turn,
    error: message,
    parts: turn.parts.map((p) => (p.kind === "tool" && p.status === "running" ? { ...p, status: "error" } : p)),
  }));
  const history = conv.history.slice();
  if (history.at(-1)?.role === "user") history.pop();
  return { ...failed, history };
}

/** Carte de validation en attente (dernière partie du dernier tour), s'il y en a une. */
export function pendingApproval(conv: Conversation): ApprovalPart | null {
  const last = conv.turns.at(-1);
  const part = last?.role === "assistant" ? last.parts.findLast((p) => p.kind === "approval") : undefined;
  return part && part.kind === "approval" && !part.submitted ? part : null;
}

/** Enregistre les décisions et fige la carte ; renvoie aussi les validations à envoyer. */
export function submitApprovals(
  conv: Conversation,
  decisions: Record<string, boolean>,
): { conv: Conversation; approvals: Record<string, boolean> } | null {
  const pending = pendingApproval(conv);
  if (!pending || pending.calls.some((c) => decisions[c.id] === undefined)) return null;
  const approvals = Object.fromEntries(pending.calls.map((c) => [c.id, decisions[c.id] === true]));
  const next = updateLast(conv, (turn) => ({
    ...turn,
    parts: turn.parts.map((p) =>
      p === pending ? { ...pending, decisions: approvals, submitted: true } : p,
    ),
  }));
  return { conv: next, approvals };
}
