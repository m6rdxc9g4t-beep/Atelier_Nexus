"use client";

import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUpFromLine,
  Bell,
  Bot,
  ChevronRight,
  LayoutGrid,
  Map as MapIcon,
  Plus,
  RefreshCw,
  Rss,
  TriangleAlert,
  Waypoints,
  Wrench,
  X,
} from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";

import { AppIcon } from "@/components/layout/appIcons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Hint } from "@/components/ui/hint";
import { SectionLabel } from "@/components/ui/section-label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AgentIcon } from "@/features/chat-agent/agentMeta";
import { formatWhen } from "@/features/chat-agent/formatWhen";
import { toolLabel } from "@/features/chat-agent/ToolCall";
import { appTheme } from "@/features/workflows-graph/catalog";
import { AppStatusDot, AppTile, KindBadge } from "@/features/workflows-graph/StepBadges";
import { ApiError, api } from "@/lib/api";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import { cn } from "@/lib/utils";
import type { SuiteEventsEntry, SuiteFlow, SuiteMap, SuiteMapAction, SuiteMapApp } from "@/types/api";

import {
  actionUses,
  eventLabel,
  feedWarnings,
  flowsOf,
  layoutFlows,
  mergeEvents,
  splitActions,
  transportLabel,
  triggerChoices,
  workflowsOf,
} from "./suiteMap";

type Loaded<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };
type MapTab = "flows" | "apps" | "events";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

const appName = (map: SuiteMap | null, id: string) =>
  id === "nexus" ? "Nexus" : (map?.apps.find((a) => a.app === id)?.name ?? id);

/**
 * Carte de la suite (onglet du Studio des workflows) : les flux entre applications d'abord,
 * puis, pour chaque application, ce qui y entre (écritures), ce qui en sort (lectures), ses
 * événements, les outils Nexus et agents qui l'utilisent, ses échanges et les workflows qui la
 * touchent ; enfin le fil des derniers événements. Un « + » part d'une action ou d'un événement.
 */
export function SuiteMapView() {
  const [map, setMap] = useState<Loaded<SuiteMap>>({ status: "loading" });
  const [refresh, setRefresh] = useState(0);
  const [tab, setTab] = useState<MapTab>("flows");
  // Application choisie sur le schéma : seule sa carte est montrée dans « Applications »
  const [focus, setFocus] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .suiteMap(ctrl.signal)
      .then((data) => setMap({ status: "ready", data }))
      .catch((err: unknown) => !ctrl.signal.aborted && setMap({ status: "error", message: errorText(err, "Le serveur ne répond pas.") }));
    return () => ctrl.abort();
  }, [refresh]);

  const reload = () => {
    setMap({ status: "loading" });
    setRefresh((r) => r + 1);
  };

  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as MapTab)} className="gap-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <TabsList aria-label="Vues de la carte" className="max-w-full overflow-x-auto">
          <TabsTrigger value="flows">
            <MapIcon />
            Flux
          </TabsTrigger>
          <TabsTrigger value="apps">
            <LayoutGrid />
            Applications
          </TabsTrigger>
          <TabsTrigger value="events">
            <Rss />
            Derniers événements
          </TabsTrigger>
        </TabsList>
        <Button variant="ghost" size="sm" className="ml-auto" aria-label="Actualiser la carte" onClick={reload}>
          <RefreshCw />
          <span className="hidden sm:inline">Actualiser</span>
        </Button>
      </div>
      <p className="max-w-3xl text-sm text-muted-foreground">
        Ce que chaque application reçoit et produit, les agents qui s&apos;en servent et les échanges entre elles. Partez
        d&apos;une action (+) pour créer un workflow, ou d&apos;un événement pour le lancer tout seul.
      </p>

      {map.status === "loading" && tab !== "events" && (
        <div role="status" aria-label="Lecture des manifestes des applications" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-64 rounded-lg" />
          ))}
        </div>
      )}
      {map.status === "error" && tab !== "events" && (
        <Callout
          tone="destructive"
          title="Carte indisponible"
          action={
            <Button size="sm" variant="outline" onClick={reload}>
              <RefreshCw />
              Réessayer
            </Button>
          }
        >
          {map.message}
        </Callout>
      )}
      {map.status === "ready" && (
        <>
          <TabsContent value="flows">
            <FlowsView
              map={map.data}
              onPick={(app) => {
                setFocus(app);
                setTab("apps");
              }}
            />
          </TabsContent>
          <TabsContent value="apps">
            <AppsGrid map={map.data} flows={map.data.flows} focus={focus} onClearFocus={() => setFocus(null)} />
          </TabsContent>
        </>
      )}
      <TabsContent value="events">
        <EventsFeed map={map.status === "ready" ? map.data : null} refresh={refresh} />
      </TabsContent>
    </Tabs>
  );
}

