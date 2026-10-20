/** Dernière conversation ouverte par agent, pour la rouvrir au prochain passage (confort, non critique). */

const KEY = "atelier-nexus.last-conversation";

function read(): Record<string, string> {
  try {
    const raw = localStorage.getItem(KEY);
    const value: unknown = raw ? JSON.parse(raw) : {};
    return value && typeof value === "object" ? (value as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function lastConversation(agent: string): string | null {
  return read()[agent] ?? null;
}

export function rememberConversation(agent: string, id: string | null): void {
  try {
    const all = read();
    if (id) all[agent] = id;
    else delete all[agent];
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    // stockage indisponible (navigation privée…) : on s'en passe
  }
}
