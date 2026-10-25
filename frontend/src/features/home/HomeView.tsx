"use client";

import { ArrowRight, ArrowUp, Clock, Inbox, Lock, Map as MapIcon, MessageSquare, Waypoints } from "lucide-react";
import { useEffect, useState } from "react";

import { AppChip } from "@/components/layout/AppChip";
import { appDot } from "@/components/layout/AppsMenu";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SectionLabel } from "@/components/ui/section-label";
import { StatusDot } from "@/components/ui/status-dot";
import { AgentTile } from "@/features/chat-agent/AgentTile";
import { agentApps } from "@/features/chat-agent/agentApps";
import { formatWhen } from "@/features/chat-agent/formatWhen";
import { badgeText } from "@/features/workflow-triggers/origin";
import { useInboxCount } from "@/features/workflow-triggers/useInboxCount";
import { homeTemplates } from "@/features/workflows/studio";
import { TemplateCard, TemplateSkeletons, useWorkflowLibrary } from "@/features/workflows/TemplateGallery";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/useChatStore";
import { useNavStore } from "@/stores/useNavStore";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { AgentInfo, AppStatus, ConversationSummary } from "@/types/api";

import { appsSentence, appsSummary, featuredAgents, greeting } from "./home";

/** Agent qui reçoit les questions posées depuis l'accueil. */
const ASK_AGENT = "assistant";

/**
 * Accueil : question rapide à l'Assistant, reprise des dernières conversations, agents mis en
 * avant, état de la suite, « À valider » et workflows de suite (modèles prêts à l'emploi).
 */
