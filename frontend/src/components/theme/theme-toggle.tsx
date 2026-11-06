"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";

import { segmentedItem, segmentedRail } from "@/components/ui/segmented";
import { cn } from "@/lib/utils";

import { DEFAULT_THEME_PREFERENCE, isThemePreference, type ThemePreference } from "./theme-constants";

/** Ordre de la suite (portail) : Système, Clair, Sombre. */
const OPTIONS: { value: ThemePreference; label: string; short: string; Icon: LucideIcon }[] = [
  { value: "system", label: "Thème du système", short: "Système", Icon: Monitor },
  { value: "light", label: "Thème clair", short: "Clair", Icon: Sun },
  { value: "dark", label: "Thème sombre", short: "Sombre", Icon: Moon },
];

/* ─── Préférence commune à la suite (styles/brand/atelier-theme.js) ─── */

function readPreference(): ThemePreference {
  const value = window.atelierTheme?.get();
  return isThemePreference(value) ? value : DEFAULT_THEME_PREFERENCE;
}

function subscribe(notify: () => void) {
  // Changement fait ici, dans un autre onglet ou dans une autre app de la suite (retour sur la page).
  window.addEventListener("atelier-theme", notify);
  window.addEventListener("storage", notify);
  document.addEventListener("visibilitychange", notify);
  return () => {
    window.removeEventListener("atelier-theme", notify);
    window.removeEventListener("storage", notify);
    document.removeEventListener("visibilitychange", notify);
  };
}

/**
 * Sélecteur Système / Clair / Sombre, branché sur la préférence commune de la suite
 * (`window.atelierTheme.set`, qui applique le thème et prévient par l'événement « atelier-theme »).
 * `labels` : nom de chaque thème à côté de son icône (Réglages › Apparence) ; sinon icônes seules.
 */
export function ThemeToggle({ className, labels = false }: { className?: string; labels?: boolean }) {
  // null au rendu serveur et à l'hydratation : aucun bouton coché tant que la préférence n'est pas lue.
  const preference = useSyncExternalStore(subscribe, readPreference, () => null);

  return (
    <div role="group" aria-label="Choix du thème" className={cn(segmentedRail, className)}>
      {OPTIONS.map(({ value, label, short, Icon }) => (
        <button
          key={value}
          type="button"
          aria-label={label}
          aria-pressed={preference === value}
          title={labels ? undefined : label}
          onClick={() => window.atelierTheme?.set(value)}
          className={cn(segmentedItem, labels ? "px-2.5" : "w-7 px-0")}
        >
          <Icon aria-hidden />
          {labels && short}
        </button>
      ))}
    </div>
  );
}
