/**
 * Lien profond venu d'une autre app de la suite (Atelier Hub) : `?agent=<nom>` ouvre la conversation
 * avec cet agent. Lu une fois, quand le catalogue des agents est chargé, puis retiré de l'adresse.
 */

const AGENT_NAME = /^[a-z0-9_-]{1,64}$/i;

export function readAgentLink(search: string): string | null {
  const name = new URLSearchParams(search).get("agent");
  return name && AGENT_NAME.test(name) ? name : null;
}

/** Adresse sans le paramètre `agent` (les autres sont gardés). */
export function withoutAgentLink(href: string): string {
  const url = new URL(href);
  url.searchParams.delete("agent");
  return `${url.pathname}${url.search}${url.hash}`;
}
