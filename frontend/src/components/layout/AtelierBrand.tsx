"use client";

import { Network, X } from "lucide-react";
import { useId, useRef } from "react";

/**
 * Marque commune de la suite (SUITE.md §1.6) : tuile cyan + icône, « atelier_ » atténué,
 * nom en gras. Un clic ouvre la fenêtre « À propos » (toujours sombre).
 */
export function AtelierBrand() {
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
        <span className="atelier-brand__tile" aria-hidden>
          <Network />
        </span>
        <span className="atelier-brand__name hidden sm:inline">
          <span className="atelier-brand__prefix">atelier_</span>Nexus
        </span>
        <span className="sr-only sm:hidden">Atelier Nexus</span>
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
          <span
            className="atelier-brand__tile mx-auto mb-4 size-24! rounded-3xl! [&_svg]:size-12!"
            aria-hidden
          >
            <Network />
          </span>
          <h2 id={titleId} className="atelier-about__name">
            <span className="atelier-brand__prefix">atelier_</span>Nexus
          </h2>
          <p className="atelier-about__tagline">
            Des agents IA qui travaillent avec vos applications Atelier : données de Viz, projets,
            trésorerie, code.
          </p>
          <p className="atelier-about__suite">Suite Atelier · Claude ou modèle local</p>
        </div>
      </dialog>
    </>
  );
}
