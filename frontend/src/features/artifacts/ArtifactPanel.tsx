"use client";

import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  FileBraces,
  FileCode,
  FileText,
  type LucideIcon,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { cn } from "@/lib/utils";
import { type StoredArtifact, selectSelectedArtifact, useArtifactStore } from "@/stores/useArtifactStore";
import type { ArtifactKind } from "@/types/api";

import { ArtifactViewer } from "./ArtifactViewer";
import {
  type ArtifactScope,
  type KindFamily,
  artifactScope,
  artifactSubtitle,
  artifactTime,
  inScope,
  kindFamily,
  positionOf,
  scopeCounts,
  selectionAfterRemoval,
  selectionForScope,
} from "./panel";

const FAMILY_ICONS: Record<KindFamily, LucideIcon> = {
  data: Database,
  code: FileCode,
  document: FileText,
  json: FileBraces,
};

const KindIcon = ({ kind, className }: { kind: ArtifactKind; className?: string }) => {
  const Icon = FAMILY_ICONS[kindFamily(kind)];
  return <Icon className={className} aria-hidden />;
};

/** Même seuil que l'ouverture automatique des livrables (useChatStore, workflows). */
const WIDE = "(min-width: 1280px)";

/**
 * Panneau des livrables d'agents et de workflows (CLAUDE.md « Expérience Artefacts »).
 * En xl, colonne collée à droite du chat (« Agrandir » : 60 % de la largeur) ; en dessous,
 * tiroir modal à droite (voile, Échap, focus piégé), pour ne pas recouvrir le chat sans le dire.
 */
export function ArtifactPanel() {
  const artifacts = useArtifactStore((s) => s.artifacts);
  const selected = useArtifactStore(selectSelectedArtifact);
  const open = useArtifactStore((s) => s.panelOpen);
  const setOpen = useArtifactStore((s) => s.setPanelOpen);
  const wide = useMediaQuery(WIDE);
  const [expanded, setExpanded] = useState(false);

  if (wide) {
    if (!open || !selected) return null;
    return (
      <aside
        aria-label="Livrables"
        className={cn(
          "flex min-h-0 shrink-0 flex-col border-l border-atelier-line bg-card transition-[width] duration-200 motion-reduce:transition-none",
          expanded ? "w-[60vw]" : "w-[min(36rem,40vw)]",
        )}
      >
        <PanelBody
          artifacts={artifacts}
          selected={selected}
          expanded={expanded}
          onToggleExpanded={() => setExpanded((e) => !e)}
          onClose={() => setOpen(false)}
        />
      </aside>
    );
  }

  return (
    <Sheet open={open && !!selected} onOpenChange={setOpen}>
      {selected && (
        <SheetContent
          side="right"
          closeButton={false}
          aria-describedby={undefined}
          // Focus sur le tiroir lui-même (annoncé par son titre) plutôt que sur un bouton de l'en-tête
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            (e.currentTarget as HTMLElement | null)?.focus();
          }}
        >
          <SheetTitle className="sr-only">Livrables</SheetTitle>
          <PanelBody artifacts={artifacts} selected={selected} onClose={() => setOpen(false)} />
        </SheetContent>
      )}
    </Sheet>
  );
}

