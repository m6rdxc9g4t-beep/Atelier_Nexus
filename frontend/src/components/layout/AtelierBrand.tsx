"use client";

import { Network, X } from "lucide-react";
import { useId, useRef, useState } from "react";

/** Logo complet de l'app (bicolore) : réservé à la fenêtre « À propos », jamais dans l'interface de travail. */
const LOGO_SRC = "/brand/logo-atelier-nexus.png";

/**
 * Marque commune de la suite (SUITE.md §1.6) : tuile cyan + icône, « atelier_ » atténué,
 * nom en gras. Un clic ouvre la fenêtre « À propos » (toujours sombre), avec le logo complet.
 */
export function AtelierBrand() {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  // Logo chargé à la première ouverture seulement (image lourde, inutile tant que la fenêtre est fermée)
  const [opened, setOpened] = useState(false);

  return (
    <>
      <button
        type="button"
        className="atelier-brand"
        aria-haspopup="dialog"
        onClick={() => {
          setOpened(true);
          dialog.current?.showModal();
        }}
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
          {opened && (
            // eslint-disable-next-line @next/next/no-img-element -- fichier statique de la marque (export statique de l'app de bureau, sans optimiseur d'images)
            <img className="atelier-about__logo" src={LOGO_SRC} alt="Logo Atelier Nexus" width={1254} height={1254} decoding="async" />
          )}
          <h2 id={titleId} className="atelier-about__name">
            <span className="atelier-brand__prefix">atelier_</span>Nexus
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
