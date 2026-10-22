/** Client HTTP typé de l'API Atelier Nexus. */

import { readSse } from "@/lib/sse";
import type {
  AgentEvent,
  AnyWorkflow,
  Catalog,
  AgentInfo,
  AgentRunRequest,
  Artifact,
  ApiErrorBody,
  AppStatus,
  AttachmentInfo,
  ChainInfo,
  ChainRun,
  ChainStep,
  ConversationDetail,
  ConversationSummary,
  CustomAgentDefinition,
  CustomAgentFields,
  DataViaStatus,
  EditorOptions,
  AtelierEvent,
  EventsCatalog,
  InboxCount,
  RunStatus,
  Trigger,
  TriggerBody,
  Message,
  ProviderStatus,
  SearchHit,
  SettingsView,
  SuiteEventsEntry,
  SuiteMap,
  ValidationResult,
  Workflow,
  WorkflowCreate,
  WorkflowDraft,
  WorkflowFields,
  WorkflowRun,
  WorkflowRunResult,
  WorkflowV2,
  WorkflowV2Body,
} from "@/types/api";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    /** Message par champ (réglages refusés). */
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Partial<ApiErrorBody> & { detail?: unknown };
    if (body.error)
      return new ApiError(body.error.message, response.status, body.error.code, body.error.fields ?? {});
    if (typeof body.detail === "string") return new ApiError(body.detail, response.status, "http");
    if (Array.isArray(body.detail)) {
      // Erreurs de validation FastAPI : « champ : message »
      const message = body.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")} : ${d.msg ?? ""}`)
        .join(" ; ");
      return new ApiError(message, response.status, "validation");
    }
  } catch {
    // corps non JSON
  }
  return new ApiError(`Erreur ${response.status}`, response.status, "http");
}

