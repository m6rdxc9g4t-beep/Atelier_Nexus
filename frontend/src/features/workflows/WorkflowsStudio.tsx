"use client";

import { Inbox, LibraryBig, Map as MapIcon, Waypoints, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SuiteMapView } from "@/features/suite-map/SuiteMapDialog";
import { InboxView } from "@/features/workflow-triggers/InboxDialog";
import { badgeText, inboxLabel } from "@/features/workflow-triggers/origin";
import { useInboxCount } from "@/features/workflow-triggers/useInboxCount";
import { useNavStore } from "@/stores/useNavStore";
import { type ListSection, useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo } from "@/types/api";

import { shownSection, studioTab, type StudioTab } from "./studio";
import { TemplateGallery } from "./TemplateGallery";
import { MyWorkflows } from "./WorkflowsDialog";

/**
 * Studio des workflows de suite : vue plein cadre de la zone principale (à la place de l'accueil
 * ou de la conversation), affichée dès que la liste, la carte ou « À valider » est ouverte dans
 * `useWorkflowStudioStore`. Onglets : Workflows (mes workflows · modèles de la suite), Carte de
 * la suite, À valider. L'éditeur en graphe s'ouvre par-dessus (fenêtre plein écran) ; fermer le
 * Studio revient à l'accueil ou à la conversation.
 */
export function WorkflowsStudio({ agents }: { agents: AgentInfo[] }) {
  const tab = useWorkflowStudioStore((s) => studioTab(s)) ?? "workflows";
  const listAgent = useWorkflowStudioStore((s) => s.listAgent);
  const section = useWorkflowStudioStore((s) => shownSection(s.listSection, s.listAgent));
  const openList = useWorkflowStudioStore((s) => s.openList);
  const setListSection = useWorkflowStudioStore((s) => s.setListSection);
  const openTemplates = useWorkflowStudioStore((s) => s.openTemplates);
  const setMapOpen = useWorkflowStudioStore((s) => s.setMapOpen);
  const setInboxOpen = useWorkflowStudioStore((s) => s.setInboxOpen);
  const closeStudio = useWorkflowStudioStore((s) => s.closeStudio);
  const view = useNavStore((s) => s.view);
  const count = useInboxCount();
  const pending = count ?? 0;

  const select = (next: StudioTab) => {
    // L'API du store ne change pas : chaque onglet est une des trois « fenêtres » d'avant
    if (next === "workflows") openList(listAgent);
    else if (next === "map") setMapOpen(true);
    else setInboxOpen(true);
  };
  const back = view === "home" ? "retour à l'accueil" : "retour à la conversation";

  return (
    <section aria-label="Workflows de suite" className="flex min-h-0 min-w-0 flex-1 flex-col">
      <Tabs value={tab} onValueChange={(v) => select(v as StudioTab)} className="min-h-0 flex-1 gap-0">
        <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-atelier-line px-4 py-2 md:h-14 md:flex-nowrap md:py-0">
          <span className="grid size-9 shrink-0 place-items-center rounded-[10px] border border-atelier-line bg-signature-faint text-accent-ink">
            <Waypoints className="size-[18px]" aria-hidden />
          </span>
          <h1 className="text-[15px] font-semibold tracking-tight">Workflows</h1>
          <TabsList
            aria-label="Sections du Studio des workflows"
            className="order-last w-full max-w-full justify-start overflow-x-auto md:order-none md:ml-3 md:w-fit"
          >
            <TabsTrigger value="workflows">
              <Waypoints />
              Workflows
            </TabsTrigger>
            <TabsTrigger value="map">
              <MapIcon />
              Carte de la suite
            </TabsTrigger>
            <TabsTrigger value="inbox" aria-label={count === null ? "À valider" : inboxLabel(pending)}>
              <Inbox />
              À valider
              {pending > 0 && (
                <span
                  aria-hidden
                  className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[11px] leading-none font-semibold text-primary-foreground tabular-nums"
                >
                  {badgeText(pending)}
                </span>
              )}
            </TabsTrigger>
          </TabsList>
          <Button variant="ghost" size="sm" className="ml-auto" aria-label={`Fermer : ${back}`} title={`Fermer : ${back}`} onClick={closeStudio}>
            <X />
            <span className="hidden sm:inline">Fermer</span>
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-7xl px-4 py-5 sm:px-6 lg:py-6">
            <TabsContent value="workflows" className="grid grid-cols-[minmax(0,1fr)] gap-4">
              <Segmented<ListSection>
                label="Afficher"
                value={section}
                // Les modèles sont de la suite : quitter la portée d'un agent pour les montrer
                onChange={(next) => (next === "templates" ? openTemplates() : setListSection("mine"))}
                options={[
                  {
                    value: "mine",
                    label: (
                      <>
                        <Waypoints aria-hidden />
                        Mes workflows
                      </>
                    ),
                  },
                  {
                    value: "templates",
                    label: (
                      <>
                        <LibraryBig aria-hidden />
                        Modèles de la suite
                      </>
                    ),
                  },
                ]}
              />
              {section === "mine" ? (
                // Nouvelle portée à chaque agent suivi (bouton Workflows d'une conversation)
                <MyWorkflows key={listAgent ?? ""} agents={agents} onShowTemplates={openTemplates} />
              ) : (
                <TemplateGallery />
              )}
            </TabsContent>
            <TabsContent value="map">
              <SuiteMapView />
            </TabsContent>
            <TabsContent value="inbox">
              <InboxView />
            </TabsContent>
          </div>
        </div>
      </Tabs>
    </section>
  );
}