export function HomeView({
  agents,
  apps,
  loading,
  onOpenAgent,
}: {
  agents: AgentInfo[];
  apps: AppStatus[];
  loading: boolean;
  onOpenAgent: (name: string) => void;
}) {
  // Heure locale : au rendu serveur « Bonjour », corrigée à l'hydratation (texte qui dépend de l'heure)
  const [hello] = useState(() => (typeof window === "undefined" ? "Bonjour" : greeting(new Date().getHours())));
  const [recent, setRecent] = useState<ConversationSummary[] | null>(null);
  const openConversation = useChatStore((s) => s.open);
  const historyVersion = useChatStore((s) => s.historyVersion);
  const setView = useNavStore((s) => s.setView);
  const setMapOpen = useWorkflowStudioStore((s) => s.setMapOpen);
  const setInboxOpen = useWorkflowStudioStore((s) => s.setInboxOpen);
  const inbox = useInboxCount();

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .recentConversations(4, ctrl.signal)
      .then(setRecent)
      .catch(() => !ctrl.signal.aborted && setRecent([]));
    return () => ctrl.abort();
  }, [historyVersion]);

  const names = new Map(agents.map((a) => [a.name, a]));
  const featured = featuredAgents(agents, 6);
  const summary = appsSummary(apps);
  const askAgent = names.get(ASK_AGENT) ?? agents[0];

  return (
    <main aria-label="Accueil" className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-10 px-5 py-10 sm:px-8 lg:py-14">
        <section className="flex flex-col gap-6">
          <div>
            <p className="text-sm font-medium text-accent-ink" suppressHydrationWarning>
              {hello}
            </p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight text-balance sm:text-4xl">
              Que voulez-vous faire aujourd&apos;hui ?
            </h1>
            <p className="mt-2 max-w-2xl text-[15px] text-muted-foreground">
              {agents.length > 0 ? `${agents.length} agents` : "Des agents"} experts branchés sur vos applications
              Atelier, et des workflows rejouables qui enchaînent Convert, Tab, Viz et Projets — avec Claude ou un
              modèle local, chaque action validée par vous.
            </p>
          </div>
          {askAgent && <QuickAsk agent={askAgent} onAsked={() => onOpenAgent(askAgent.name)} />}
        </section>

        {recent && recent.length > 0 && (
          <section aria-labelledby="home-recent" className="flex flex-col gap-3">
            <SectionLabel id="home-recent">Reprendre</SectionLabel>
            <ul className="grid gap-2 sm:grid-cols-2">
              {recent.map((c) => {
                const owner = names.get(c.agent);
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => {
                        void openConversation(c.id);
                        setView("agents");
                      }}
                      className="group flex w-full items-center gap-3 rounded-xl border border-atelier-line bg-card px-3 py-2.5 text-left transition-[border-color,box-shadow] hover:border-atelier-border hover:shadow-glow"
                    >
                      <AgentTile icon={owner?.icon} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold">{c.title || "Sans titre"}</span>
                        <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                          {owner?.display_name ?? c.agent}
                          <span aria-hidden>·</span>
                          <Clock className="size-3" aria-hidden />
                          {formatWhen(c.updated_at)}
                        </span>
                      </span>
                      <ArrowRight
                        className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-accent-ink"
                        aria-hidden
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <section aria-labelledby="home-agents" className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <SectionLabel id="home-agents">Agents</SectionLabel>
              <span className="text-xs text-muted-foreground">
                Tous dans <span className="lg:hidden">le menu</span>
                <span className="hidden lg:inline">la barre latérale</span>
              </span>
            </div>
            {loading && !agents.length ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="h-32 animate-pulse rounded-xl border border-atelier-line bg-card" />
                ))}
              </div>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2">
                {featured.map((a) => (
                  <li key={a.name}>
                    <AgentCard agent={a} onOpen={() => onOpenAgent(a.name)} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <aside className="flex flex-col gap-6">
            <section aria-labelledby="home-suite" className="flex flex-col gap-3">
              <SectionLabel id="home-suite">Suite Atelier</SectionLabel>
              <Card className="gap-1 p-3">
                <p className="px-1 pb-1 text-[13px] text-muted-foreground">{appsSentence(summary)}</p>
                <ul className="flex flex-col">
                  {apps.map((app) => (
                    <li key={app.id} className="flex items-center gap-2.5 rounded-lg px-1 py-1.5">
                      <StatusDot status={appDot(app)} />
                      <span className="min-w-0 flex-1 truncate text-[13px]" title={app.error ?? app.detail ?? undefined}>
                        {app.label}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {app.available ? "en marche" : app.configured ? "arrêtée" : "non configurée"}
                      </span>
                    </li>
                  ))}
                </ul>
                <Button variant="ghost" size="sm" className="mt-1 justify-start" onClick={() => setMapOpen(true)}>
                  <MapIcon />
                  Carte de la suite
                </Button>
              </Card>
            </section>

            <section aria-labelledby="home-inbox" className="flex flex-col gap-3">
              <SectionLabel id="home-inbox">À valider</SectionLabel>
              <button
                type="button"
                onClick={() => setInboxOpen(true)}
                className={cn(
                  "flex items-center gap-3 rounded-xl border bg-card px-3 py-3 text-left transition-[border-color,box-shadow]",
                  inbox ? "border-atelier-border shadow-glow" : "border-atelier-line hover:border-atelier-border-soft",
                )}
              >
                <span className="grid size-9 place-items-center rounded-lg bg-signature-faint text-accent-ink">
                  <Inbox className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-semibold">
                    {inbox ? `${badgeText(inbox)} en attente` : "Rien en attente"}
                  </span>
                  <span className="block text-xs text-muted-foreground">Étapes de workflows à autoriser</span>
                </span>
                <ArrowRight className="size-4 text-muted-foreground" aria-hidden />
              </button>
            </section>
          </aside>
        </div>

        <SuiteWorkflows />
      </div>
    </main>
  );
}

/**
 * Workflows de suite : trois modèles prêts à l'emploi (les disponibles d'abord) à copier dans un
 * brouillon, tous les modèles, ses workflows. Sans modèles (serveur plus ancien, erreur) : la
 * présentation des workflows de suite et l'accès au Studio.
 */
function SuiteWorkflows() {
  const { state } = useWorkflowLibrary();
  const openList = useWorkflowStudioStore((s) => s.openList);
  const setListSection = useWorkflowStudioStore((s) => s.setListSection);
  const openTemplates = useWorkflowStudioStore((s) => s.openTemplates);
  const picks = state.status === "ready" ? homeTemplates(state.templates) : [];
  const openMine = () => {
    openList(null);
    setListSection("mine");
  };

  return (
    <section aria-labelledby="home-workflows" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <SectionLabel id="home-workflows">Workflows de suite</SectionLabel>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={openMine}>
            <Waypoints />
            Mes workflows
          </Button>
          {picks.length > 0 && (
            <Button variant="ghost" size="sm" onClick={openTemplates}>
              Voir tous les modèles
              <ArrowRight />
            </Button>
          )}
        </div>
      </div>
      {state.status === "loading" && <TemplateSkeletons count={3} className="grid gap-3 md:grid-cols-3" />}
      {picks.length > 0 ? (
        <>
          <p className="-mt-1 text-[13px] text-muted-foreground">
            Des enchaînements prêts à l&apos;emploi : le modèle devient un brouillon que vous relisez, et chaque étape attend
            votre accord.
          </p>
          <ul className="grid gap-3 md:grid-cols-3">
            {picks.map((template) => (
              <li key={template.slug} className="min-w-0">
                <TemplateCard template={template} compact />
              </li>
            ))}
          </ul>
        </>
      ) : (
        state.status !== "loading" && (
          <Card variant="highlight" className="overflow-hidden">
            <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
              <div className="flex flex-wrap items-center gap-1.5" aria-hidden>
                {["convert", "tab", "viz", "projets"].map((id, i) => (
                  <span key={id} className="flex items-center gap-1.5">
                    {i > 0 && <ArrowRight className="size-3.5 text-muted-foreground" />}
                    <AppChip app={id} />
                  </span>
                ))}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-lg font-semibold">Enchaînez vos applications, sans passer par un agent</p>
                <p className="text-[13px] text-muted-foreground">
                  Un relevé converti devient une table Tab, un jeu Viz, des tâches Projets : chaque étape est vérifiée
                  avant de s&apos;exécuter.
                </p>
              </div>
              <Button onClick={openMine}>
                <Waypoints />
                Ouvrir les workflows
              </Button>
            </div>
          </Card>
        )
      )}
    </section>
  );
}

/** Carte d'un agent : tuile, nom, description, applications utilisées. */
function AgentCard({ agent, onOpen }: { agent: AgentInfo; onOpen: () => void }) {
  const apps = agentApps(agent);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex h-full w-full flex-col gap-3 rounded-xl border border-atelier-line bg-card p-4 text-left transition-[border-color,box-shadow] hover:border-atelier-border hover:shadow-glow"
    >
      <span className="flex items-start gap-3">
        <AgentTile icon={agent.icon} variant="glass" />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="truncate text-sm font-semibold">{agent.display_name}</span>
            {agent.local_only && <Lock className="size-3 shrink-0 text-muted-foreground" aria-label="100 % local" />}
          </span>
          {agent.category && <span className="block text-xs text-muted-foreground">{agent.category}</span>}
        </span>
        <MessageSquare
          className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
          aria-hidden
        />
      </span>
      <span className="line-clamp-2 text-[13px] text-muted-foreground">{agent.description}</span>
      {apps.length > 0 && (
        <span className="mt-auto flex flex-wrap gap-1">
          {apps.map((app) => (
            <AppChip key={app} app={app} />
          ))}
        </span>
      )}
    </button>
  );
}

/** Question rapide : ouvre une nouvelle conversation avec l'Assistant et l'envoie. */
function QuickAsk({ agent, onAsked }: { agent: AgentInfo; onAsked: () => void }) {
  const [text, setText] = useState("");
  const setAgent = useChatStore((s) => s.setAgent);
  const reset = useChatStore((s) => s.reset);
  const send = useChatStore((s) => s.send);
  const streaming = useChatStore((s) => s.streaming);

  const submit = () => {
    const value = text.trim();
    if (!value || streaming) return;
    setAgent(agent.name);
    reset();
    void send(value, { localOnly: agent.local_only ?? false });
    setText("");
    onAsked();
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="group relative flex items-center gap-2 rounded-[20px] border border-atelier-border-soft bg-card p-2 pl-3 transition-[border-color,box-shadow] focus-within:border-atelier-border focus-within:shadow-glow"
    >
      <AgentTile icon={agent.icon} size="sm" variant="glass" />
      <label htmlFor="home-ask" className="sr-only">
        Question pour {agent.display_name}
      </label>
      <Input
        id="home-ask"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={`Demander à ${agent.display_name}… (il vous oriente vers le bon agent)`}
        className="h-10 flex-1 border-0 bg-transparent px-0 text-[15px] shadow-none focus-visible:shadow-none"
        autoComplete="off"
      />
      <Button type="submit" size="icon" className="rounded-full" disabled={!text.trim() || streaming} aria-label="Envoyer">
        <ArrowUp />
      </Button>
    </form>
  );
}
