"use client";

import { useRef } from "react";

/**
 * Retour du focus à la fermeture d'une fenêtre ou d'un tiroir.
 * Radix ne rend le focus qu'à un `DialogTrigger` : une fenêtre ouverte par un store (Réglages,
 * éditeur d'agent, éditeur en graphe, navigation en tiroir, livrables) le laissait sur `<body>`,
 * et la navigation au clavier repartait du haut de la page. On retient donc l'élément qui avait
 * le focus à l'ouverture, et on le lui rend s'il existe encore.
 */

/** Ce qu'il faut d'un élément (injecté dans les tests, sans DOM). */
export interface FocusTarget {
  isConnected: boolean;
  focus: () => void;
}

/**
 * Élément qui avait le focus à l'ouverture : ignoré si c'est `<body>` (rien n'avait le focus) ou un
 * élément de la fenêtre elle-même (champ en `autoFocus`, déjà servi avant l'événement).
 */
export function rememberOpener<T>(
  active: T | null,
  content: { contains: (node: T) => boolean } | null,
  body: T | null,
): T | null {
  if (!active || active === body || content?.contains(active)) return null;
  return active;
}

/** Rend le focus ; faux si l'élément a disparu (menu refermé, vue changée) : Radix garde la main. */
export function returnFocus(opener: FocusTarget | null): boolean {
  if (!opener || !opener.isConnected) return false;
  opener.focus();
  return true;
}

type FocusHandler = (event: Event) => void;

/** Gestionnaires `onOpenAutoFocus` / `onCloseAutoFocus` d'un contenu Radix, composés avec ceux de l'appelant. */
export function useFocusReturn(own: { onOpenAutoFocus?: FocusHandler; onCloseAutoFocus?: FocusHandler }) {
  const opener = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: (event: Event) => {
      const active = document.activeElement;
      opener.current = rememberOpener(
        active instanceof HTMLElement ? active : null,
        event.currentTarget instanceof Node ? event.currentTarget : null,
        document.body,
      );
      own.onOpenAutoFocus?.(event);
    },
    onCloseAutoFocus: (event: Event) => {
      own.onCloseAutoFocus?.(event);
      // L'appelant a déjà placé le focus : on ne le déplace pas
      if (!event.defaultPrevented && returnFocus(opener.current)) event.preventDefault();
      opener.current = null;
    },
  };
}
