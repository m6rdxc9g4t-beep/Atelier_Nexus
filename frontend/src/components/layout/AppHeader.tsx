"use client";

import { Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import { InboxButton } from "@/features/workflow-triggers/InboxDialog";
import { useNavStore } from "@/stores/useNavStore";

import { AtelierBrand } from "./AtelierBrand";
import { SuiteSwitcher } from "./SuiteSwitcher";

/**
 * En-tête des petits écrans (sous lg) : ouvre la barre latérale en tiroir (navigation, agents,
 * applications, thème, réglages) ; marque, suite et « À valider » restent à portée.
 */
export function AppHeader() {
  const setDrawerOpen = useNavStore((s) => s.setDrawerOpen);
  return (
    <header className="relative z-10 flex h-14 shrink-0 items-center gap-1.5 border-b border-atelier-line bg-sidebar/85 px-2 backdrop-blur-md lg:hidden">
      <Button variant="ghost" size="icon-sm" aria-label="Ouvrir la navigation" onClick={() => setDrawerOpen(true)}>
        <Menu />
      </Button>
      <SuiteSwitcher />
      <AtelierBrand />
      <div className="ml-auto flex items-center gap-1">
        <InboxButton />
      </div>
    </header>
  );
}
