import Link from "next/link";
import { Workflow } from "lucide-react";

/** Page 404 aux couleurs de l'app (la page par défaut de Next.js impose un fond blanc / noir). */
export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 p-8 text-center">
      <span className="atelier-about__icon atelier-brand__tile" aria-hidden="true">
        <Workflow />
      </span>
      <h1 className="mt-1 text-2xl font-semibold tracking-[-0.012em]">Page introuvable</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        Cette adresse ne correspond à aucun écran d&apos;Atelier Nexus.
      </p>
      <Link href="/" className="text-sm font-medium text-atelier-ink underline-offset-4 hover:underline">
        Retour à l&apos;accueil
      </Link>
    </main>
  );
}
