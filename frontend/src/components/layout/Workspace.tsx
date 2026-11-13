"use client";

import { RefreshCw, ServerOff } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";
import { HomeView } from "@/features/home/HomeView";
import { studioTab } from "@/features/workflows/studio";
import { useBackend } from "@/hooks/useBackend";
import { API_URL } from "@/lib/api";
import { readAgentLink, withoutAgentLink } from "@/lib/deepLink";
import { PROVIDER_SHORT, effectiveProvider } from "@/lib/labels";
import { useChatStore } from "@/stores/useChatStore";
import { useNavStore } from "@/stores/useNavStore";
import { useUiStore } from "@/stores/useUiStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";

import { AppHeader } from "./AppHeader";
import { AppSidebar } from "./AppSidebar";
import { LAZY_VIEWS, whenIdle } from "./lazyViews";

// Vues chargées à la demande : hors du paquet initial (l'accueil s'affiche sans elles), puis
// préchargées quand le navigateur est au repos pour s'ouvrir sans attente (lazyViews.ts).
/** Zone principale en attendant une vue (même encombrement : le panneau Livrables ne bouge pas). */
const ViewLoading = () => <div aria-busy className="min-w-0 flex-1" />;
const ChatPanel = dynamic(LAZY_VIEWS.chat, { ssr: false, loading: ViewLoading });
const WorkflowsStudio = dynamic(LAZY_VIEWS.studio, { ssr: false, loading: ViewLoading });
const WorkflowGraphDialog = dynamic(LAZY_VIEWS.graphEditor, { ssr: false });
const SettingsDialog = dynamic(LAZY_VIEWS.settings, { ssr: false });
const AgentEditor = dynamic(LAZY_VIEWS.agentEditor, { ssr: false });

/** Vrai dès que `flag` l'a été une fois : une fenêtre chargée à la demande reste montée ensuite. */
function useOnce(flag: boolean): boolean {
  const [seen, setSeen] = useState(flag);
  if (flag && !seen) setSeen(true);
  return seen || flag;
}

/**
 * Écran principal : barre latérale (navigation + agents) · accueil, conversation ou Studio des
 * workflows · artefacts.
 */
