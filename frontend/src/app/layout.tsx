import type { Metadata, Viewport } from "next";

import { THEME_COLORS } from "@/components/theme/theme-constants";
import { ThemeScript } from "@/components/theme/theme-script";

import "./globals.css";

export const metadata: Metadata = {
  title: "Atelier Nexus",
  description: "Agents IA de la suite Atelier",
};

// Barre du navigateur sur le fond neutre de la charte v2, une par schéma.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_COLORS.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLORS.dark },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // Thème Système / Clair / Sombre commun à la suite : clair par défaut au rendu serveur ;
    // ThemeScript (atelier-theme.js, copie verbatim) applique la préférence avant le premier
    // affichage — sombre = .dark + data-theme="dark".
    // suppressHydrationWarning : le script modifie <html> avant l'hydratation.
    // data-atelier-app : accent dans la signature de Nexus (orange #c84f00), structure neutre.
    <html lang="fr" data-atelier-app="nexus" data-theme="light" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body>{children}</body>
    </html>
  );
}
