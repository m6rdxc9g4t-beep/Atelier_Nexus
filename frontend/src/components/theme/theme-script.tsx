import { DARK_MEDIA_QUERY, LEGACY_THEME_STORAGE_KEY, THEME_STORAGE_KEY } from "./theme-constants";

/**
 * Applique le thème mémorisé avant le premier affichage (pas de flash).
 * Contrat Atelier sur <html> : sombre = class « dark » + data-theme="dark" ;
 * clair = sans « dark » + data-theme="light". Voir le guide Next.js
 * « Preventing flash before hydration ». À garder aligné sur applyTheme() (theme-toggle.tsx).
 * Reprend aussi le choix enregistré sous l'ancienne clé (app de bureau : stockage persistant).
 */
const script = `(function(){var p="system";try{var k=${JSON.stringify(THEME_STORAGE_KEY)},o=${JSON.stringify(LEGACY_THEME_STORAGE_KEY)},v=localStorage.getItem(k),w=localStorage.getItem(o);if(w!==null){if(v===null&&(w==="light"||w==="dark")){v=w;localStorage.setItem(k,w)}localStorage.removeItem(o)}if(v==="light"||v==="dark"||v==="system")p=v}catch(e){}try{var d=p==="dark"||(p==="system"&&window.matchMedia(${JSON.stringify(DARK_MEDIA_QUERY)}).matches);var r=document.documentElement;r.classList.toggle("dark",d);r.setAttribute("data-theme",d?"dark":"light")}catch(e){}})();`;

export function ThemeScript() {
  return (
    <script
      // Exécuté pendant l'analyse du HTML ; ignoré côté client (pas d'avertissement React sur <script>).
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: script }}
    />
  );
}
