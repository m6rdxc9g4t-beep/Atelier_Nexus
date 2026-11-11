/**
 * Vues chargées à la demande (`next/dynamic` dans Workspace.tsx) : la conversation et son rendu
 * Markdown, le Studio des workflows, l'éditeur en graphe (@xyflow/react), les Réglages et
 * l'éditeur d'agent ne sont pas dans le paquet initial — l'accueil s'affiche sans eux.
 * Un seul chargeur par vue : `next/dynamic` et le préchargement au repos partagent le même module.
 */

export const LAZY_VIEWS = {
  chat: () => import("@/features/chat-agent/ChatPanel").then((m) => m.ChatPanel),
  studio: () => import("@/features/workflows/WorkflowsStudio").then((m) => m.WorkflowsStudio),
  graphEditor: () => import("@/features/workflows-graph/WorkflowGraphEditor").then((m) => m.WorkflowGraphDialog),
  settings: () => import("@/features/settings/SettingsDialog").then((m) => m.SettingsDialog),
  agentEditor: () => import("@/features/agent-editor/AgentEditor").then((m) => m.AgentEditor),
};

/** Minimum de l'objet `window` utilisé (injecté dans les tests). */
export interface IdleHost {
  requestIdleCallback?: (run: () => void, options?: { timeout: number }) => number;
  cancelIdleCallback?: (id: number) => void;
  setTimeout: (run: () => void, ms: number) => unknown;
  clearTimeout: (id: never) => void;
}

/**
 * Lance `run` quand le navigateur est au repos (au plus tard après `timeout` ms) ; sans
 * `requestIdleCallback` (Safari), après un court délai. Rend la fonction qui annule.
 */
export function whenIdle(run: () => void, host: IdleHost = window, timeout = 4000): () => void {
  if (host.requestIdleCallback) {
    const id = host.requestIdleCallback(run, { timeout });
    return () => host.cancelIdleCallback?.(id);
  }
  const id = host.setTimeout(run, 1500);
  return () => host.clearTimeout(id as never);
}