export function Workspace() {
  const { agents, providers, apps, loading, error, reload } = useBackend();
  const [editor, setEditor] = useState<{ open: boolean; editing: string | null }>({
    open: false,
    editing: null,
  });
  const agent = useChatStore((s) => s.agent);
  const setAgent = useChatStore((s) => s.setAgent);
  const provider = useChatStore((s) => s.provider);
  const view = useNavStore((s) => s.view);
  const setView = useNavStore((s) => s.setView);
  const drawerOpen = useNavStore((s) => s.drawerOpen);
  const setDrawerOpen = useNavStore((s) => s.setDrawerOpen);
  // Studio des workflows (liste, carte, « À valider ») : vue plein cadre à la place de l'accueil
  // ou de la conversation, gardée derrière l'éditeur en graphe ouvert depuis lui
  const studio = useWorkflowStudioStore((s) => studioTab(s));
  const closeStudio = useWorkflowStudioStore((s) => s.closeStudio);
  // Fenêtres montées à leur première ouverture seulement (leur code n'est pas dans le paquet initial)
  const graphEditor = useOnce(useWorkflowStudioStore((s) => s.editor !== null));
  const settings = useOnce(useUiStore((s) => s.settingsOpen));

  // Navigateur au repos : le code des autres vues est préchargé
  useEffect(() => whenIdle(() => Object.values(LAZY_VIEWS).forEach((load) => void load().catch(() => undefined))), []);

  // Agent inexistant (supprimé, catalogue changé) : on revient au premier disponible
  useEffect(() => {
    if (agents.length && !agents.some((a) => a.name === agent)) setAgent(agents[0]!.name);
  }, [agents, agent, setAgent]);

  const current = agents.find((a) => a.name === agent);
  // Conversation bloquée : serveur en erreur, ou moteur qui répondrait non configuré. ChatPanel
  // en fait un seul message ; pour le moteur, avec le bouton « Ouvrir les réglages ».
  const engine = providers.find((p) => p.name === effectiveProvider(current, provider, providers));
  const blocked = error ?? (engine && !engine.configured ? `${PROVIDER_SHORT[engine.name]} n'est pas configuré.` : null);

  const openAgent = (name: string) => {
    closeStudio();
    setAgent(name);
    setView("agents");
  };

  // Lien profond (Atelier Hub) : `?agent=<nom>` ouvre la conversation avec cet agent, une seule fois,
  // quand le catalogue est chargé ; un nom inconnu laisse l'accueil. Le paramètre est retiré de l'adresse.
  const linkHandled = useRef(false);
  useEffect(() => {
    if (linkHandled.current || !agents.length) return;
    linkHandled.current = true;
    const name = readAgentLink(window.location.search);
    if (!name) return;
    window.history.replaceState(window.history.state, "", withoutAgentLink(window.location.href));
    if (!agents.some((a) => a.name === name)) return;
    closeStudio();
    setAgent(name);
    setView("agents");
  }, [agents, closeStudio, setAgent, setView]);
  const sidebar = (
    <AppSidebar
      agents={agents}
      apps={apps}
      onCreateAgent={() => setEditor({ open: true, editing: null })}
      onEditAgent={(name) => setEditor({ open: true, editing: name })}
    />
  );

  return (
    // Coquille : exactement la hauteur de la fenêtre, et rien n'en sort. La page elle-même ne défile
    // jamais ; seules défilent les zones de contenu (accueil, conversation, Studio, liste des agents),
    // toutes positionnées (`relative`) : un élément hors flux (`sr-only`, case à cocher Radix) placé
    // dans une zone non positionnée échappe à son `overflow`, allonge le document et, au défilement,
    // emporte la barre latérale avec la page. `relative` + `overflow-clip` : même un oubli reste dedans.
    <div data-slot="app-shell" className="relative flex h-dvh overflow-clip">
      {/* Grand écran : barre latérale sur toute la hauteur, toujours en place (sa liste d'agents défile
          en elle, son pied reste visible). Toujours montée (le choix du thème s'y applique). */}
      <aside className="hidden h-full w-[232px] shrink-0 border-r border-atelier-line bg-sidebar lg:block">{sidebar}</aside>
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent aria-describedby={undefined} className="lg:hidden">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Accueil, workflows, carte de la suite, agents et réglages</SheetDescription>
          {sidebar}
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader agents={agents} />
        <div className="flex min-h-0 flex-1">
          {error && !agents.length && !loading ? (
            <EmptyState
              icon={ServerOff}
              title="Le serveur Atelier Nexus ne répond pas"
              className="m-auto max-w-md"
              actions={
                <Button variant="outline" onClick={() => void reload()}>
                  <RefreshCw />
                  Réessayer
                </Button>
              }
            >
              L&apos;interface attend l&apos;API sur <code className="font-mono">{API_URL}</code>. Lancez-la avec{" "}
              <code className="font-mono">uvicorn main:app --port 8100</code> dans le dossier backend.
            </EmptyState>
          ) : studio ? (
            <WorkflowsStudio agents={agents} />
          ) : view === "home" ? (
            <HomeView agents={agents} apps={apps} loading={loading} onOpenAgent={openAgent} />
          ) : (
            <ChatPanel agent={current} agents={agents} providers={providers} blocked={blocked} />
          )}

          <ArtifactPanel />
        </div>
      </div>

      {/* Éditeur en graphe : fenêtre plein écran, par-dessus le Studio ou la conversation */}
      {graphEditor && <WorkflowGraphDialog agents={agents} />}
      {settings && <SettingsDialog onSaved={reload} />}

      {editor.open && (
        <AgentEditor
          key={editor.editing ?? "nouvel-agent"}
          open
          editing={editor.editing}
          onOpenChange={(open) => setEditor((e) => ({ ...e, open }))}
          onSaved={async (name) => {
            // Sélection une fois le catalogue rechargé (sinon l'agent serait jugé inexistant)
            await reload();
            if (name) openAgent(name);
          }}
        />
      )}
    </div>
  );
}
