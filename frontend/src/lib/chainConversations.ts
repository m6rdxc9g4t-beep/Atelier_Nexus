/**
 * Conversations des étapes de la chaîne suivie : le mode pas à pas y est imposé (la chaîne
 * promet que chaque résultat est revu). Tenu à jour par useChainStore, lu par useChatStore
 * (module à part : pas de dépendance circulaire entre les deux stores).
 */

let ids = new Set<string>();

export function setChainConversations(next: Iterable<string>): void {
  ids = new Set(next);
}

export function isChainConversation(id: string | null | undefined): boolean {
  return !!id && ids.has(id);
}
