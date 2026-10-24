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

/** Pièce jointe d'un message utilisateur : référence au fichier importé (POST /api/attachments). */
export interface AttachmentBlock {
  type: "attachment";
  id: string;
  name: string;
  media_type: string;
  kind: AttachmentKind;
  size: number;
}

export type AttachmentKind = "image" | "document";

export type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | AttachmentBlock;

/** Fichier importé (Étape 15). */
export interface AttachmentInfo {
  id: string;
  name: string;
  media_type: string;
  kind: AttachmentKind;
  size: number;
  meta: AttachmentMeta;
  created_at: string;
}

export interface AttachmentMeta {
  pages?: number;
  sheets?: string[];
  rows?: number;
  chars?: number;
  width?: number;
  height?: number;
  /** Motif d'une coupure (document très long, image animée…) */
  truncated?: string;
}

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
  | "data_preview"
  /** Graphique calculé par les outils d'analyse (format `atelier-chart/1`). */
  | "chart";

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
  /** Nom lisible fourni par le backend (outils des extensions compris). */
  label?: string;
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

/** Nature d'un appel sur la carte de validation (« Lecture », « Écriture », « Délégation »). */
export type CallKind = "read" | "write" | "delegation";

export interface PendingCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
  summary: string;
  /** Absent des tours enregistrés avant la validation de chaque action : écriture. */
  kind?: CallKind;
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
export type SettingsGroup = "Validation des actions" | "Modèles" | "Applications Atelier" | "Atelier Cuisine" | "GitHub";

/** Réglage APPROVAL_MODE : chaque action (défaut, recommandé) ou seulement les écritures. */
export type ApprovalMode = "every_step" | "writes_only";

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

// ─── Workflows rejouables (Étape 18) ─────────────────────────────

export interface WorkflowStep {
  tool: string;
  input: Record<string, unknown>;
  label: string;
}

export interface WorkflowParam {
  name: string;
  label: string;
  default: string;
}

export interface WorkflowFields {
  title: string;
  description: string;
  steps: WorkflowStep[];
  params: WorkflowParam[];
}

export interface WorkflowCreate extends WorkflowFields {
  agent: string;
  source_conversation_id?: string | null;
}

export interface Workflow extends WorkflowCreate {
  id: string;
  run_count: number;
  last_run_at: string | null;
  /** stopped = une écriture refusée a arrêté le workflow */
  last_status: "completed" | "failed" | "stopped" | null;
  created_at: string;
  updated_at: string;
}

/** Proposition tirée du dernier tour d'une conversation (rien n'est encore enregistré). */
export interface WorkflowDraft {
  agent: string;
  title: string;
  description: string;
  steps: WorkflowStep[];
  skipped: { tool: string; reason: string }[];
  /** Numéros (à partir de 1) des étapes qui modifient des données. */
  writes: number[];
}

export type StepStatus = "ok" | "error" | "refused" | "skipped";

export interface StepResult {
  index: number;
  tool: string;
  label: string;
  input: Record<string, unknown>;
  status: StepStatus;
  content: string;
}

export interface PendingStep {
  index: number;
  tool: string;
  summary: string;
  /** À renvoyer dans `approvals` : ne vaut que pour cette action (valeurs, version). */
  token: string;
  /** Lecture : seulement en APPROVAL_MODE=every_step */
  kind?: "read" | "write";
}

export interface WorkflowRunResult {
  status: "completed" | "failed" | "stopped" | "awaiting_approval";
  message: string;
  steps: StepResult[];
  artifacts: Artifact[];
  pending: PendingStep[];
}

// ─── Workflows v2 : graphe d'étapes inter-applications (docs/workflows-v2-api.md) ───

/** "tool:<nom_outil>" | "node:<app>/<action_id>" */
export type StepUses = string;

export type ConditionOp = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains" | "empty" | "not_empty";

/** L'étape ne s'exécute que si la condition est vraie (sinon « skipped »). */
export interface Condition {
  /** Gabarit, ex. "{{steps.lire.data.total}}" */
  left: string;
  op: ConditionOp;
  /** Absent pour empty / not_empty */
  right?: unknown;
}

export type OnError = "stop" | "continue";

export interface StepPosition {
  x: number;
  y: number;
}

export interface WorkflowStepV2 {
  /** ^[a-z][a-z0-9_]{0,39}$, unique dans le workflow */
  id: string;
  label: string;
  uses: StepUses;
  /** Valeurs littérales ou gabarits {{…}} (récursif dans objets / listes) */
  input: Record<string, unknown>;
  /** Étapes amont (arêtes du graphe) ; DAG obligatoire */
  needs: string[];
  when?: Condition | null;
  on_error: OnError;
  /** Placement dans l'éditeur, ignoré par le moteur */
  position?: StepPosition | null;
}

/** Corps de création, de modification et de validation d'un workflow v2. */
export interface WorkflowV2Fields {
  /** null = workflow de suite (toutes les boîtes configurées) */
  agent: string | null;
  title: string;
  description: string;
  steps: WorkflowStepV2[];
  params: WorkflowParam[];
}

