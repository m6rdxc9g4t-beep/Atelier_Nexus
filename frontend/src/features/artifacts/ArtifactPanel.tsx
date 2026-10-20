"use client";

import { Layers, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { selectSelectedArtifact, useArtifactStore } from "@/stores/useArtifactStore";

import { ArtifactViewer, KIND_LABELS } from "./ArtifactViewer";

/**
 * Panneau latéral droit des livrables d'agents. En dessous de xl, il se superpose au chat.
 */
export function ArtifactPanel() {
  const artifacts = useArtifactStore((s) => s.artifacts);
  const selected = useArtifactStore(selectSelectedArtifact);
  const open = useArtifactStore((s) => s.panelOpen);
  const select = useArtifactStore((s) => s.select);
  const setOpen = useArtifactStore((s) => s.setPanelOpen);

  if (!open || !selected) return null;

  return (
    <aside
      aria-label="Artefacts"
      className={cn(
        "flex min-h-0 flex-col border-l border-atelier-border bg-card",
        "fixed inset-y-0 right-0 z-40 w-full shadow-glow-strong sm:w-[32rem]",
        "xl:static xl:z-auto xl:w-[34rem] xl:shrink-0 xl:shadow-glow",
      )}
    >
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <Layers className="size-4 text-accent-ink" aria-hidden />
        <label htmlFor="artifact-select" className="sr-only">
          Choisir un artefact
        </label>
        <select
          id="artifact-select"
          value={selected.id}
          onChange={(e) => select(e.target.value)}
          className="h-8 min-w-0 flex-1 truncate rounded-md border-0 bg-card text-sm font-medium outline-none focus-visible:shadow-focus"
        >
          {artifacts.map((a) => (
            <option key={a.id} value={a.id}>
              {KIND_LABELS[a.kind]} · {a.title}
            </option>
          ))}
        </select>
        <span className="text-xs text-muted-foreground">{artifacts.length}</span>
        <Button variant="ghost" size="icon-sm" aria-label="Fermer le panneau" onClick={() => setOpen(false)}>
          <X />
        </Button>
      </div>
      <ArtifactViewer key={selected.id} artifact={selected} />
    </aside>
  );
}
