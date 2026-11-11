/**
 * Garde la référence précédente quand une relecture rend les mêmes données (comparaison par
 * contenu JSON) : l'état React ne change pas, donc rien n'est re-rendu. Sert aux lectures
 * périodiques (agents, moteurs, état des applications toutes les 30 s).
 */
export function stable<T>(previous: T, next: T): T {
  if (Object.is(previous, next)) return previous;
  return JSON.stringify(previous) === JSON.stringify(next) ? previous : next;
}
