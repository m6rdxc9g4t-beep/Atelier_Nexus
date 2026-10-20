/**
 * Miroirs TypeScript des schémas Pydantic du backend.
 * Sources : app/core/llm/types.py, app/agents/base.py, app/tools/base.py,
 * app/core/llm/router.py, app/schemas/data_via.py, app/api/errors.py.
 */

export type ProviderName = "anthropic" | "ollama";

// ─── Conversation (format neutre) ────────────────────────────────

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  tool_name: string;
  content: string;
  is_error: boolean;
}

export type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock;

export interface Message {
  role: "user" | "assistant";
  content: ContentBlock[];
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
}

// ─── Artefacts ───────────────────────────────────────────────────

export type ArtifactKind =
  | "sql"
  | "dax"
  | "powerquery"
  | "python"
  | "react"
  | "code"
  | "markdown"
  | "json"
  | "data_preview";

export interface Artifact {
  kind: ArtifactKind;
  title: string;
  content: string;
  language: string | null;
  metadata: Record<string, unknown>;
}

// ─── Agents ──────────────────────────────────────────────────────

export interface ToolInfo {
  name: string;
  description: string;
}

export interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  tools: ToolInfo[];
  /** Champs facultatifs, fournis par le catalogue d'agents (Étape 5). */
  icon?: string | null;
  category?: string | null;
  starters?: string[];
}

export type StopReason =
  | "end_turn"
  | "tool_use"
  | "max_tokens"
  | "stop_sequence"
  | "refusal"
  | "other"
  | "max_iterations";

export interface AgentResult {
  agent: string;
  provider: ProviderName;
  model: string;
  text: string;
  stop_reason: StopReason;
  iterations: number;
  usage: Usage;
  artifacts: Artifact[];
  new_messages: Message[];
}

export interface AgentRunRequest {
  messages: Message[];
  provider?: ProviderName | null;
  model?: string | null;
  conversation_id?: string | null;
}

/** Événements du flux SSE de `POST /api/agents/{name}/stream`. */
export type AgentEvent =
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; content: string; is_error: boolean }
  | { type: "artifact"; artifact: Artifact }
  | { type: "done"; result: AgentResult }
  | { type: "error"; code: string; message: string; provider: string | null };

// ─── Supervision ─────────────────────────────────────────────────

export interface ProviderStatus {
  name: ProviderName;
  configured: boolean;
  available: boolean;
  is_default: boolean;
  is_fallback: boolean;
  default_model: string;
  models: string[];
  error: string | null;
}

export interface DataViaStatus {
  configured: boolean;
  available: boolean;
  base_url: string | null;
  version: string | null;
  datasets: number | null;
  error: string | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; provider: string | null };
}

// ─── Data Via (aperçus) ──────────────────────────────────────────

export interface QueryColumn {
  key: string;
  field: string | null;
  role: "dimension" | "measure" | "grouping";
  type: "number" | "string" | "date" | "boolean";
}

export type Scalar = string | number | boolean | null;