export interface WorkflowV2Body extends WorkflowV2Fields {
  version: 2;
  source_conversation_id?: string | null;
}

export interface WorkflowV2 extends WorkflowV2Fields {
  id: string;
  version: 2;
  source_conversation_id: string | null;
  run_count: number;
  last_run_at: string | null;
  last_status: string | null;
  created_at: string;
  updated_at: string;
}

/** Workflow v1 tel que le renvoie `GET /api/workflows` (champ `version` à 1). */
export interface WorkflowV1 extends Workflow {
  version?: 1;
}

/** `GET /api/workflows` renvoie les deux versions ; `version` les distingue. */
export type AnyWorkflow = WorkflowV1 | WorkflowV2;

// ─── Catalogue des étapes ────────────────────────────────────────

export type ActionKind = "read" | "write" | "destructive";
export type OutputFormat = "atelier-table/1" | "json" | "text";
export type NodeAppStatus = "ok" | "unreachable" | "no_contract" | "not_configured";

export interface OutputColumnHint {
  key: string;
  label: string;
  type: string;
}

export interface OutputHint {
  columns?: OutputColumnHint[];
  fields?: string[];
}

export interface CatalogEntry {
  uses: StepUses;
  source: "tool" | "node";
  /** "viz" | "tab" | "projets" | "cine" | … | null (outil système) */
  app: string | null;
  label: string;
  description: string;
  /** Outil : requires_approval → "write" */
  kind: ActionKind;
  /** JSON Schema (portable_schema pour un outil) */
  input_schema: Record<string, unknown>;
  output_format: OutputFormat;
  output_hint: OutputHint | null;
  /** false si l'app n'est pas configurée / ne répond pas */
  available: boolean;
  unavailable_reason: string | null;
}

export interface CatalogApp {
  app: string;
  name: string;
  status: NodeAppStatus;
  color: string;
}

export interface Catalog {
  apps: CatalogApp[];
  entries: CatalogEntry[];
}

// ─── Validation ──────────────────────────────────────────────────

export type ValidationCode =
  | "DUPLICATE_ID"
  | "BAD_ID"
  | "UNKNOWN_USES"
  | "UNAVAILABLE"
  | "CYCLE"
  | "UNKNOWN_NEED"
  | "REF_NOT_ANCESTOR"
  | "UNDECLARED_PARAM"
  | "INPUT_INVALID"
  | "TOO_MANY_STEPS"
  | "NOT_REPLAYABLE"
  // Codes inconnus (version plus récente du backend) : affichés tels quels
  | (string & {});

export interface ValidationError {
  step_id: string | null;
  field: string | null;
  code: ValidationCode;
  message: string;
}

export interface ValidationResult {
  ok: boolean;
  errors: ValidationError[];
  /** Ordre d'exécution topologique si `ok` */
  order: string[];
}

// ─── Exécutions (persistées) ─────────────────────────────────────

export type RunStatus = "running" | "awaiting_approval" | "completed" | "failed" | "stopped";
export type StepRunStatus = "pending" | "ok" | "error" | "refused" | "skipped" | "awaiting_approval";

