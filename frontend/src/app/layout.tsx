import type { Metadata, Viewport } from "next";
// Polices auto-hébergées (aucun accès réseau requis au build / en Docker)
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { ThemeScript } from "@/components/theme/theme-script";
import { THEME_COLORS } from "@/components/theme/theme-constants";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atelier Nexus",
  description: "Agents IA pour la suite Atelier",
};

// Barre du navigateur aux couleurs de fond du kit (orange), une par schéma.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_COLORS.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLORS.dark },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // Thème Clair / Sombre / Système (contrat de la suite Atelier) : clair par défaut au
    // rendu serveur ; ThemeScript applique la préférence (localStorage « atelier-nexus-theme »,
    // défaut Système) avant le premier affichage — sombre = .dark + data-theme="dark".
    // suppressHydrationWarning : le script modifie <html> avant l'hydratation.
    // data-atelier-app : toute l'app dans la couleur signature de Nexus (orange #E8590C).
    <html
      lang="fr"
      data-atelier-app="nexus"
      data-theme="light"
      suppressHydrationWarning
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
    >
      <head>
        <ThemeScript />
      </head>
      <body className="flex min-h-full flex-col font-sans">{children}</body>
    </html>
  );
}
