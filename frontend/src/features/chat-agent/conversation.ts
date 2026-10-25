/**
 * Logique pure d'une conversation : application des événements du flux d'agent
 * sur l'état affiché. Sans React ni réseau, donc testable (conversation.test.ts).
 */

import type {
  AgentEvent,
  AgentResult,
  AttachmentBlock,
  ContentBlock,
  ConversationDetail,
  Message,
  PendingCall,
} from "@/types/api";

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

/** Fichier joint à un message de l'utilisateur. */
export interface AttachmentPart {
  kind: "attachment";
  attachment: AttachmentBlock;
}

export type Part = TextPart | ToolCallPart | ArtifactRefPart | ApprovalPart | AttachmentPart;

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

/** Pièces jointes d'abord (le modèle lit le fichier avant la question), puis le texte. */
export function addUserTurn(conv: Conversation, text: string, attachments: AttachmentBlock[] = []): Conversation {
  const content: ContentBlock[] = [...attachments];
  if (text) content.push({ type: "text", text });
  const parts: Part[] = attachments.map((attachment) => ({ kind: "attachment", attachment }));
  if (text) parts.push({ kind: "text", text });
  return {
    turns: [...conv.turns, { id: turnId(), role: "user", parts }, { id: turnId(), role: "assistant", parts: [] }],
    history: [...conv.history, { role: "user", content }],
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

    case "saved":
    case "save_error":
      return conv; // gérés par le store (historique), sans effet sur l'affichage
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

/**
 * Reconstruit l'affichage d'une conversation enregistrée.
 * Un tour assistant va d'une question de l'utilisateur à la suivante ; les résultats d'outils
 * (messages `user` sans texte) complètent les appels du tour en cours.
 * `artifactIds` : identifiant serveur → identifiant dans le store d'artefacts.
 */
export function fromStored(detail: ConversationDetail, artifactIds: Record<string, string>): Conversation {
  const turns: ChatTurn[] = [];
  let current: ChatTurn | null = null;
  const toolParts = new Map<string, ToolCallPart>();
  let lastAssistantIndex: Record<string, number> = {};

  detail.history.forEach((message, index) => {
    const results = message.content.filter((b) => b.type === "tool_result");
    if (message.role === "user" && results.length === 0) {
      const parts: Part[] = [];
      for (const b of message.content) {
        if (b.type === "attachment") parts.push({ kind: "attachment", attachment: b });
        else if (b.type === "text") parts.push({ kind: "text", text: b.text });
      }
      turns.push({ id: turnId(), role: "user", parts });
      current = null;
      return;
    }
    if (message.role === "user") {
      for (const r of results) {
        const part = toolParts.get(r.tool_use_id);
        if (part) {
          part.status = r.is_error ? "error" : "done";
          part.result = r.content;
        }
      }
      return;
    }
    if (!current) {
      current = { id: turnId(), role: "assistant", parts: [] };
      turns.push(current);
    }
    for (const block of message.content) {
      if (block.type === "text" && block.text) current.parts.push({ kind: "text", text: block.text });
      if (block.type === "tool_use") {
        const part: ToolCallPart = { kind: "tool", id: block.id, name: block.name, input: block.input, status: "running" };
        toolParts.set(block.id, part);
        current.parts.push(part);
      }
    }
    lastAssistantIndex = { ...lastAssistantIndex, [current.id]: index };
  });

  // Méta et artefacts rattachés à la fin de chaque tour assistant
  for (const turn of turns) {
    const end = lastAssistantIndex[turn.id];
    if (end === undefined) continue;
    const meta = detail.turn_meta[String(end)];
    if (meta) {
      const { provider, model, usage, stop_reason, iterations } = meta;
      turn.meta = { provider, model, usage, stop_reason, iterations };
    }
  }
  for (const artifact of detail.artifacts) {
    const owner = [...turns]
      .reverse()
      .find((t) => t.role === "assistant" && (lastAssistantIndex[t.id] ?? Infinity) < artifact.position);
    const id = artifactIds[artifact.id];
    if (owner && id) owner.parts.push({ kind: "artifact", artifactId: id, title: artifact.title });
  }

  // Validations restées en attente à la fin du dernier tour
  const last = turns.at(-1);
  if (detail.pending_approvals.length && last?.role === "assistant") {
    last.parts.push({ kind: "approval", calls: detail.pending_approvals, decisions: {}, submitted: false });
  }
  // Appels sans résultat : en attente de validation (exécutés à la reprise, donc masqués comme
  // dans le flux en direct), sinon tour interrompu (affichés en erreur, jamais « en cours »).
  const waiting = detail.pending_approvals.length > 0;
  for (const turn of turns) {
    turn.parts = turn.parts.filter((p) => !(waiting && p.kind === "tool" && p.status === "running"));
    for (const p of turn.parts) if (p.kind === "tool" && p.status === "running") p.status = "error";
  }

  return { turns, history: detail.history };
}

/** Outils qui n'ont pas de sens sans modèle : ils ne suffisent pas à proposer un workflow. */
const NOT_REPLAYABLE = new Set(["current_datetime", "delegate_to_agent"]);

/** Actions réussies et rejouables sans modèle d'un tour (« Rejouer ces n actions »). */
export function replayableCount(turn: ChatTurn): number {
  return turn.parts.filter((p) => p.kind === "tool" && p.status === "done" && !NOT_REPLAYABLE.has(p.name)).length;
}

/** Le tour peut devenir un workflow : terminé, sans erreur, avec une action réussie et rejouable. */
export function canSaveAsWorkflow(turn: ChatTurn): boolean {
  return (
    turn.role === "assistant" &&
    !!turn.meta &&
    turn.meta.stop_reason !== "awaiting_approval" &&
    !turn.error &&
    replayableCount(turn) > 0
  );
}
