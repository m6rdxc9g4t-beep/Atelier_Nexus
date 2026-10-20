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
  requires_approval?: boolean;
  sensitive?: boolean;
}

export type Privacy = "standard" | "local_only";

export interface AgentInfo {
  name: string;
  display_name: string;
  description: string;
  tools: ToolInfo[];
  icon?: string | null;
  category?: string | null;
  starters?: string[];
  source?: "builtin" | "custom";
  toolsets?: string[];
  privacy?: Privacy;
  /** Verrouillé sur le modèle local (déclaré, ou boîte à outils sensible). */
  local_only?: boolean;
  default_provider?: ProviderName | null;
  /** Boîtes déclarées mais écartées (application non configurée). */
  unavailable_toolsets?: string[];
}

export interface PendingCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
  summary: string;
}

export type StopReason =
  | "end_turn"
  | "tool_use"
  | "max_tokens"
  | "stop_sequence"
  | "refusal"
  | "other"
  | "max_iterations"
  | "awaiting_approval";

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
  pending_approvals?: PendingCall[];
}

export interface AgentRunRequest {
  messages: Message[];
  provider?: ProviderName | null;
  model?: string | null;
  conversation_id?: string | null;
  /** Reprise après validation : id d'appel → autorisé. */
  approvals?: Record<string, boolean> | null;
}

/** Événements du flux SSE de `POST /api/agents/{name}/stream`. */
export type AgentEvent =
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; content: string; is_error: boolean }
  | { type: "artifact"; artifact: Artifact }
  | { type: "approval_required"; calls: PendingCall[] }
  | { type: "done"; result: AgentResult }
  | { type: "saved"; conversation_id: string }
  | { type: "save_error"; message: string }
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
  error: { code: string; message: string; provider: string | null; fields?: Record<string, string> };
}

// ─── Data Via (aperçus) ──────────────────────────────────────────

export interface QueryColumn {
  key: string;
  field: string | null;
  role: "dimension" | "measure" | "grouping";
  type: "number" | "string" | "date" | "boolean";
}

export type Scalar = string | number | boolean | null;

// ─── Éditeur d'agents (Étape 5) ──────────────────────────────────

export interface ToolsetInfo {
  id: string;
  label: string;
  description: string;
  app: string | null;
  configured: boolean;
  sensitive: boolean;
  writes: boolean;
  tools: ToolInfo[];
}

export interface EditorOptions {
  icons: string[];
  toolsets: ToolsetInfo[];
  reserved_names: string[];
}

export interface CustomAgentFields {
  display_name: string;
  description: string;
  system_prompt: string;
  icon: string;
  category: string;
  toolsets: string[];
  privacy: Privacy;
  default_provider: ProviderName | null;
  starters: string[];
}

export interface CustomAgentDefinition extends CustomAgentFields {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface AppStatus {
  id: string;
  label: string;
  configured: boolean;
  available: boolean;
  base_url: string | null;
  detail: string | null;
  error: string | null;
}

// ─── Historique (Étape 6) ────────────────────────────────────────

export interface TurnMeta {
  provider: ProviderName;
  model: string;
  usage: Usage;
  stop_reason: StopReason;
  iterations: number;
}

export interface StoredArtifactDto extends Artifact {
  id: string;
  agent: string;
  position: number;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  agent: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  artifact_count: number;
}

/** Résultat de recherche : extrait autour du premier mot trouvé (Étape 13). */
export interface SearchHit extends ConversationSummary {
  snippet: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  history: Message[];
  artifacts: StoredArtifactDto[];
  turn_meta: Record<string, TurnMeta>;
  pending_approvals: PendingCall[];
}

// ─── Réglages (Étape 11) ─────────────────────────────────────────

export type SettingsKind = "text" | "url" | "secret" | "choice" | "path";
export type SettingsGroup = "Modèles" | "Applications Atelier" | "Atelier Cuisine" | "GitHub";

export interface SettingsField {
  key: string;
  label: string;
  group: SettingsGroup;
  kind: SettingsKind;
  help: string;
  choices: string[];
  /** Valeur effective ; null pour un secret (jamais renvoyé). */
  value: string | null;
  configured: boolean;
  /** Secret configuré : « …abcd ». */
  hint: string | null;
  source: "fichier" | "environnement" | "défaut";
}

export interface SettingsView {
  env_file: string;
  fields: SettingsField[];
}