// ─── Applications ────────────────────────────────────────────────

function AppsGrid({ map, flows, focus, onClearFocus }: { map: SuiteMap; flows: SuiteFlow[]; focus: string | null; onClearFocus: () => void }) {
  if (map.apps.length === 0) return <p className="text-sm text-muted-foreground">Aucune application connue du hub.</p>;
  const shown = focus ? map.apps.filter((a) => a.app === focus) : map.apps;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
      {focus && shown.length > 0 && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>
            Application : <span className="font-medium text-foreground">{appName(map, focus)}</span>
          </span>
          <Button variant="ghost" size="sm" onClick={onClearFocus}>
            <X />
            Toutes les applications
          </Button>
        </div>
      )}
      <ul className="grid items-start gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(shown.length ? shown : map.apps).map((app) => (
          <AppCard key={app.app} app={app} map={map} flows={flows} />
        ))}
      </ul>
    </div>
  );
}

/** Section toujours ouverte (entrées, sorties) : étiquette et compteur. */
function Section({ icon: Icon, title, count, children }: { icon: typeof Bell; title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1">
      <SectionLabel as="p" className="flex items-center gap-1.5">
        <Icon className="size-3.5" aria-hidden />
        {title}
        <span className="font-normal tabular-nums">({count})</span>
      </SectionLabel>
      {count > 0 ? children : <p className="text-xs text-muted-foreground">Aucune</p>}
    </section>
  );
}

/** Section repliée (événements, outils, agents, échanges, workflows), avec son compteur. */
function Fold({ icon: Icon, title, count, children }: { icon: typeof Bell; title: string; count: number; children: React.ReactNode }) {
  const head = (
    <>
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{title}</span>
      <span className="tabular-nums">{count}</span>
    </>
  );
  if (count === 0)
    return <p className="flex items-center gap-1.5 py-1 pr-1 pl-5 text-xs text-muted-foreground">{head}</p>;
  return (
    <details className="group min-w-0">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md py-1 pr-1 text-xs font-medium text-muted-foreground select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 shrink-0 transition-transform group-open:rotate-90" aria-hidden />
        {head}
      </summary>
      <div className="pt-1 pb-1.5 pl-6">{children}</div>
    </details>
  );
}

const plusClass = "shrink-0 text-atelier-faint hover:text-foreground";
/**
 * Ligne d'une fiche : le libellé prend la place et passe à la ligne, étiquette et « + » restent
 * entiers, alignés sur sa première ligne (au doigt, où le « + » fait 40 px : centrés).
 */
const lineClass = "group/hint relative flex items-start gap-1.5 rounded-md py-0.5 pr-0.5 pl-1.5 hover:bg-accent pointer-coarse:items-center";
const lineLabelClass = "min-w-0 flex-1 py-0.5 text-sm break-words";
/** Précision du « + », montrée dans la bulle de la ligne quand il est survolé ou a le focus. */
const plusHintClass = "hidden text-muted-foreground group-has-[button:focus-visible]/hint:block group-has-[button:hover]/hint:block";

/** Échanges d'une application, en texte : sens, autre application, nature et transport. */
function ExchangeLines({ map, flows, app, className }: { map: SuiteMap; flows: SuiteFlow[]; app: string; className?: string }) {
  const { incoming, outgoing } = flowsOf(flows, app);
  const line = (f: SuiteFlow, other: string, Icon: typeof ArrowLeft, sense: string, key: string) => (
    <li key={key} className="flex items-start gap-1.5">
      <Icon className="mt-[3px] size-3.5 shrink-0 text-atelier-faint" aria-hidden />
      <span className="min-w-0 break-words">
        <span className="sr-only">{sense} </span>
        <span className="text-foreground">{appName(map, other)}</span> · {f.label} <span className="text-atelier-faint">· par {f.via}</span>
      </span>
    </li>
  );
  return (
    <ul className={cn("grid grid-cols-[minmax(0,1fr)] gap-0.5 text-sm text-muted-foreground", className)}>
      {incoming.map((f, i) => line(f, f.from, ArrowLeft, "Reçoit de", `in-${i}`))}
      {outgoing.map((f, i) => line(f, f.to, ArrowRight, "Envoie à", `out-${i}`))}
    </ul>
  );
}

