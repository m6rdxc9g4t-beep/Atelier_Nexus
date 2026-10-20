import { DARK_MEDIA_QUERY, THEME_STORAGE_KEY } from "./theme-constants";

/**
 * Applique le thème mémorisé avant le premier affichage (pas de flash).
 * Contrat Atelier sur <html> : sombre = class « dark » + data-theme="dark" ;
 * clair = sans « dark » + data-theme="light". Voir le guide Next.js
 * « Preventing flash before hydration ». À garder aligné sur applyTheme() (theme-toggle.tsx).
 */
const script = `(function(){var p="system";try{var v=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(v==="light"||v==="dark"||v==="system")p=v}catch(e){}try{var d=p==="dark"||(p==="system"&&window.matchMedia(${JSON.stringify(DARK_MEDIA_QUERY)}).matches);var r=document.documentElement;r.classList.toggle("dark",d);r.setAttribute("data-theme",d?"dark":"light")}catch(e){}})();`;

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
