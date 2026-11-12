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
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

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
  suiteFlows,
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
  const data = map.status === "ready" ? map.data : null;
  // Échanges du hub et ceux que les workflows ouvrent : les mêmes sur le schéma, la liste et les fiches
  const flows = useMemo(() => (data ? suiteFlows(data) : []), [data]);

  const top = useRef<HTMLDivElement>(null);

  return (
    <Tabs ref={top} value={tab} onValueChange={(v) => setTab(v as MapTab)} className="gap-4">
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
              flows={flows}
              onPick={(app) => {
                setFocus(app);
                setTab("apps");
                // « Voir la fiche » est sous le schéma et disparaît avec lui : la fiche s'ouvre en haut
                // de page, et le focus passe à l'onglet « Applications » (jamais perdu au clavier)
                requestAnimationFrame(() => {
                  top.current?.scrollIntoView({ block: "start" });
                  top.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus({ preventScroll: true });
                });
              }}
            />
          </TabsContent>
          <TabsContent value="apps">
            <AppsGrid map={map.data} flows={flows} focus={focus} onClearFocus={() => setFocus(null)} />
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

/** Largeur disponible d'un élément, suivie au redimensionnement (480 avant la première mesure). */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(480);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0]?.contentRect.width ?? 0);
      if (next > 0) setWidth(next);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

const plural = (n: number, one: string, many: string) => `${n} ${n > 1 ? many : one}`;

/**
 * Schéma des échanges : placé par `layoutFlows` à la largeur disponible (jamais de défilement
 * horizontal, texte à 12 px). Survol ou focus d'une application : ses liens ressortent, les autres
 * s'estompent. Clic, Entrée ou Espace : l'application est choisie, ses échanges s'écrivent sous le
 * schéma, avec le bouton « Voir la fiche ». La liste complète reste en texte à côté.
 */