function ActionLine({ app, action }: { app: string; action: SuiteMapAction }) {
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const hint = useId();
  return (
    <li className={lineClass}>
      <span className={lineLabelClass}>{action.label}</span>
      {action.kind !== "read" && <KindBadge kind={action.kind} className="mt-0.5 pointer-coarse:mt-0" />}
      <Button
        variant="ghost"
        size="icon-xs"
        className={plusClass}
        aria-label={`Créer un workflow à partir de « ${action.label} »`}
        aria-describedby={hint}
        onClick={() => openEditor({ kind: "new", agent: null, uses: actionUses(app, action.id) })}
      >
        <Plus />
      </Button>
      <Hint id={hint}>
        <span className="font-mono">{action.kind === "read" ? `${action.id} · ${action.output_format}` : action.id}</span>
        <span className={plusHintClass}>+ : créer un workflow à partir de cette action</span>
      </Hint>
    </li>
  );
}

function AppCard({ app, map, flows }: { app: SuiteMapApp; map: SuiteMap; flows: SuiteFlow[] }) {
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const { inputs, outputs } = splitActions(app);
  const { incoming, outgoing } = flowsOf(flows, app.app);
  const workflows = workflowsOf(map, app.app);
  const actionLine = (action: SuiteMapAction) => <ActionLine key={action.id} app={app.app} action={action} />;

  return (
    <li className="min-w-0">
      <Card className="gap-3 p-3.5">
        <header className="flex items-start gap-2.5">
          <AppTile app={app.app} color={app.color} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold">{app.name}</h3>
            <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-atelier-faint">
              <AppStatusDot status={app.status} className="text-xs" />
              {app.transport && <span>· par {transportLabel(app.transport)}</span>}
            </p>
          </div>
        </header>

        <Section icon={ArrowDownToLine} title="Entrées" count={inputs.length}>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-0.5">{inputs.map(actionLine)}</ul>
        </Section>
        <Section icon={ArrowUpFromLine} title="Sorties" count={outputs.length}>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-0.5">{outputs.map(actionLine)}</ul>
        </Section>
        {app.status === "no_contract" && app.actions.length === 0 && (
          <p className="flex items-start gap-1.5 text-xs text-warning-ink">
            <TriangleAlert className="mt-px size-3.5 shrink-0 text-warning" aria-hidden />
            Cette application ne décrit pas encore ses actions : seuls les outils Nexus la relient au hub.
          </p>
        )}

        <div className="grid grid-cols-[minmax(0,1fr)] border-t border-atelier-line pt-2">
          <Fold icon={Bell} title="Événements" count={app.events.length}>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
              {app.events.map((ev) => (
                <EventLine key={ev.type} app={app.app} type={ev.type} label={ev.label} />
              ))}
            </ul>
          </Fold>

          <Fold icon={Wrench} title="Outils Nexus" count={app.nexus_tools.length}>
            {/* La bulle se pose sous la liste (ancêtre `relative`), à la largeur de la fiche */}
            <ul className="relative flex flex-wrap gap-1">
              {app.nexus_tools.map((tool) => (
                <li key={tool.name} className="group/hint max-w-full">
                  <Badge variant={tool.kind === "write" ? "warning" : "outline"} className="max-w-full">
                    <span className="truncate">{toolLabel(tool.name)}</span>
                  </Badge>
                  <Hint>
                    <span className="font-mono">{tool.name}</span>
                    <span className="text-muted-foreground">
                      Boîte {tool.toolset} · {tool.kind === "write" ? "écriture validée" : "lecture"}
                    </span>
                  </Hint>
                </li>
              ))}
            </ul>
          </Fold>

          <Fold icon={Bot} title="Agents" count={app.agents.length}>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-1">
              {app.agents.map((agent) => (
                <li key={agent.name} className="flex items-start gap-1.5 text-sm">
                  <AgentIcon icon={agent.icon} className="mt-[3px] size-3.5 shrink-0 text-atelier-faint" aria-hidden />
                  <span className="min-w-0 flex-1 break-words">{agent.display_name}</span>
                  <span className="shrink-0 pt-px text-xs text-muted-foreground">{agent.writes ? "lit et écrit" : "lecture seule"}</span>
                </li>
              ))}
            </ul>
          </Fold>

          <Fold icon={Waypoints} title="Échanges" count={incoming.length + outgoing.length}>
            <ExchangeLines map={map} flows={flows} app={app.app} />
          </Fold>

          <Fold icon={Waypoints} title="Workflows" count={workflows.length}>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
              {workflows.map((wf) => (
                <li key={wf.id}>
                  <button
                    type="button"
                    className="w-full rounded-md px-1.5 py-0.5 text-left text-sm break-words text-accent-ink hover:bg-accent hover:underline"
                    onClick={() => openEditor({ kind: "open", id: wf.id })}
                  >
                    {wf.title}
                  </button>
                </li>
              ))}
            </ul>
          </Fold>
        </div>
      </Card>
    </li>
  );
}

