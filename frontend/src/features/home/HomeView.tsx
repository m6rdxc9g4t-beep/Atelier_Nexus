"use client";

import { ArrowRight, ArrowUp, ChevronRight, House, Inbox, Lock, Map as MapIcon, Waypoints } from "lucide-react";
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
    <main aria-label="Accueil" className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* Barre haute de la vue (sous lg, la barre mobile porte déjà le contexte) */}
      <header className="hidden h-11 shrink-0 items-center gap-2 border-b border-atelier-line px-5 lg:flex">
        <House className="size-4 text-atelier-faint" aria-hidden />
        <span className="text-sm font-semibold">Accueil</span>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-9 px-5 py-8 sm:px-8 lg:py-10">
        <section className="flex flex-col gap-5">
          <div>
            <h1 className="text-2xl font-semibold tracking-[-0.012em] text-balance" suppressHydrationWarning>
              {hello}, que voulez-vous faire aujourd&apos;hui ?
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">
              {agents.length > 0 ? `${agents.length} agents` : "Des agents"} experts branchés sur vos applications
              Atelier, et des workflows rejouables qui enchaînent Convert, Tab, Viz et Projets — avec Claude ou un
              modèle local, chaque action validée par vous.
            </p>
          </div>
          {askAgent && <QuickAsk agent={askAgent} onAsked={() => onOpenAgent(askAgent.name)} />}
        </section>

        {recent && recent.length > 0 && (
          <section aria-labelledby="home-recent" className="flex flex-col gap-2">
            <SectionLabel id="home-recent">Reprendre</SectionLabel>
            <ul className="overflow-hidden rounded-lg border border-atelier-border bg-card">
              {recent.map((c) => {
                const owner = names.get(c.agent);
                return (
                  <li key={c.id} className="border-b border-atelier-line last:border-b-0">
                    <button
                      type="button"
                      onClick={() => {
                        void openConversation(c.id);
                        setView("agents");
                      }}
                      className="group flex min-h-10 w-full items-center gap-3 px-3 py-1.5 text-left transition-colors hover:bg-accent"
                    >
                      <AgentTile icon={owner?.icon} variant="bare" />
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{c.title || "Sans titre"}</span>
                      <span className="hidden shrink-0 truncate text-xs text-muted-foreground sm:block">
                        {owner?.display_name ?? c.agent}
                      </span>
                      <span className="shrink-0 text-right text-xs whitespace-nowrap text-atelier-faint tabular-nums sm:w-36">
                        {formatWhen(c.updated_at)}
                      </span>
                      <ChevronRight
                        className="size-4 shrink-0 text-atelier-faint transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
                        aria-hidden
                      />
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <div className="grid grid-cols-[minmax(0,1fr)] gap-9 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <section aria-labelledby="home-agents" className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <SectionLabel id="home-agents">Agents</SectionLabel>
              <span className="text-xs text-atelier-faint">
                Tous dans <span className="lg:hidden">le menu</span>
                <span className="hidden lg:inline">la barre latérale</span>
              </span>
            </div>
            {loading && !agents.length ? (
              <div className="overflow-hidden rounded-lg border border-atelier-border bg-card">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="flex h-[52px] items-center gap-3 border-b border-atelier-line px-3 last:border-b-0">
                    <span className="size-8 animate-pulse rounded-md bg-atelier-hover" />
                    <span className="h-3 w-40 animate-pulse rounded-xs bg-atelier-hover" />
                  </div>
                ))}
              </div>
            ) : (
              <ul className="overflow-hidden rounded-lg border border-atelier-border bg-card">
                {featured.map((a) => (
                  <li key={a.name} className="border-b border-atelier-line last:border-b-0">
                    <AgentCard agent={a} onOpen={() => onOpenAgent(a.name)} />
                  </li>
                ))}
              </ul>
            )}
          </section>

          <aside className="flex flex-col gap-6">
            <section aria-labelledby="home-suite" className="flex flex-col gap-2">
              <SectionLabel id="home-suite">Suite Atelier</SectionLabel>
              <Card className="gap-0.5 p-2">
                <p className="px-1.5 pt-0.5 pb-1 text-xs text-muted-foreground">{appsSentence(summary)}</p>
                <ul className="flex flex-col">
                  {apps.map((app) => {
                    const dot = appDot(app);
                    return (
                      <li key={app.id} className="flex h-8 items-center gap-2.5 px-1.5">
                        {/* Témoin muet : pas de pastille pour une app en marche */}
                        {dot === "up" ? <span className="size-2 shrink-0" aria-hidden /> : <StatusDot status={dot} />}
                        <span className="min-w-0 flex-1 truncate text-sm" title={app.error ?? app.detail ?? undefined}>
                          {app.label}
                        </span>
                        <span
                          className={cn(
                            "text-xs",
                            dot === "down" ? "font-medium text-destructive-ink" : "text-atelier-faint",
                          )}
                        >
                          {app.available ? "en marche" : app.configured ? "arrêtée" : "non configurée"}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <Button variant="ghost" size="sm" className="mt-1 justify-start px-1.5" onClick={() => setMapOpen(true)}>
                  <MapIcon />
                  Carte de la suite
                </Button>
              </Card>
            </section>

            <section aria-labelledby="home-inbox" className="flex flex-col gap-2">
              <SectionLabel id="home-inbox">À valider</SectionLabel>
              {/* Carte de chiffre (.atelier-kpi, coins de 12 px). Validation attendue = état anormal :
                  trait, icône et chiffre ambre ; sinon neutre */}
              <button
                type="button"
                onClick={() => setInboxOpen(true)}
                className={cn(
                  "atelier-kpi group text-left transition-colors hover:bg-accent",
                  inbox && "decision-card",
                )}
              >
                <span className="atelier-kpi__label flex items-center gap-1.5">
                  <Inbox className={cn("size-3.5 shrink-0", inbox ? "text-warning-ink" : "text-atelier-faint")} aria-hidden />
                  Étapes de workflows à autoriser
                </span>
                <span className="flex items-end justify-between gap-3">
                  <span className={cn("atelier-kpi__value", inbox && "text-warning-ink")}>
                    {inbox ? badgeText(inbox) : "0"}
                  </span>
                  <ChevronRight
                    className="mb-1 size-4 text-atelier-faint transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
                    aria-hidden
                  />
                </span>
                <span className="atelier-kpi__note">{inbox ? "en attente" : "Rien en attente"}</span>
              </button>
            </section>
          </aside>
        </div>

        <SuiteWorkflows />
      </div>
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
    <section aria-labelledby="home-workflows" className="flex flex-col gap-2">
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
          <p className="-mt-1 text-sm text-muted-foreground">
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
                <p className="text-[15px] font-semibold">Enchaînez vos applications, sans passer par un agent</p>
                <p className="text-sm text-muted-foreground">
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

/** Ligne d'un agent (liste dense) : icône, nom et catégorie, description, applications utilisées. */
function AgentCard({ agent, onOpen }: { agent: AgentInfo; onOpen: () => void }) {
  const apps = agentApps(agent);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-accent"
    >
      <AgentTile icon={agent.icon} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{agent.display_name}</span>
          {agent.local_only && <Lock className="size-3 shrink-0 text-atelier-faint" aria-label="100 % local" />}
          {agent.category && <span className="truncate text-xs text-atelier-faint">{agent.category}</span>}
        </span>
        <span className="block truncate text-xs text-muted-foreground">{agent.description}</span>
      </span>
      {apps.length > 0 && (
        <span className="hidden shrink-0 gap-1 sm:flex">
          {apps.map((app) => (
            <AppChip key={app} app={app} />
          ))}
        </span>
      )}
      <ChevronRight
        className="size-4 shrink-0 text-atelier-faint transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
        aria-hidden
      />
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
      className="group relative flex items-center gap-2.5 rounded-lg border border-atelier-border-soft bg-card p-1.5 pl-3 transition-[border-color,box-shadow] focus-within:border-primary focus-within:shadow-focus"
    >
      <AgentTile icon={agent.icon} variant="bare" />
      <label htmlFor="home-ask" className="sr-only">
        Question pour {agent.display_name}
      </label>
      <Input
        id="home-ask"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={`Demander à ${agent.display_name}… (il vous oriente vers le bon agent)`}
        className="h-8 flex-1 border-0 bg-transparent px-0 text-base shadow-none focus-visible:shadow-none"
        autoComplete="off"
      />
      <Button type="submit" size="icon" disabled={!text.trim() || streaming} aria-label="Envoyer">
        <ArrowUp />
      </Button>
    </form>
  );
}
