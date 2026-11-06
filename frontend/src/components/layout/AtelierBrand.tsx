"use client";

import { Workflow, X } from "lucide-react";
import { useId, useRef } from "react";

/**
 * Marque commune de la suite (SUITE.md §1.6) : icône carrée arrondie en dégradé de la signature
 * (orange de Nexus), glyphe Lucide `workflow` blanc, « Atelier » atténué puis le nom en gras.
 * Un clic ouvre la fenêtre « À propos », qui suit le thème de l'app, avec la grande icône.
 */
export function AtelierBrand({ compact = false }: { compact?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  return (
    <>
      <button
        type="button"
        className="atelier-brand"
        aria-haspopup="dialog"
        onClick={() => dialog.current?.showModal()}
      >
        <span className="atelier-brand__tile atelier-brand__tile--sm" aria-hidden>
          <Workflow />
        </span>
        {/* `compact` (barre des petits écrans) : l'icône seule sous sm, le nom reste lu */}
        <span className={compact ? "atelier-brand__name hidden sm:inline" : "atelier-brand__name"}>
          <span className="atelier-brand__prefix">Atelier </span>Nexus
        </span>
        {compact && <span className="sr-only sm:hidden">Atelier Nexus</span>}
      </button>

      <dialog
        ref={dialog}
        className="atelier-about"
        aria-labelledby={titleId}
        onClick={(e) => {
          if (e.target === e.currentTarget) e.currentTarget.close();
        }}
      >
        <div className="atelier-about__panel">
          <button
            type="button"
            className="atelier-about__close"
            aria-label="Fermer"
            onClick={() => dialog.current?.close()}
          >
            <X className="size-4" aria-hidden />
          </button>
          <span className="atelier-about__icon atelier-brand__tile" aria-hidden>
            <Workflow />
          </span>
          <h2 id={titleId} className="atelier-about__name">
            <span className="atelier-brand__prefix">Atelier </span>Nexus
          </h2>
          <p className="atelier-about__tagline">
            Des agents IA et des workflows qui relient vos applications Atelier : Convert, Tab, Viz,
            Projets, Trésorerie, code.
          </p>
          <p className="atelier-about__suite">Suite Atelier · Claude ou modèle local</p>
        </div>
      </dialog>
    </>
  );
}
