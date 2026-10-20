import type { Metadata } from "next";

import { THEME_BOOT_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "Atelier Nexus",
  description: "Agents IA de la suite Atelier",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // Le thème est posé avant l'hydratation (script ci-dessous) : attributs différents du rendu serveur
    <html lang="fr" data-theme="light" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
