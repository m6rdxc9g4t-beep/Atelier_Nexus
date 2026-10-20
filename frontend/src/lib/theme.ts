/**
 * Thème clair / sombre (SUITE.md §1.5) : sur <html>, classe `dark` ET data-theme.
 * Préférence propre à Nexus : clé `atelier-nexus:theme`.
 */

export type ThemePreference = "light" | "dark" | "system";

export const THEME_KEY = "atelier-nexus:theme";

export function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(pref: ThemePreference, prefersDark: boolean): "light" | "dark" {
  return pref === "system" ? (prefersDark ? "dark" : "light") : pref;
}

export function applyTheme(pref: ThemePreference): void {
  const dark = resolveTheme(pref, window.matchMedia("(prefers-color-scheme: dark)").matches);
  const root = document.documentElement;
  root.classList.toggle("dark", dark === "dark");
  root.dataset.theme = dark;
  try {
    if (pref === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, pref);
  } catch {
    // stockage indisponible : le thème s'applique pour la session
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

const THEME_EVENT = "atelier-nexus:theme-change";

/** Abonnement pour `useSyncExternalStore` (préférence changée dans cet onglet ou un autre). */
export function subscribePreference(onChange: () => void): () => void {
  window.addEventListener(THEME_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(THEME_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** Script exécuté avant l'affichage : évite le flash du mauvais thème. */
export const THEME_BOOT_SCRIPT = `(function(){try{var p=localStorage.getItem("${THEME_KEY}");var d=p==="dark"||(p!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);var r=document.documentElement;r.classList.toggle("dark",d);r.dataset.theme=d?"dark":"light";}catch(e){}})();`;