async function getJson<T>(path: string, signal?: AbortSignal, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { signal, cache: "no-store", ...init });
  } catch {
    throw new ApiError(
      `Le serveur Atelier Nexus ne répond pas (${API_URL}). Lancez le backend sur le port 8100.`,
      0,
      "network",
    );
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const sendJson = <T>(method: string, path: string, body?: unknown) =>
  getJson<T>(path, undefined, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/** Adresse du fichier joint (image affichée, autre fichier téléchargé). */
export const attachmentUrl = (id: string) => `${API_URL}/api/attachments/${encodeURIComponent(id)}/content`;

export const api = {
  /** Importe un fichier joint (texte extrait et image réduite côté serveur). */
  uploadAttachment: (file: File, signal?: AbortSignal) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return getJson<AttachmentInfo>("/api/attachments", signal, { method: "POST", body: form });
  },
  /** Retire un fichier joint pas encore envoyé. */
  removeAttachment: (id: string) => sendJson<void>("DELETE", `/api/attachments/${encodeURIComponent(id)}`),
  agents: (signal?: AbortSignal) => getJson<AgentInfo[]>("/api/agents", signal),
  providers: (signal?: AbortSignal) => getJson<ProviderStatus[]>("/api/llm/providers", signal),
  dataViaStatus: (signal?: AbortSignal) => getJson<DataViaStatus>("/api/data-via/status", signal),
  appsStatus: (signal?: AbortSignal) => getJson<AppStatus[]>("/api/apps/status", signal),
  editorOptions: (signal?: AbortSignal) => getJson<EditorOptions>("/api/toolsets", signal),
  customAgent: (name: string) =>
    getJson<CustomAgentDefinition>(`/api/custom-agents/${encodeURIComponent(name)}`),
  createAgent: (body: CustomAgentFields & { name: string }) =>
    sendJson<AgentInfo>("POST", "/api/custom-agents", body),
  updateAgent: (name: string, body: CustomAgentFields) =>
    sendJson<AgentInfo>("PUT", `/api/custom-agents/${encodeURIComponent(name)}`, body),
  deleteAgent: (name: string) =>
    sendJson<void>("DELETE", `/api/custom-agents/${encodeURIComponent(name)}`),
  conversations: (agent: string, signal?: AbortSignal) =>
    getJson<ConversationSummary[]>(`/api/conversations?agent=${encodeURIComponent(agent)}`, signal),
  conversation: (id: string) =>
    getJson<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`),
  /** Recherche (titre, messages, artefacts) ; `agent` null = tous les agents. */
  searchConversations: (query: string, agent: string | null, signal?: AbortSignal) => {
    const params = new URLSearchParams({ q: query });
    if (agent) params.set("agent", agent);
    return getJson<SearchHit[]>(`/api/conversations/search?${params.toString()}`, signal);
  },
  createConversation: (agent: string) =>
    sendJson<ConversationDetail>("POST", "/api/conversations", { agent }),
  renameConversation: (id: string, title: string) =>
    sendJson<ConversationDetail>("PATCH", `/api/conversations/${encodeURIComponent(id)}`, { title }),
  deleteConversation: (id: string) =>
    sendJson<void>("DELETE", `/api/conversations/${encodeURIComponent(id)}`),
  settings: (signal?: AbortSignal) => getJson<SettingsView>("/api/settings", signal),
  updateSettings: (values: Record<string, string | null>) =>
    sendJson<SettingsView>("PUT", "/api/settings", { values }),
  /** Chaînes d'agents (Étape 24). */
  chains: (signal?: AbortSignal) => getJson<ChainInfo[]>("/api/chains", signal),
  chainRuns: (chain: string | null, signal?: AbortSignal) =>
    getJson<ChainRun[]>(`/api/chain-runs${chain ? `?chain=${encodeURIComponent(chain)}` : ""}`, signal),
  chainRun: (id: string) => getJson<ChainRun>(`/api/chain-runs/${encodeURIComponent(id)}`),
  startChain: (chain: string, request: string) =>
    sendJson<ChainStep>("POST", `/api/chains/${encodeURIComponent(chain)}/runs`, { request }),
  /** Valide le livrable de l'étape courante (409 si elle n'est pas terminée). */
  advanceChain: (runId: string) =>
    sendJson<ChainStep>("POST", `/api/chain-runs/${encodeURIComponent(runId)}/advance`),
  /** Message de relais de l'étape en cours (à renvoyer si l'envoi n'a pas abouti). */
  chainHandoff: (runId: string) => getJson<ChainStep>(`/api/chain-runs/${encodeURIComponent(runId)}/handoff`),
  stopChain: (runId: string) => sendJson<ChainRun>("POST", `/api/chain-runs/${encodeURIComponent(runId)}/stop`),
  chainRecap: (runId: string) => getJson<Artifact>(`/api/chain-runs/${encodeURIComponent(runId)}/recap`),
  /** Workflows rejouables (Étape 18), v1 et v2 (champ `version`). `agent` null = tous. */
  workflows: (agent: string | null, signal?: AbortSignal) =>
    getJson<AnyWorkflow[]>(`/api/workflows${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`, signal),
  /** Propose un workflow à partir du dernier tour de la conversation (rien n'est enregistré). */
  captureWorkflow: (agent: string, messages: Message[]) =>
    sendJson<WorkflowDraft>("POST", "/api/workflows/capture", { agent, messages }),
  createWorkflow: (body: WorkflowCreate) => sendJson<Workflow>("POST", "/api/workflows", body),
  updateWorkflow: (id: string, body: WorkflowFields) =>
    sendJson<Workflow>("PUT", `/api/workflows/${encodeURIComponent(id)}`, body),
  deleteWorkflow: (id: string) => sendJson<void>("DELETE", `/api/workflows/${encodeURIComponent(id)}`),
  /** Lance sans modèle ; `approvals` : jeton de l'étape d'écriture (reçu dans `pending`) → autorisée. */
  runWorkflow: (id: string, params: Record<string, string>, approvals: Record<string, boolean> | null) =>
    sendJson<WorkflowRunResult>("POST", `/api/workflows/${encodeURIComponent(id)}/run`, { params, approvals }),

  // ─── Workflows v2 (docs/workflows-v2-api.md) ───
  /** Catalogue des étapes ; sans `agent` (null) : catalogue de suite. */
  workflowCatalog: (agent: string | null, signal?: AbortSignal) =>
    getJson<Catalog>(`/api/workflows/catalog${agent ? `?agent=${encodeURIComponent(agent)}` : ""}`, signal),
  workflow: (id: string, signal?: AbortSignal) =>
    getJson<AnyWorkflow>(`/api/workflows/${encodeURIComponent(id)}`, signal),
  validateWorkflow: (body: WorkflowV2Body, signal?: AbortSignal) =>
    getJson<ValidationResult>("/api/workflows/validate", signal, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createWorkflowV2: (body: WorkflowV2Body) => sendJson<WorkflowV2>("POST", "/api/workflows", body),
  updateWorkflowV2: (id: string, body: WorkflowV2Body) =>
    sendJson<WorkflowV2>("PUT", `/api/workflows/${encodeURIComponent(id)}`, body),
  /** v1 → v2, enregistré (ids s1..sn, chaîne linéaire de `needs`, `{{nom}}` → `{{params.nom}}`). */
  convertWorkflow: (id: string) =>
    sendJson<WorkflowV2>("POST", `/api/workflows/${encodeURIComponent(id)}/convert`),
  /** Lance un workflow v2 : l'exécution est persistée et suivie par `workflowRun`. */
  runWorkflowV2: (id: string, params: Record<string, string>) =>
    sendJson<WorkflowRun>("POST", `/api/workflows/${encodeURIComponent(id)}/run`, { params }),
  workflowRun: (runId: string, signal?: AbortSignal) =>
    getJson<WorkflowRun>(`/api/workflow-runs/${encodeURIComponent(runId)}`, signal),
  workflowRuns: (workflowId: string, limit = 20, signal?: AbortSignal) =>
    getJson<WorkflowRun[]>(
      `/api/workflow-runs?${new URLSearchParams({ workflow_id: workflowId, limit: String(limit) }).toString()}`,
      signal,
    ),
  /** `approvals` : jeton de l'étape en attente → autorisée. */
  resumeWorkflowRun: (runId: string, approvals: Record<string, boolean>) =>
    sendJson<WorkflowRun>("POST", `/api/workflow-runs/${encodeURIComponent(runId)}/resume`, { approvals }),

  // ─── Déclencheurs (docs/declencheurs-api.md) ───
  triggers: (workflowId: string, signal?: AbortSignal) =>
    getJson<Trigger[]>(`/api/workflows/${encodeURIComponent(workflowId)}/triggers`, signal),
  createTrigger: (workflowId: string, body: TriggerBody) =>
    sendJson<Trigger>("POST", `/api/workflows/${encodeURIComponent(workflowId)}/triggers`, body),
  /** Même corps que la création ; les compteurs sont conservés, `next_fire_at` recalculé. */
  updateTrigger: (triggerId: string, body: TriggerBody) =>
    sendJson<Trigger>("PUT", `/api/triggers/${encodeURIComponent(triggerId)}`, body),
  deleteTrigger: (triggerId: string) => sendJson<void>("DELETE", `/api/triggers/${encodeURIComponent(triggerId)}`),
  /** Lance une fois maintenant comme le ferait le déclencheur ; `event` : événement d'exemple. */
  testTrigger: (triggerId: string, event?: AtelierEvent) =>
    sendJson<WorkflowRun>("POST", `/api/triggers/${encodeURIComponent(triggerId)}/test`, event ? { event } : {}),
  eventsCatalog: (signal?: AbortSignal) => getJson<EventsCatalog>("/api/triggers/events-catalog", signal),
  /** Exécutions d'un statut, tous workflows confondus (récents d'abord) : boîte « À valider ». */
  workflowRunsByStatus: (status: RunStatus, signal?: AbortSignal) =>
    getJson<WorkflowRun[]>(`/api/workflow-runs?${new URLSearchParams({ status }).toString()}`, signal),
  inboxCount: (signal?: AbortSignal) => getJson<InboxCount>("/api/workflow-runs/inbox-count", signal),

  // ─── Carte de la suite ───
  suiteMap: (signal?: AbortSignal) => getJson<SuiteMap>("/api/suite/map", signal),
  /** Derniers événements ; `since` n'a de sens qu'avec `app`. */
  suiteEvents: (query: { app?: string; since?: number; limit?: number } = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    if (query.app) params.set("app", query.app);
    if (query.app && query.since !== undefined) params.set("since", String(query.since));
    if (query.limit !== undefined) params.set("limit", String(query.limit));
    const qs = params.toString();
    return getJson<SuiteEventsEntry[]>(`/api/suite/events${qs ? `?${qs}` : ""}`, signal);
  },
};

/** `GET /api/workflows` renvoie v1 et v2 : le champ `version` les distingue. */
export const isWorkflowV2 = (wf: AnyWorkflow): wf is WorkflowV2 => wf.version === 2;

/**
 * Lance un agent en streaming et relaie chaque événement.
 * Les erreurs HTTP (agent inconnu, provider non configuré…) sont levées en `ApiError` ;
 * les erreurs survenues pendant le flux arrivent sous forme d'événement `error`.
 */
export async function* streamAgent(
  agent: string,
  body: AgentRunRequest,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/agents/${encodeURIComponent(agent)}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (signal?.aborted) return;
    throw new ApiError(
      `Le serveur Atelier Nexus ne répond pas (${API_URL}).`,
      0,
      err instanceof Error ? "network" : "unknown",
    );
  }
  if (!response.ok || !response.body) throw await toApiError(response);

  for await (const message of readSse(response.body)) {
    const payload = JSON.parse(message.data) as Record<string, unknown>;
    yield { ...payload, type: message.event } as AgentEvent;
  }
}
