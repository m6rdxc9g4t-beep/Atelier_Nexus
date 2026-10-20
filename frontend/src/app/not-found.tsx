import Link from "next/link";
import { Network } from "lucide-react";

/** Page 404 aux couleurs de l'app (la page par défaut de Next.js impose un fond blanc / noir). */
export default function NotFound() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <span className="atelier-brand__tile size-11 rounded-xl" aria-hidden="true">
        <Network className="size-6" />
      </span>
      <h1 className="text-3xl font-semibold tracking-tight text-shadow-glow">Page introuvable</h1>
      <p className="max-w-md text-muted-foreground">
        Cette adresse ne correspond à aucun écran d&apos;Atelier Nexus.
      </p>
      <Link
        href="/"
        className="text-sm font-medium text-atelier-ink underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:shadow-focus focus-visible:outline-none"
      >
        Retour à l&apos;accueil
      </Link>
    </main>
  );
}