function PanelBody({
  artifacts,
  selected,
  expanded,
  onToggleExpanded,
  onClose,
}: {
  artifacts: StoredArtifact[];
  selected: StoredArtifact;
  /** Colonne xl seulement : largeur agrandie et sa bascule. */
  expanded?: boolean;
  onToggleExpanded?: () => void;
  onClose: () => void;
}) {
  const select = useArtifactStore((s) => s.select);
  const remove = useArtifactStore((s) => s.remove);
  const [listOpen, setListOpen] = useState(true);
  const listId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  // Après un retrait, le bouton « Retirer » disparaît : le focus va au titre du livrable montré
  // ensuite, une fois affiché (lu avec son nouveau titre), plutôt que de retomber sur la page.
  const refocus = useRef(false);

  useEffect(() => {
    if (!refocus.current) return;
    refocus.current = false;
    heading.current?.focus();
  }, [selected.id]);

  // La provenance affichée est celle du livrable sélectionné : choisir l'autre filtre
  // sélectionne son livrable le plus récent (aucun état à resynchroniser).
  const scope = artifactScope(selected);
  const counts = scopeCounts(artifacts);
  const list = inScope(artifacts, scope);
  const position = positionOf(list, selected.id);

  const removeSelected = () => {
    // Reste dans la même provenance quand c'est possible (le store, lui, reprendrait le premier)
    const fallback = selectionAfterRemoval(list, selected.id);
    if (fallback) select(fallback);
    refocus.current = true;
    remove(selected.id);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-2.5 border-b border-atelier-line px-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-atelier-border-soft bg-signature-faint text-accent-ink">
          <KindIcon kind={selected.kind} className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs text-muted-foreground">{artifactSubtitle(selected.kind, selected.createdAt)}</p>
          <h2
            ref={heading}
            tabIndex={-1}
            className="truncate text-sm font-semibold tracking-tight outline-none"
            title={selected.title}
          >
            {selected.title}
          </h2>
        </div>
        {position.total > 1 && (
          <nav aria-label="Parcourir les livrables" className="flex shrink-0 items-center">
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Livrable précédent"
              disabled={!position.previous}
              onClick={() => position.previous && select(position.previous)}
            >
              <ChevronLeft />
            </Button>
            <span className="min-w-9 text-center text-xs text-muted-foreground tabular-nums">
              <span aria-hidden>
                {position.index} / {position.total}
              </span>
              <span className="sr-only">
                Livrable {position.index} sur {position.total}
              </span>
            </span>
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Livrable suivant"
              disabled={!position.next}
              onClick={() => position.next && select(position.next)}
            >
              <ChevronRight />
            </Button>
          </nav>
        )}
        <div className="flex shrink-0 items-center gap-0.5">
          {onToggleExpanded && (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-pressed={expanded}
              aria-label={expanded ? "Réduire le panneau" : "Agrandir le panneau"}
              title={expanded ? "Réduire" : "Agrandir"}
              onClick={onToggleExpanded}
            >
              {expanded ? <Minimize2 /> : <Maximize2 />}
            </Button>
          )}
          <Button variant="ghost" size="icon-xs" aria-label="Fermer le panneau" onClick={onClose}>
            <X />
          </Button>
        </div>
      </header>

      {artifacts.length > 1 && (
        <div className="shrink-0 border-b border-atelier-line">
          <div className="flex flex-wrap items-center gap-2 px-3 py-2">
            <button
              type="button"
              aria-expanded={listOpen}
              aria-controls={listId}
              onClick={() => setListOpen((o) => !o)}
              className="inline-flex h-7 items-center gap-1.5 rounded-md pr-1 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground focus-visible:shadow-focus focus-visible:outline-none"
            >
              <ChevronDown className={cn("size-3.5 transition-transform", !listOpen && "-rotate-90")} aria-hidden />
              Livrables
              <Badge variant="secondary" className="tabular-nums">
                {list.length}
              </Badge>
            </button>
            {counts.conversation > 0 && counts.workflow > 0 && (
              <Segmented<ArtifactScope>
                className="ml-auto"
                label="Provenance des livrables"
                value={scope}
                onChange={(next) => {
                  const first = selectionForScope(artifacts, scope, next);
                  if (first) select(first);
                }}
                options={[
                  { value: "conversation", label: <ScopeLabel text="Conversations" count={counts.conversation} /> },
                  { value: "workflow", label: <ScopeLabel text="Workflows" count={counts.workflow} /> },
                ]}
              />
            )}
          </div>
          <ul id={listId} hidden={!listOpen} aria-label="Liste des livrables" className="max-h-44 overflow-y-auto px-2 pb-2">
            {list.map((a) => {
              const active = a.id === selected.id;
              return (
                <li key={a.id}>
                  <button
                    type="button"
                    aria-current={active ? "true" : undefined}
                    onClick={() => select(a.id)}
                    title={a.title}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors focus-visible:shadow-focus focus-visible:outline-none",
                      active ? "atelier-nav-active font-medium" : "text-foreground/90 hover:bg-accent hover:text-foreground",
                    )}
                  >
                    <KindIcon
                      kind={a.kind}
                      className={cn("size-3.5 shrink-0", active ? "text-accent-ink" : "text-muted-foreground")}
                    />
                    <span className="min-w-0 flex-1 truncate">{a.title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{artifactTime(a.createdAt)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <ArtifactViewer key={selected.id} artifact={selected} onRemove={removeSelected} />
    </div>
  );
}

const ScopeLabel = ({ text, count }: { text: string; count: number }) => (
  <>
    {text}
    <span className="text-atelier-muted tabular-nums">{count}</span>
  </>
);
