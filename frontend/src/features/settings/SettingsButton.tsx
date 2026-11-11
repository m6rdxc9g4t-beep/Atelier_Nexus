"use client";

import { Settings } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useUiStore } from "@/stores/useUiStore";

/**
 * Bouton « Réglages » (barre latérale) : ouvre la fenêtre unique des Réglages. À part de
 * SettingsDialog, chargée à la demande : la barre latérale n'embarque pas le formulaire.
 */
export function SettingsButton({ className }: { className?: string }) {
  const openSettings = useUiStore((s) => s.openSettings);
  return (
    <Button variant="ghost" size="icon-sm" aria-label="Réglages" title="Réglages" className={className} onClick={openSettings}>
      <Settings />
    </Button>
  );
}
