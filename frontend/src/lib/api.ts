/** Client HTTP typé de l'API Atelier Nexus. */

import { readSse } from "@/lib/sse";
import type {
  AgentEvent,
  AgentInfo,
  AgentRunRequest,
  ApiErrorBody,
  AppStatus,
  ConversationDetail,
  ConversationSummary,
  CustomAgentDefinition,
  CustomAgentFields,
  DataViaStatus,
  EditorOptions,
  ProviderStatus,
  SettingsView,
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

export const api = {
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
  createConversation: (agent: string) =>
    sendJson<ConversationDetail>("POST", "/api/conversations", { agent }),
  renameConversation: (id: string, title: string) =>
    sendJson<ConversationDetail>("PATCH", `/api/conversations/${encodeURIComponent(id)}`, { title }),
  deleteConversation: (id: string) =>
    sendJson<void>("DELETE", `/api/conversations/${encodeURIComponent(id)}`),
  settings: (signal?: AbortSignal) => getJson<SettingsView>("/api/settings", signal),
  updateSettings: (values: Record<string, string | null>) =>
    sendJson<SettingsView>("PUT", "/api/settings", { values }),
};

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
