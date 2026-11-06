import { readFileSync } from "node:fs";
import { join } from "node:path";

import { LEGACY_THEME_STORAGE_KEYS, SUITE_THEME_STORAGE_KEY } from "./theme-constants";

/**
 * Reprise, une seule fois, du choix enregistré par les anciennes versions de Nexus (app de bureau :
 * stockage persistant) sous la clé commune de la suite, puis effacement des anciennes clés.
 */
const migrate = `(function(){try{var s=localStorage,k=${JSON.stringify(SUITE_THEME_STORAGE_KEY)},o=${JSON.stringify(LEGACY_THEME_STORAGE_KEYS)};for(var i=0;i<o.length;i++){var v=s.getItem(o[i]);if(v!==null){if(s.getItem(k)===null&&(v==="light"||v==="dark"||v==="system"))s.setItem(k,v);s.removeItem(o[i])}}}catch(e){}})();`;

/**
 * Préférence de thème commune à la suite (SUITE.md §1.5) : `styles/brand/atelier-theme.js`, copie
 * verbatim d'Atelier_Projets/design-system, lu au rendu serveur (ou à l'export statique) et posé en
 * script bloquant dans <head> : le thème est appliqué avant le premier affichage (pas de flash).
 * Effet sur <html> : data-theme="light|dark", classe « dark », data-theme-pref ; `window.atelierTheme`.
 */
const suite = readFileSync(join(process.cwd(), "src/styles/brand/atelier-theme.js"), "utf8");

export function ThemeScript() {
  return (
    <script
      // Exécuté pendant l'analyse du HTML ; ignoré côté client (pas d'avertissement React sur <script>).
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: `${migrate}\n${suite}` }}
    />
  );
}
