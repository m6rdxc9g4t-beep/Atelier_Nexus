import { Network } from "lucide-react";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="atelier-brand gap-3">
        <span className="atelier-brand__tile size-11 rounded-xl" aria-hidden="true">
          <Network className="size-6" />
        </span>
        <span className="atelier-brand__name text-3xl">
          <span className="atelier-brand__prefix">atelier_</span>Nexus
        </span>
      </h1>
      <p className="max-w-md text-muted-foreground">
        Environnement initialisé. Les modules Chat Agent, Studio Dev et Dashboard Data Via
        arrivent aux étapes suivantes.
      </p>
    </main>
  );
}
