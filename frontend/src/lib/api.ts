/** Client HTTP typé de l'API Atelier Nexus. */

import { readSse } from "@/lib/sse";
import type {
  AgentEvent,
  AgentInfo,
  AgentRunRequest,
  ApiErrorBody,
  DataViaStatus,
  ProviderStatus,
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
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Partial<ApiErrorBody> & { detail?: unknown };
    if (body.error) return new ApiError(body.error.message, response.status, body.error.code);
    if (typeof body.detail === "string") return new ApiError(body.detail, response.status, "http");
  } catch {
    // corps non JSON
  }
  return new ApiError(`Erreur ${response.status}`, response.status, "http");
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { signal, cache: "no-store" });
  } catch {
    throw new ApiError(
      `Le serveur Atelier Nexus ne répond pas (${API_URL}). Lancez le backend sur le port 8100.`,
      0,
      "network",
    );
  }
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

export const api = {
  agents: (signal?: AbortSignal) => getJson<AgentInfo[]>("/api/agents", signal),
  providers: (signal?: AbortSignal) => getJson<ProviderStatus[]>("/api/llm/providers", signal),
  dataViaStatus: (signal?: AbortSignal) => getJson<DataViaStatus>("/api/data-via/status", signal),
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
