/** Clé localStorage de la préférence de thème (contrat de la suite Atelier : atelier-<app>-theme). */
export const THEME_STORAGE_KEY = "atelier-nexus-theme";

export const THEME_PREFERENCES = ["light", "dark", "system"] as const;
export type ThemePreference = (typeof THEME_PREFERENCES)[number];

/** Préférence par défaut : suivre le réglage de l'appareil. */
export const DEFAULT_THEME_PREFERENCE: ThemePreference = "system";

export const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

/** Couleurs de fond du kit pour l'orange (--atelier-bg calculé), pour la meta theme-color. */
export const THEME_COLORS = { light: "#fbf3f2", dark: "#120c0d" } as const;

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (THEME_PREFERENCES as readonly string[]).includes(value);
}
