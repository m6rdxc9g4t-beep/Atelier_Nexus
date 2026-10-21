"use client";

import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Bell,
  Bot,
  Map as MapIcon,
  Plus,
  RefreshCw,
  Rss,
  TriangleAlert,
  Waypoints,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AgentIcon } from "@/features/chat-agent/agentMeta";
import { formatWhen } from "@/features/chat-agent/formatWhen";
import { toolLabel } from "@/features/chat-agent/ToolCall";
import { appTheme } from "@/features/workflows-graph/catalog";
import { AppStatusDot, AppTile, KindBadge } from "@/features/workflows-graph/StepBadges";
import { ApiError, api } from "@/lib/api";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { SuiteEventsEntry, SuiteMap, SuiteMapAction, SuiteMapApp } from "@/types/api";

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

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Bouton de l'en-tête (à côté du menu des apps) : ouvre la carte de la suite. */
export function SuiteMapButton() {
  const setOpen = useWorkflowStudioStore((s) => s.setMapOpen);
  return (
    <Button variant="ghost" size="sm" className="hidden sm:inline-flex" aria-label="Carte de la suite" title="Carte de la suite : entrées, sorties, agents" onClick={() => setOpen(true)}>
      <MapIcon />
      <span className="hidden xl:inline">Carte</span>
    </Button>
  );
}

/**
 * Carte de la suite : pour chaque application, ce qui y entre (écritures), ce qui en sort
 * (lectures et format), ses événements, les outils Nexus et agents qui l'utilisent, les flux
 * entre apps et les workflows qui la touchent ; plus le fil des derniers événements.
 */
export function SuiteMapDialog() {
  const open = useWorkflowStudioStore((s) => s.mapOpen);
  const setOpen = useWorkflowStudioStore((s) => s.setMapOpen);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex h-[calc(100dvh-2rem)] max-w-6xl flex-col gap-3 overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <MapIcon className="size-5 text-accent-ink" aria-hidden />
            Carte de la suite
          </DialogTitle>
          <DialogDescription>
            Ce que chaque application reçoit et produit, les agents qui s&apos;en servent et les échanges entre elles.
            Partez d&apos;une action pour créer un workflow, ou d&apos;un événement pour le lancer tout seul.
          </DialogDescription>
        </DialogHeader>
        {open && <SuiteMapBody />}
      </DialogContent>
    </Dialog>
  );
}

function SuiteMapBody() {
  const [map, setMap] = useState<Loaded<SuiteMap>>({ status: "loading" });
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .suiteMap(ctrl.signal)
      .then((data) => setMap({ status: "ready", data }))
      .catch((err: unknown) => !ctrl.signal.aborted && setMap({ status: "error", message: errorText(err, "Le serveur ne répond pas.") }));
    return () => ctrl.abort();
  }, [refresh]);

  return (
    <Tabs defaultValue="apps" className="min-h-0 flex-1">
      <div className="flex min-w-0 items-center gap-2">
        <TabsList className="max-w-full overflow-x-auto">
          <TabsTrigger value="apps">
            <Waypoints />
            Applications
          </TabsTrigger>
          <TabsTrigger value="flows">
            <MapIcon />
            Flux
          </TabsTrigger>
          <TabsTrigger value="events">
            <Rss />
            Derniers événements
          </TabsTrigger>
        </TabsList>
        <Button variant="ghost" size="sm" className="ml-auto" aria-label="Actualiser la carte" onClick={() => setRefresh((r) => r + 1)}>
          <RefreshCw />
          <span className="hidden sm:inline">Actualiser</span>
        </Button>
      </div>
      {map.status === "loading" && (
        <p role="status" className="text-sm text-muted-foreground">
          Lecture des manifestes des applications…
        </p>
      )}
      {map.status === "error" && (
        <p role="alert" className="text-sm text-destructive">
          Carte indisponible : {map.message}
        </p>
      )}
      {map.status === "ready" && (
        <>
          <TabsContent value="apps" className="overflow-y-auto">
            <AppsGrid map={map.data} />
          </TabsContent>
          <TabsContent value="flows" className="overflow-y-auto">
            <FlowsView map={map.data} />
          </TabsContent>
        </>
      )}
      <TabsContent value="events" className="overflow-y-auto">
        <EventsFeed map={map.status === "ready" ? map.data : null} refresh={refresh} />
      </TabsContent>
    </Tabs>
  );
}