function FlowsView({ map, flows, onPick }: { map: SuiteMap; flows: SuiteFlow[]; onPick: (app: string) => void }) {
  const [box, width] = useWidth<HTMLDivElement>();
  const layout = useMemo(() => layoutFlows(map, width), [map, width]);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const titleId = useId();
  const listId = useId();
  if (layout.links.length === 0) return <p className="text-sm text-muted-foreground">Aucun échange déclaré entre les applications.</p>;
  const known = new Set(map.apps.map((a) => a.app));
  const chosen = selected && layout.nodes.some((n) => n.id === selected) ? selected : null;
  const active = hovered ?? chosen;
  const touches = (link: { a: string; b: string }, id: string) => link.a === id || link.b === id;
  const near = new Set(active ? layout.links.filter((l) => touches(l, active)).flatMap((l) => [l.a, l.b]) : []);
  const count = (id: string) => flows.filter((f) => f.from !== f.to && (f.from === id || f.to === id)).length;
  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
      <figure className="min-w-0 rounded-lg border border-atelier-border bg-card p-2">
        <div ref={box} className="min-w-0">
          <svg
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            width={layout.width}
            height={layout.height}
            role="group"
            aria-labelledby={titleId}
            aria-describedby={listId}
            className="mx-auto block h-auto max-w-full"
          >
            <title id={titleId}>Schéma des échanges entre les applications de la suite</title>
            <g aria-hidden>
              {layout.rail && (
                <line
                  x1={layout.rail.x}
                  y1={layout.rail.y1}
                  x2={layout.rail.x}
                  y2={layout.rail.y2}
                  strokeWidth={1.5}
                  strokeLinecap="round"
                  className="stroke-atelier-border-soft"
                />
              )}
              {layout.links.map((link) => {
                const on = active !== null && touches(link, active);
                return (
                  <g
                    key={link.key}
                    className={cn(
                      "transition-opacity motion-reduce:transition-none",
                      on ? "text-foreground" : "text-atelier-faint",
                      active !== null && !on && "opacity-25",
                    )}
                  >
                    <path d={link.path} fill="none" strokeWidth={on ? 1.5 : 1.25} strokeLinecap="round" className="stroke-current" />
                    {link.heads.map((d) => (
                      <path key={d} d={d} className="fill-current" />
                    ))}
                    {link.label && (
                      <text
                        x={link.label.x}
                        y={link.label.y}
                        textAnchor={link.label.anchor}
                        className={cn("text-[12px]", on ? "fill-foreground" : "fill-muted-foreground")}
                      >
                        {link.label.text}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
            {layout.nodes.map((node) => {
              const theme = appTheme(node.id, map.apps.find((a) => a.app === node.id)?.color);
              const pressed = chosen === node.id;
              const gradient = `${titleId}-${node.id}`;
              return (
                <g
                  key={node.id}
                  {...theme}
                  role="button"
                  tabIndex={0}
                  aria-pressed={pressed}
                  aria-label={`${appName(map, node.id)} : ${plural(count(node.id), "échange", "échanges")}`}
                  className={cn(
                    "cursor-pointer outline-none transition-opacity motion-reduce:transition-none [&:focus-visible_.tile-ring]:stroke-primary [&:hover_.tile-ring]:stroke-atelier-faint",
                    active !== null && node.id !== active && !near.has(node.id) && "opacity-40",
                  )}
                  onClick={() => setSelected(pressed ? null : node.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelected(pressed ? null : node.id);
                    } else if (e.key === "Escape" && chosen) setSelected(null);
                  }}
                  onMouseEnter={() => setHovered(node.id)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(node.id)}
                  onBlur={() => setHovered(null)}
                >
                  {/* Icône de l'app (charte v2) : carré arrondi en dégradé de SA signature, glyphe blanc */}
                  <defs>
                    <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0" style={{ stopColor: "color-mix(in oklab, var(--atelier-signature) 78%, white)" }} />
                      <stop offset="1" style={{ stopColor: "var(--atelier-signature)" }} />
                    </linearGradient>
                  </defs>
                  {/* Zone de clic : l'icône et son nom */}
                  <rect x={node.x - 24} y={node.y - 24} width={48} height={64} fill="transparent" />
                  <rect
                    x={node.x - 23}
                    y={node.y - 23}
                    width={46}
                    height={46}
                    rx={12.5}
                    strokeWidth={2}
                    className={cn("tile-ring fill-none", pressed ? "stroke-primary" : "stroke-transparent")}
                  />
                  <rect x={node.x - 20} y={node.y - 20} width={40} height={40} rx={10} fill={`url(#${gradient})`} />
                  <AppIcon app={node.id} x={node.x - 11} y={node.y - 11} width={22} height={22} strokeWidth={2} className="text-white" aria-hidden />
                  <text x={node.label.x} y={node.label.y} textAnchor={node.label.anchor} className="fill-foreground text-[12px] font-medium">
                    {node.name}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
        <figcaption className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-2 border-t border-atelier-line px-1.5 pt-2 pb-1 text-xs text-muted-foreground">
          <p>
            Pointe vers Nexus : lecture. Pointe vers une application : écritures validées. Entre deux applications, le lien porte ce
            qui passe.
          </p>
          <div aria-live="polite" className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
            {chosen ? (
              <>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                  <p className="mr-auto text-sm text-foreground">
                    <span className="font-medium">{appName(map, chosen)}</span>{" "}
                    <span className="text-muted-foreground">· {plural(count(chosen), "échange", "échanges")}</span>
                  </p>
                  {known.has(chosen) && (
                    <Button size="sm" variant="outline" onClick={() => onPick(chosen)}>
                      <LayoutGrid />
                      Voir la fiche
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
                    <X />
                    Tout afficher
                  </Button>
                </div>
                <ExchangeLines map={map} flows={flows} app={chosen} />
              </>
            ) : (
              <p>Choisissez une application pour voir ses échanges et ouvrir sa fiche.</p>
            )}
          </div>
        </figcaption>
      </figure>
      {/* La même carte en texte : tous les échanges, ceux de l'application choisie mis en avant */}
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full text-sm">
          {/* Le schéma renvoie à ce titre (aria-describedby), pas aux 20 lignes */}
          <caption id={listId} className="mb-2 text-left text-xs text-muted-foreground">
            Liste des échanges entre les applications ({flows.length})
          </caption>
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th scope="col" className="border-b border-atelier-line py-1.5 pr-2 font-medium">De</th>
              <th scope="col" className="border-b border-atelier-line py-1.5 pr-2 font-medium">Vers</th>
              <th scope="col" className="border-b border-atelier-line py-1.5 pr-2 font-medium">Quoi</th>
              <th scope="col" className="border-b border-atelier-line py-1.5 font-medium">Par</th>
            </tr>
          </thead>
          <tbody>
            {flows.map((f, i) => (
              <tr key={i} className={cn("transition-opacity motion-reduce:transition-none", active !== null && f.from !== active && f.to !== active && "opacity-40")}>
                <td className="border-b border-atelier-line py-1.5 pr-2 align-top">{appName(map, f.from)}</td>
                <td className="border-b border-atelier-line py-1.5 pr-2 align-top">{appName(map, f.to)}</td>
                <td className="border-b border-atelier-line py-1.5 pr-2 align-top">{f.label}</td>
                <td className="border-b border-atelier-line py-1.5 align-top text-muted-foreground">{f.via}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
