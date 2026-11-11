/**
 * Focus après « Réessayer ».
 * Le bouton disparaît avec le tour en échec qu'il remplace : sans rien faire, le focus tombe sur
 * `<body>` et la navigation au clavier repart du haut de la page. On le pose donc sur la zone de
 * saisie, là où il se trouve après un envoi normal.
 */

/** Ce qu'il faut de la zone de saisie (injecté dans les tests, sans DOM). */
export interface RetryFocusTarget {
  disabled?: boolean;
  focus: () => void;
}

/**
 * Place le focus dans la zone de saisie ; faux si rien n'a bougé.
 * Au doigt, on n'y touche pas : le clavier à l'écran s'ouvrirait par-dessus la réponse qui arrive.
 * Un « Réessayer » fait au clavier (Entrée, Espace : `detail` du clic à 0) le déplace toujours,
 * même sur une tablette, puisqu'un clavier est branché.
 */
export function focusAfterRetry({
  composer,
  keyboard,
  coarse,
}: {
  composer: RetryFocusTarget | null;
  /** Bouton activé au clavier, et non par un clic ou un appui */
  keyboard: boolean;
  /** Pointeur principal grossier (téléphone, tablette) */
  coarse: boolean;
}): boolean {
  if (!composer || composer.disabled) return false;
  if (coarse && !keyboard) return false;
  composer.focus();
  return true;
}