// ─── Applications ────────────────────────────────────────────────

function AppsGrid({ map }: { map: SuiteMap }) {
  if (map.apps.length === 0) return <p className="text-sm text-muted-foreground">Aucune application connue du hub.</p>;
  return (
    <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {map.apps.map((app) => (
        <AppCard key={app.app} app={app} map={map} />
      ))}
    </ul>
  );
}

function Section({ icon: Icon, title, count, children }: { icon: typeof Bell; title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1">
      <h4 className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
        <Icon className="size-3.5" aria-hidden />
        {title}
        {count !== undefined && <span className="font-normal tabular-nums">({count})</span>}
      </h4>
      {children}
    </section>
  );
}

function AppCard({ app, map }: { app: SuiteMapApp; map: SuiteMap }) {
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const { inputs, outputs } = splitActions(app);
  const { incoming, outgoing } = flowsOf(map.flows, app.app);
  const workflows = workflowsOf(map, app.app);
  const theme = appTheme(app.app, app.color);
  const empty = <p className="text-xs text-muted-foreground">—</p>;

  const actionLine = (action: SuiteMapAction) => (
    <li key={action.id} className="group flex items-center gap-1.5 rounded-sm px-1 py-0.5 hover:bg-accent">
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs">{action.label}</span>
        <span className="block truncate font-mono text-[10px] text-muted-foreground">
          {action.id}
          {action.kind === "read" && ` · ${action.output_format}`}
        </span>
      </span>
      {action.kind !== "read" && <KindBadge kind={action.kind} />}
      <Button
        variant="ghost"
        size="icon-sm"
        className="size-6 opacity-70 group-hover:opacity-100 focus-visible:opacity-100"
        aria-label={`Créer un workflow à partir de « ${action.label} »`}
        title="Créer un workflow à partir de cette action"
        onClick={() => openEditor({ kind: "new", agent: null, uses: actionUses(app.app, action.id) })}
      >
        <Plus className="size-3.5" />
      </Button>
    </li>
  );

  return (
    <li {...theme} className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-3 rounded-lg border border-atelier-border bg-card p-3 shadow-glow">
      <header className="flex items-start gap-2.5">
        <AppTile app={app.app} color={app.color} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold">{app.name}</h3>
          <p className="flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
            <AppStatusDot status={app.status} />
            <span>transport : {transportLabel(app.transport)}</span>
          </p>
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
        <Section icon={ArrowDownToLine} title="Entrées" count={inputs.length}>
          {inputs.length ? <ul className="grid gap-0.5">{inputs.map(actionLine)}</ul> : empty}
        </Section>
        <Section icon={ArrowUpFromLine} title="Sorties" count={outputs.length}>
          {outputs.length ? <ul className="grid gap-0.5">{outputs.map(actionLine)}</ul> : empty}
        </Section>
      </div>
      {app.status === "no_contract" && app.actions.length === 0 && (
        <p className="flex items-start gap-1.5 text-[11px] text-warning">
          <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
          Pas de manifeste atelier-node/1 : seuls les outils Nexus la relient au hub.
        </p>
      )}

      <Section icon={Bell} title="Événements" count={app.events.length}>
        {app.events.length ? (
          <ul className="grid gap-0.5">
            {app.events.map((ev) => (
              <li key={ev.type} className="group flex items-center gap-1.5 rounded-sm px-1 py-0.5 hover:bg-accent">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs">{ev.label}</span>
                  <span className="block truncate font-mono text-[10px] text-muted-foreground">{ev.type}</span>
                </span>
                <EventTriggerMenu app={app.app} type={ev.type} label={ev.label} />
              </li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </Section>

      <Section icon={Wrench} title="Outils Nexus" count={app.nexus_tools.length}>
        {app.nexus_tools.length ? (
          <ul className="flex flex-wrap gap-1">
            {app.nexus_tools.map((tool) => (
              <li key={tool.name} title={`${tool.name} · boîte ${tool.toolset}`}>
                <Badge variant={tool.kind === "write" ? "warning" : "outline"}>{toolLabel(tool.name)}</Badge>
              </li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </Section>

      <Section icon={Bot} title="Agents" count={app.agents.length}>
        {app.agents.length ? (
          <ul className="grid gap-1">
            {app.agents.map((agent) => (
              <li key={agent.name} className="flex items-center gap-1.5 text-xs">
                <AgentIcon icon={agent.icon} className="size-3.5 shrink-0 text-accent-ink" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{agent.display_name}</span>
                <span className="text-[11px] text-muted-foreground">{agent.writes ? "lit et écrit" : "lecture seule"}</span>
              </li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </Section>

      {(incoming.length > 0 || outgoing.length > 0) && (
        <Section icon={Waypoints} title="Échanges">
          <ul className="grid gap-0.5 text-xs">
            {incoming.map((f, i) => (
              <li key={`in-${i}`} className="text-muted-foreground">
                ← <span className="text-foreground">{appName(map, f.from)}</span> · {f.label} <span className="text-[11px]">({f.via})</span>
              </li>
            ))}
            {outgoing.map((f, i) => (
              <li key={`out-${i}`} className="text-muted-foreground">
                → <span className="text-foreground">{appName(map, f.to)}</span> · {f.label} <span className="text-[11px]">({f.via})</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section icon={Waypoints} title="Workflows" count={workflows.length}>
        {workflows.length ? (
          <ul className="grid gap-0.5">
            {workflows.map((wf) => (
              <li key={wf.id}>
                <button
                  type="button"
                  className="w-full truncate rounded-sm px-1 py-0.5 text-left text-xs text-accent-ink hover:bg-accent hover:underline focus-visible:shadow-focus"
                  onClick={() => openEditor({ kind: "open", id: wf.id })}
                >
                  {wf.title}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </Section>
    </li>
  );
}

/** « + » d'un événement : workflow déclenché par cet événement (nouveau, ou celui ouvert en dernier). */
function EventTriggerMenu({ app, type, label }: { app: string; type: string; label: string }) {
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);
  const last = useWorkflowStudioStore((s) => s.lastWorkflow);
  const choices = triggerChoices(app, type, last);
  if (choices.length === 0) return null;
  const button = (props: React.ComponentProps<typeof Button>) => (
    <Button
      variant="ghost"
      size="icon-sm"
      className="size-6 opacity-70 group-hover:opacity-100 focus-visible:opacity-100"
      aria-label={`Lancer un workflow quand « ${label} » arrive`}
      title="Lancer un workflow quand cet événement arrive"
      {...props}
    >
      <Plus className="size-3.5" />
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

const appName = (map: SuiteMap, id: string) => (id === "nexus" ? "Nexus" : (map.apps.find((a) => a.app === id)?.name ?? id));

// ─── Flux ────────────────────────────────────────────────────────

function FlowsView({ map }: { map: SuiteMap }) {
  const layout = layoutFlows(map);
  if (layout.edges.length === 0) return <p className="text-sm text-muted-foreground">Aucun échange déclaré entre les applications.</p>;
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,28rem)_1fr]">
      <figure className="rounded-lg border border-atelier-border-soft bg-card p-2 shadow-glow">
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          role="img"
          aria-labelledby="suite-flows-title"
          className="h-auto w-full"
        >
          <title id="suite-flows-title">Schéma des échanges entre les applications de la suite</title>
          <defs>
            <marker id="suite-flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-atelier-chart-2" />
            </marker>
          </defs>
          {layout.edges.map((edge) => (
            <g key={edge.key}>
              <path d={edge.path} fill="none" strokeWidth={1.5} markerEnd="url(#suite-flow-arrow)" className="stroke-atelier-border" />
              <text x={edge.labelX} y={edge.labelY} textAnchor="middle" className="fill-muted-foreground text-[9px]">
                {edge.label}
              </text>
            </g>
          ))}
          {layout.nodes.map((node) => {
            const theme = appTheme(node.id, map.apps.find((a) => a.app === node.id)?.color);
            return (
              <g key={node.id} {...theme}>
                <circle cx={node.x} cy={node.y} r={22} strokeWidth={2} className="fill-atelier-surface stroke-signature" />
                <text x={node.x} y={node.y + 4} textAnchor="middle" className="fill-atelier-ink text-[10px] font-semibold">
                  {appName(map, node.id).replace(/^Atelier /, "")}
                </text>
              </g>
            );
          })}
        </svg>
      </figure>
      <table className="w-full text-sm">
        <caption className="mb-2 text-left text-xs text-muted-foreground">Échanges (docs/SUITE.md §4 et écritures de Nexus)</caption>
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="border-b border-atelier-line py-1 pr-2 font-medium">De</th>
            <th className="border-b border-atelier-line py-1 pr-2 font-medium">Vers</th>
            <th className="border-b border-atelier-line py-1 pr-2 font-medium">Quoi</th>
            <th className="border-b border-atelier-line py-1 font-medium">Par</th>
          </tr>
        </thead>
        <tbody>
          {map.flows.map((f, i) => (
            <tr key={i}>
              <td className="border-b border-atelier-line py-1 pr-2">{appName(map, f.from)}</td>
              <td className="border-b border-atelier-line py-1 pr-2">{appName(map, f.to)}</td>
              <td className="border-b border-atelier-line py-1 pr-2">{f.label}</td>
              <td className="border-b border-atelier-line py-1 text-muted-foreground">{f.via}</td>
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

  if (state.status === "loading") return <p role="status" className="text-sm text-muted-foreground">Lecture des événements…</p>;
  if (state.status === "error")
    return (
      <p role="alert" className="text-sm text-destructive">
        {state.message}
      </p>
    );
  const feed = mergeEvents(state.data);
  const warnings = feedWarnings(state.data);
  return (
    <div className="grid gap-2">
      {warnings.map((w) => (
        <p key={w.app} className="flex items-center gap-1.5 text-xs text-warning">
          <TriangleAlert className="size-3.5" aria-hidden />
          {appName(map ?? { apps: [], flows: [], workflows: [] }, w.app)} : {w.text}
        </p>
      ))}
      {feed.length === 0 ? (
        <p className="text-sm text-muted-foreground">Aucun événement récent.</p>
      ) : (
        <ol className="grid gap-1" aria-live="polite">
          {feed.map((ev) => (
            <li
              key={`${ev.app}-${ev.seq}`}
              {...appTheme(ev.app, map?.apps.find((a) => a.app === ev.app)?.color)}
              className="flex items-center gap-2.5 rounded-md border border-atelier-line bg-card px-2.5 py-1.5"
            >
              <AppTile app={ev.app} size="xs" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {eventLabel(map, ev.app, ev.type)} · <span className="font-medium">{ev.subject.label || ev.subject.id}</span>
                </p>
                <p className="truncate font-mono text-[11px] text-muted-foreground">{ev.type}</p>
              </div>
              <time dateTime={ev.at} className="shrink-0 text-xs text-muted-foreground">
                {formatWhen(ev.at)}
              </time>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
