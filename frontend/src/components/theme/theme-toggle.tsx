"use client";

import { useLayoutEffect, useSyncExternalStore } from "react";
import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  DARK_MEDIA_QUERY,
  DEFAULT_THEME_PREFERENCE,
  THEME_STORAGE_KEY,
  isThemePreference,
  type ThemePreference,
} from "./theme-constants";

const OPTIONS: { value: ThemePreference; label: string; short: string; Icon: LucideIcon }[] = [
  { value: "light", label: "Thème clair", short: "Clair", Icon: Sun },
  { value: "dark", label: "Thème sombre", short: "Sombre", Icon: Moon },
  { value: "system", label: "Thème du système", short: "Système", Icon: Monitor },
];

/* ─── Préférence mémorisée (localStorage, avec repli en mémoire) ─── */

let memory: ThemePreference | null = null;
const listeners = new Set<() => void>();

function readPreference(): ThemePreference {
  if (memory) return memory;
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    memory = isThemePreference(stored) ? stored : DEFAULT_THEME_PREFERENCE;
  } catch {
    memory = DEFAULT_THEME_PREFERENCE;
  }
  return memory;
}

function writePreference(next: ThemePreference) {
  memory = next;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    /* stockage indisponible : le choix vaut pour cette visite */
  }
  listeners.forEach((notify) => notify());
}

function subscribe(notify: () => void) {
  listeners.add(notify);
  // Choix fait dans un autre onglet.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== THEME_STORAGE_KEY) return;
    memory = null;
    notify();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(notify);
    window.removeEventListener("storage", onStorage);
  };
}

/** Même règle que le script anti-flash (theme-script.tsx). */
function applyTheme(preference: ThemePreference) {
  const dark =
    preference === "dark" ||
    (preference === "system" && window.matchMedia(DARK_MEDIA_QUERY).matches);
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.dataset.theme = dark ? "dark" : "light";
}

/**
 * Sélecteur Clair / Sombre / Système (préférence mémorisée sur cet appareil). `labels` : nom de
 * chaque thème à côté de son icône (Réglages › Apparence) ; sinon icônes seules (barre latérale).
 */
export function ThemeToggle({ className, labels = false }: { className?: string; labels?: boolean }) {
  // null au rendu serveur et à l'hydratation : aucun bouton coché tant que la préférence n'est pas lue.
  const preference = useSyncExternalStore(subscribe, readPreference, () => null);

  useLayoutEffect(() => {
    if (!preference) return;
    // Applique le choix (et le réapplique après le remontage du mode strict en dev).
    applyTheme(preference);
    if (preference !== "system") return;
    // « Système » : suivre les changements de réglage de l'appareil.
    const media = window.matchMedia(DARK_MEDIA_QUERY);
    const onChange = () => applyTheme("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [preference]);

  return (
    <div
      role="group"
      aria-label="Choix du thème"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border border-atelier-border-soft bg-atelier-surface/70 p-0.5 backdrop-blur-sm",
        className,
      )}
    >
      {OPTIONS.map(({ value, label, short, Icon }) => {
        const active = preference === value;
        return (
          <button
            key={value}
            type="button"
            aria-label={label}
            aria-pressed={active}
            title={labels ? undefined : label}
            onClick={() => writePreference(value)}
            className={cn(
              "inline-flex h-8 items-center justify-center rounded-full transition-colors",
              labels ? "gap-1.5 px-3 text-xs font-medium" : "w-8",
              "focus-visible:shadow-focus focus-visible:outline-none",
              active
                ? "bg-signature-soft text-atelier-ink"
                : "text-atelier-muted hover:bg-signature-faint hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden="true" />
            {labels && short}
          </button>
        );
      })}
    </div>
  );
}
