/**
 * Lecture périodique partagée par tous les abonnés (badge « À valider » de la barre latérale, de
 * la barre mobile, du Studio et de l'accueil) : un seul minuteur et une seule requête à la fois.
 * Démarre au premier abonné, s'arrête au dernier (la valeur repart de null). Rien n'est lu tant que
 * la page est cachée ; relu au réveil (page de nouveau visible, décision, lancement).
 * Sans React ni DOM (visibilité et réveils injectés), testée dans sharedPoll.test.ts.
 */

export interface PollSource<T> {
  read: (signal: AbortSignal) => Promise<T>;
  intervalMs: number;
  /** Page visible : sinon, ni lecture ni minuteur */
  visible: () => boolean;
  /** Branche les réveils (visibilité, décision…) ; rend la fonction qui les débranche */
  watch: (wake: () => void) => () => void;
}

export interface SharedPoll<T> {
  /** Dernière valeur lue ; null : pas encore lue, ou lecture en échec */
  get: () => T | null;
  subscribe: (listener: () => void) => () => void;
}

export function sharedPoll<T>(source: PollSource<T>): SharedPoll<T> {
  let value: T | null = null;
  const listeners = new Set<() => void>();
  let ctrl: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let unwatch: (() => void) | null = null;

  const publish = (next: T | null) => {
    if (Object.is(next, value)) return;
    value = next;
    for (const listener of [...listeners]) listener();
  };
  const read = () => {
    // Une seule requête à la fois : la précédente est abandonnée
    ctrl?.abort();
    const current = new AbortController();
    ctrl = current;
    source.read(current.signal).then(
      (next) => !current.signal.aborted && publish(next),
      () => !current.signal.aborted && publish(null),
    );
  };
  const schedule = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    if (!source.visible()) return;
    timer = setTimeout(() => {
      read();
      schedule();
    }, source.intervalMs);
  };
  const wake = () => {
    if (source.visible()) read();
    schedule();
  };
  const stop = () => {
    ctrl?.abort();
    ctrl = null;
    if (timer) clearTimeout(timer);
    timer = null;
    unwatch?.();
    unwatch = null;
    value = null;
  };

  return {
    get: () => value,
    subscribe(listener) {
      listeners.add(listener);
      if (listeners.size === 1) {
        unwatch = source.watch(wake);
        // Première lecture hors du rendu
        timer = setTimeout(wake, 0);
      }
      return () => {
        if (!listeners.delete(listener)) return;
        if (listeners.size === 0) stop();
      };
    },
  };
}
