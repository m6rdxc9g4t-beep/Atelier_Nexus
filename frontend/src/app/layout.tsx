import type { Metadata } from "next";
// Polices auto-hébergées (aucun accès réseau requis au build / en Docker)
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atelier Nexus",
  description: "Agents IA pour la suite Atelier",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // Thème unique de l'app : le sombre néon de la charte Atelier
    // (.dark pour les variantes Tailwind/Shadcn, data-theme pour les effets néon de atelier-brand.css).
    // data-atelier-app pose la couleur signature de Nexus (orange #E8590C).
    <html
      lang="fr"
      data-atelier-app="nexus"
      data-theme="dark"
      className={`${GeistSans.variable} ${GeistMono.variable} dark h-full antialiased`}
    >
      <body className="flex min-h-full flex-col font-sans">{children}</body>
    </html>
  );
}