/** Événement d'une fiche : libellé, « + » s'il peut lancer un workflow, type technique dans la bulle. */
function EventLine({ app, type, label }: { app: string; type: string; label: string }) {
  const hint = useId();
  return (
    <li className={lineClass}>
      <span className={lineLabelClass}>{label}</span>
      <EventTriggerMenu app={app} type={type} label={label} describedBy={hint} />
      <Hint id={hint}>
        <span className="font-mono">{type}</span>
        <span className={plusHintClass}>+ : lancer un workflow quand cet événement arrive</span>
      </Hint>
    </li>
  );
}

/** « + » d'un événement : workflow déclenché par cet événement (nouveau, ou celui ouvert en dernier). */
function EventTriggerMenu({ app, type, label, describedBy }: { app: string; type: string; label: string; describedBy: string }) {
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const last = useWorkflowStudioStore((s) => s.lastWorkflow);
  const choices = triggerChoices(app, type, last);
  if (choices.length === 0) return null;
  const button = (props: React.ComponentProps<typeof Button>) => (
    <Button
      variant="ghost"
      size="icon-xs"
      className={plusClass}
      aria-label={`Lancer un workflow quand « ${label} » arrive`}
      aria-describedby={describedBy}
      {...props}
    >
      <Plus />
    </Button>
  );
  // Un seul choix : pas de menu
  if (choices.length === 1) return button({ onClick: () => openEditor(choices[0]!.target) });
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{button({})}</DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <DropdownMenuLabel className="truncate">Quand « {label} » arrive</DropdownMenuLabel>
        {choices.map((choice) => (
          <DropdownMenuItem key={choice.label} onSelect={() => openEditor(choice.target)}>
            <span className="min-w-0">{choice.label}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// ─── Flux ────────────────────────────────────────────────────────

/** Taille du schéma (unités SVG = pixels à 100 %) : le texte y reste à 12 px. */
const FLOW_SIZE = 480;

function FlowsView({ map, onPick }: { map: SuiteMap; onPick: (app: string) => void }) {
  const layout = layoutFlows(map, FLOW_SIZE);
  if (layout.edges.length === 0) return <p className="text-sm text-muted-foreground">Aucun échange déclaré entre les applications.</p>;
  const known = new Set(map.apps.map((a) => a.app));
  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
      {/* Défilement interne sous 480 px : le texte du schéma ne descend jamais sous 12 px */}
      <figure className="overflow-x-auto rounded-lg border border-atelier-border bg-card p-2">
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="img"
          aria-labelledby="suite-flows-title"
          className="mx-auto block h-auto w-full max-w-xl min-w-[480px]"
        >
          <title id="suite-flows-title">Schéma des échanges entre les applications de la suite</title>
          <defs>
            <marker id="suite-flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-atelier-faint" />
            </marker>
          </defs>
          {layout.edges.map((edge) => (
            <g key={edge.key}>
              <path d={edge.path} fill="none" strokeWidth={1.25} markerEnd="url(#suite-flow-arrow)" className="stroke-atelier-border-soft" />
              <text
                x={edge.labelX}
                y={edge.labelY}
                textAnchor="middle"
                strokeWidth={4}
                style={{ paintOrder: "stroke" }}
                className="fill-muted-foreground stroke-card text-[12px]"
              >
                {edge.label}
              </text>
            </g>
          ))}
          {layout.nodes.map((node) => {
            const theme = appTheme(node.id, map.apps.find((a) => a.app === node.id)?.color);
            const name = appName(map, node.id).replace(/^Atelier /, "");
            const pickable = known.has(node.id);
            return (
              <g
                key={node.id}
                {...theme}
                {...(pickable
                  ? {
                      role: "button",
                      tabIndex: 0,
                      "aria-label": `Voir l'application ${appName(map, node.id)}`,
                      className: "cursor-pointer outline-none [&:focus-visible_.tile-ring]:stroke-primary [&:hover_.tile-ring]:stroke-atelier-faint",
                      onClick: () => onPick(node.id),
                      onKeyDown: (e: React.KeyboardEvent) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onPick(node.id);
                        }
                      },
                    }
                  : {})}
              >
                {/* Icône de l'app (charte v2) : carré arrondi en dégradé de SA signature, glyphe blanc */}
                <defs>
                  <linearGradient id={`suite-tile-${node.id}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" style={{ stopColor: "color-mix(in oklab, var(--atelier-signature) 78%, white)" }} />
                    <stop offset="1" style={{ stopColor: "var(--atelier-signature)" }} />
                  </linearGradient>
                </defs>
                <rect
                  x={node.x - 24}
                  y={node.y - 24}
                  width={48}
                  height={48}
                  rx={13}
                  strokeWidth={2}
                  className="tile-ring fill-none stroke-transparent"
                />
                <rect x={node.x - 20} y={node.y - 20} width={40} height={40} rx={10} fill={`url(#suite-tile-${node.id})`} />
                <AppIcon
                  app={node.id}
                  x={node.x - 11}
                  y={node.y - 11}
                  width={22}
                  height={22}
                  strokeWidth={2}
                  className="text-white"
                  aria-hidden
                />
                <text
                  x={node.x}
                  y={node.y + 40}
                  textAnchor="middle"
                  strokeWidth={4}
                  style={{ paintOrder: "stroke" }}
                  className="fill-foreground stroke-card text-[12px] font-medium"
                >
                  {name}
                </text>
              </g>
            );
          })}
        </svg>
        <figcaption className="px-1 pt-1 text-xs text-muted-foreground">Choisissez une application pour voir sa fiche.</figcaption>
      </figure>
      <table className="w-full text-sm">
        <caption className="mb-2 text-left text-xs text-muted-foreground">Échanges entre les applications</caption>
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="border-b border-atelier-line py-1.5 pr-2 font-medium">De</th>
            <th className="border-b border-atelier-line py-1.5 pr-2 font-medium">Vers</th>
            <th className="border-b border-atelier-line py-1.5 pr-2 font-medium">Quoi</th>
            <th className="border-b border-atelier-line py-1.5 font-medium">Par</th>
          </tr>
        </thead>
        <tbody>
          {map.flows.map((f, i) => (
            <tr key={i}>
              <td className="border-b border-atelier-line py-1.5 pr-2">{appName(map, f.from)}</td>
              <td className="border-b border-atelier-line py-1.5 pr-2">{appName(map, f.to)}</td>
              <td className="border-b border-atelier-line py-1.5 pr-2">{f.label}</td>
              <td className="border-b border-atelier-line py-1.5 text-muted-foreground">{f.via}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Derniers événements ─────────────────────────────────────────

function EventsFeed({ map, refresh }: { map: SuiteMap | null; refresh: number }) {
  const [state, setState] = useState<Loaded<SuiteEventsEntry[]>>({ status: "loading" });
  const load = useCallback((signal?: AbortSignal) => {
    api
      .suiteEvents({ limit: 30 }, signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) => !signal?.aborted && setState({ status: "error", message: errorText(err, "Événements indisponibles.") }));
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal);
    // Fil vivant : relu toutes les 15 s tant que l'onglet est ouvert
    const timer = setInterval(() => load(ctrl.signal), 15_000);
    return () => {
      ctrl.abort();
      clearInterval(timer);
    };
  }, [load, refresh]);

  if (state.status === "loading")
    return (
      <div role="status" aria-label="Lecture des événements" className="grid gap-1.5">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-11 rounded-lg" />
        ))}
      </div>
    );
  if (state.status === "error")
    return (
      <Callout tone="destructive" role="alert">
        {state.message}
      </Callout>
    );
  const feed = mergeEvents(state.data);
  const warnings = feedWarnings(state.data);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
      {warnings.map((w) => (
        <Callout key={w.app} tone="warning" className="py-2 text-xs">
          {appName(map, w.app)} : {w.text}
        </Callout>
      ))}
      {feed.length === 0 ? (
        <p className="text-sm text-muted-foreground">Aucun événement récent.</p>
      ) : (
        <ol className="overflow-hidden rounded-lg border border-atelier-border bg-card" aria-live="polite">
          {feed.map((ev) => (
            <li
              key={`${ev.app}-${ev.seq}`}
              title={ev.type}
              className="flex min-h-10 items-center gap-2.5 border-b border-atelier-line px-3 py-1.5 last:border-b-0"
            >
              <AppTile app={ev.app} color={map?.apps.find((a) => a.app === ev.app)?.color} size="xs" />
              <p className="min-w-0 flex-1 truncate text-sm">
                {eventLabel(map, ev.app, ev.type)} · <span className="font-medium">{ev.subject.label || ev.subject.id}</span>
              </p>
              <time dateTime={ev.at} className="shrink-0 text-xs text-atelier-faint tabular-nums">
                {formatWhen(ev.at)}
              </time>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