export interface StepRun {
  id: string;
  uses: string;
  label: string;
  status: StepRunStatus;
  /** Entrée résolue (null tant que non résolue) */
  input: Record<string, unknown> | null;
  /** Texte (≤ 4000 caractères) */
  content: string;
  /** Sortie structurée (tables tronquées à 1000 lignes, truncated: true) */
  data: unknown;
  error_code: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface PendingApproval {
  step_id: string;
  uses: string;
  /** read : seulement en APPROVAL_MODE=every_step (chaque étape attend une validation) */
  kind: ActionKind;
  summary: string;
  token: string;
  input: Record<string, unknown>;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  status: RunStatus;
  message: string;
  params: Record<string, string>;
  /** Origine du lancement (docs/declencheurs-api.md §2) */
  trigger: RunTrigger;
  /** Déclencheur à l'origine de l'exécution (horaire, événement, test) */
  trigger_id?: string | null;
  /** Événement source (jamais `data`) */
  trigger_event?: TriggerEventRef | null;
  /** Dans l'ordre d'exécution */
  steps: StepRun[];
  /** Même forme que le panneau Artefacts */
  artifacts: Artifact[];
  /** Au plus une étape à la fois */
  pending: PendingApproval[];
  created_at: string;
  updated_at: string;
}

// ─── Table d'échange atelier-table/1 (docs/apps/noeud-atelier.md §7.2) ──

export interface AtelierTable {
  format: "atelier-table/1";
  name: string;
  label: string;
  columns: { key: string; label: string; type: "string" | "number" | "date" | "datetime" | "boolean" }[];
  rows: Record<string, unknown>[];
  total: number | null;
  truncated: boolean;
}

// ─── Carte de la suite ───────────────────────────────────────────

export interface SuiteMapAction {
  id: string;
  label: string;
  kind: ActionKind;
  output_format: string;
}

export interface SuiteMapAgent {
  name: string;
  display_name: string;
  icon: string;
  toolsets: string[];
  writes: boolean;
}

export interface SuiteMapApp {
  app: string;
  name: string;
  color: string;
  status: NodeAppStatus;
  transport: "http" | "mcp" | "files" | null;
  /** Actions du manifeste */
  actions: SuiteMapAction[];
  events: { type: string; label: string }[];
  /** Outils Nexus qui touchent l'app */
  nexus_tools: { name: string; kind: "read" | "write"; toolset: string }[];
  agents: SuiteMapAgent[];
}

export interface SuiteFlow {
  from: string;
  to: string;
  label: string;
  via: string;
}

export interface SuiteMap {
  apps: SuiteMapApp[];
  flows: SuiteFlow[];
  /** Workflows qui touchent chaque app */
  workflows: { id: string; title: string; apps: string[] }[];
}

/** Événement d'une application (contrat atelier-node/1 §7.3). */
export interface AtelierEvent {
  seq: number;
  type: string;
  at: string;
  subject: { kind: string; id: string; label: string };
  data: Record<string, unknown>;
}

export interface SuiteEventsEntry {
  app: string;
  events: AtelierEvent[];
  next: number;
  gap?: boolean;
  status: string;
}

// ─── Déclencheurs de workflows (docs/declencheurs-api.md) ────────

export type RunTrigger = "manual" | "schedule" | "event" | "test";

/** Événement source d'une exécution, sans ses données. */
export interface TriggerEventRef {
  app: string;
  seq: number;
  type: string;
  at: string;
  subject: { kind: string; id: string; label: string };
}

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export type Schedule =
  /** 5 à 1440 minutes */
  | { kind: "interval"; every_minutes: number }
  /** "HH:MM" (24 h), au moins un jour ; fuseau = settings.timezone */
  | { kind: "daily"; at: string; days: Weekday[] };

export type EventFilterOp = "eq" | "ne" | "in" | "contains" | "gt" | "gte" | "lt" | "lte" | "exists";

/** Condition sur l'événement (toutes doivent être vraies). */
export interface EventFilter {
  /** "data.to", "subject.id", "subject.label", "type" */
  path: string;
  op: EventFilterOp;
  /** Liste pour "in" ; absent pour "exists" */
  value?: unknown;
}

/** Applications qui publient des événements (atelier-node/1 §7.3). */
export type TriggerApp = "viz" | "projets" | "tab";

export interface TriggerCounters {
  fired: number;
  throttled: number;
  waiting: number;
  filtered: number;
  missed: number;
  errors: number;
}

/** État tenu par le serveur (lecture seule). */
export interface TriggerState {
  /** Horaire : prochaine occurrence ; événement : null */
  next_fire_at: string | null;
  last_fired_at: string | null;
  last_run_id: string | null;
  last_run_status: string | null;
  /** Événement : dernier seq traité */
  cursor: number | null;
  counters: TriggerCounters;
  /** Ex. « Atelier Projets injoignable » ; effacé au premier succès */
  last_error: string | null;
  /** Ex. « Des événements ont été perdus (journal remis à zéro) » */
  warning: string | null;
}

/** Champs modifiables communs (corps de création et de modification). */
export interface TriggerBaseFields {
  /** "" autorisé */
  label: string;
  enabled: boolean;
  /** Valeurs des paramètres du workflow ; gabarits {{event.…}} permis (déclencheur événement) */
  params: Record<string, string>;
  /** 1 à 120, défaut 12 */
  max_runs_per_hour: number;
}

export interface ScheduleTriggerFields extends TriggerBaseFields {
  kind: "schedule";
  schedule: Schedule;
}

export interface EventTriggerFields extends TriggerBaseFields {
  kind: "event";
  app: TriggerApp;
  /** 1 à 10 types déclarés par le manifeste de l'app */
  types: string[];
  /** 0 à 10 */
  filters: EventFilter[];
  /** 0 à 3600, défaut 0 : une rafale donne un seul lancement (le dernier événement gagne) */
  debounce_seconds: number;
}

/** Corps de `POST /api/workflows/{id}/triggers` et `PUT /api/triggers/{id}`. */
export type TriggerBody = ScheduleTriggerFields | EventTriggerFields;

interface TriggerServerFields {
  /** Attribué par le serveur */
  id: string;
  workflow_id: string;
  created_at: string;
  updated_at: string;
  state: TriggerState;
}

export type ScheduleTrigger = ScheduleTriggerFields & TriggerServerFields;
export type EventTrigger = EventTriggerFields & TriggerServerFields;
export type Trigger = ScheduleTrigger | EventTrigger;

export interface EventsCatalogEvent {
  type: string;
  label: string;
  /** Chemins proposés pour les filtres (data.to, subject.id…) */
  fields: string[];
}

export interface EventsCatalogApp {
  app: TriggerApp;
  name: string;
  color: string;
  status: NodeAppStatus;
  events: EventsCatalogEvent[];
}

/** `GET /api/triggers/events-catalog` */
export interface EventsCatalog {
  apps: EventsCatalogApp[];
}

/** `GET /api/workflow-runs/inbox-count` */
export interface InboxCount {
  awaiting_approval: number;
}
