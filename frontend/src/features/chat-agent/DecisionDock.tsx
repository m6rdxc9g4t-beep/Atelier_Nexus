"use client";

import { ShieldQuestion } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Rappel collant au-dessus du composer quand une validation attend et que sa carte est hors de
 * vue : « L'agent attend votre accord · n actions » et « Voir », qui ramène à la carte et met le
 * focus sur son titre. Jamais de bouton d'autorisation ici : on décide sur la carte, paramètres
 * sous les yeux. Monté avec la clé de la validation : l'état repart de zéro à chaque carte.
 */
export function DecisionDock({
  target,
  root,
  count,
}: {
  /** Carte de validation en attente */
  target: HTMLElement | null;
  /** Conteneur qui fait défiler le fil */
  root: HTMLElement | null;
  count: number;
}) {
  const [offscreen, setOffscreen] = useState(false);

  useEffect(() => {
    if (!target || !root || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        // Vue : assez de la carte pour la lire, hors de la bande couverte par le dock lui-même
        const seen = entry.isIntersecting && (entry.intersectionRatio >= 0.3 || entry.intersectionRect.height >= 120);
        setOffscreen(!seen);
      },
      { root, rootMargin: "0px 0px -64px 0px", threshold: [0, 0.1, 0.3, 0.6, 1] },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [target, root]);

  if (!target || !offscreen) return null;

  const reveal = () => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    target.querySelector<HTMLElement>("[data-decision-title]")?.focus({ preventScroll: true });
  };

  return (
    <div
      role="region"
      aria-label="Validation en attente"
      className="pointer-events-auto flex w-full items-center gap-3 rounded-xl border border-atelier-border bg-card/95 py-2 pr-2 pl-3.5 shadow-glow backdrop-blur"
    >
      <ShieldQuestion className="size-4 shrink-0 text-warning" aria-hidden />
      <p className="min-w-0 flex-1 truncate text-sm">
        <span className="font-medium text-warning-ink">L&apos;agent attend votre accord</span>
        <span className="text-muted-foreground">
          {" "}
          · {count} action{count > 1 ? "s" : ""}
        </span>
      </p>
      <Button size="sm" variant="outline" onClick={reveal}>
        Voir
      </Button>
    </div>
  );
}
