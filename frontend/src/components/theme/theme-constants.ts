/**
 * Préférence de thème commune à la suite (SUITE.md §1.5) : `styles/brand/atelier-theme.js`
 * (copie verbatim) la lit et l'écrit (cookie `atelier_theme` sur le VPS, sinon
 * localStorage « atelier:theme ») et expose `window.atelierTheme`.
 */

/** Anciennes clés de Nexus (charte néon, puis avant) : reprises une fois au démarrage, puis effacées. */
export const LEGACY_THEME_STORAGE_KEYS = ["atelier-nexus-theme", "atelier-nexus:theme"] as const;

/** Clé commune de la suite (atelier-theme.js) : cible de la reprise. */
export const SUITE_THEME_STORAGE_KEY = "atelier:theme";

export const THEME_PREFERENCES = ["light", "dark", "system"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];

/** Préférence par défaut : suivre le réglage de l'appareil. */
export const DEFAULT_THEME_PREFERENCE: ThemePreference = "system";

/** Fond de page (--atelier-bg de la charte v2, structure neutre), pour la meta theme-color. */
export const THEME_COLORS = { light: "#fbfbfc", dark: "#0f1012" } as const;

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (THEME_PREFERENCES as readonly string[]).includes(value);
}

/** API posée sur `window` par atelier-theme.js. */
export interface AtelierThemeApi {
  get: () => ThemePreference;
  set: (preference: ThemePreference) => void;
  resolved: () => "light" | "dark";
}

declare global {
  interface Window {
    atelierTheme?: AtelierThemeApi;
  }
}
