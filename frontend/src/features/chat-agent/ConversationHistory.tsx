"use client";

import { Check, History, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/useChatStore";
import type { AgentInfo, ConversationSummary, SearchHit } from "@/types/api";

import { formatWhen } from "./formatWhen";
import { highlight, searchTerms } from "./highlight";

/** Bouton « Historique » : conversations enregistrées de l'agent et recherche dans tout l'historique. */
export function ConversationHistory({
  agent,
  label,
  agents,
}: {
  agent: string;
  label: string;
  agents: AgentInfo[];
}) {
  const [open, setOpen] = useState(false);
  const streaming = useChatStore((s) => s.streaming);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" disabled={streaming} aria-label="Historique des conversations">
          <History />
          <span className="hidden sm:inline">Historique</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-xl grid-cols-[minmax(0,1fr)]">
        <DialogHeader>
          <DialogTitle>Conversations avec {label}</DialogTitle>
          <DialogDescription>
            Reprenez une conversation, ou retrouvez un échange ou un livrable passé.
          </DialogDescription>
        </DialogHeader>
        {/* Monté à chaque ouverture : la liste est relue à jour */}
        {open && <HistoryList agent={agent} label={label} agents={agents} onDone={() => setOpen(false)} />}
      </DialogContent>
    </Dialog>
  );
}

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: ConversationSummary[] };

type SearchState = { key: string } & (
  { status: "loading" } | { status: "error"; message: string } | { status: "ready"; hits: SearchHit[] }
);

function HistoryList({
  agent,
  label,
  agents,
  onDone,
}: {
  agent: string;
  label: string;
  agents: AgentInfo[];
  onDone: () => void;
}) {
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [everywhere, setEverywhere] = useState(false);
  const [search, setSearch] = useState<SearchState>({
    key: "",
    status: "loading",
  });
  const searching = searchTerms(query).length > 0;
  const version = useChatStore((s) => s.historyVersion);
  const currentId = useChatStore((s) => s.conversationIds[agent] ?? null);
  const openConversation = useChatStore((s) => s.open);
  const reset = useChatStore((s) => s.reset);

  useEffect(() => {
    const controller = new AbortController();
    api
      .conversations(agent, controller.signal)
      .then((items) => setState({ status: "ready", items }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const message = err instanceof ApiError ? err.message : "Le serveur ne répond pas.";
        setState({ status: "error", message });
      });
    return () => controller.abort();
  }, [agent, version]);

  // Recherche : relancée 250 ms après la dernière frappe ; les résultats précédents restent
  // affichés (atténués) en attendant
  const key = searching ? JSON.stringify([query.trim(), everywhere, version]) : "";
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api
        .searchConversations(query.trim(), everywhere ? null : agent, controller.signal)
        .then((hits) => setSearch({ key, status: "ready", hits }))
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          const message = err instanceof ApiError ? err.message : "Le serveur ne répond pas.";
          setSearch({ key, status: "error", message });
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [key, query, everywhere, agent]);
  const shown: SearchState =
    search.key === key || search.status === "ready" ? search : { key, status: "loading" };
  const stale = shown.key !== key;

  const agentLabel = (name: string) => agents.find((a) => a.name === name)?.display_name ?? name;
  const choose = (id: string) => {
    void openConversation(id);
    onDone();
  };

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            type="search"
            value={query}
            maxLength={200}
            className="pl-8"
            placeholder="Rechercher : mot, livrable, nom…"
            aria-label="Rechercher dans les conversations"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape" && query) {
                e.stopPropagation(); // vider la recherche sans fermer la fenêtre
                e.preventDefault();
                setQuery("");
              }
            }}
          />
        </div>
        <Button
          variant="outline"
          onClick={() => {
            reset();
            onDone();
          }}
        >
          <Plus />
          Nouvelle conversation
        </Button>
      </div>

      {searching ? (
        <SearchResults
          state={shown}
          stale={stale}
          query={query}
          everywhere={everywhere}
          label={label}
          currentAgent={agent}
          currentId={currentId}
          agentLabel={agentLabel}
          onScope={setEverywhere}
          onOpen={choose}
        />
      ) : (
        <>
          {state.status === "loading" && <p className="text-sm text-muted-foreground">Chargement…</p>}
          {state.status === "error" && (
            <p role="alert" className="text-sm text-destructive">
              Historique indisponible : {state.message}
            </p>
          )}
          {state.status === "ready" && state.items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Aucune conversation enregistrée avec cet agent. Elle apparaîtra ici dès votre premier message.
            </p>
          )}
          {state.status === "ready" && state.items.length > 0 && (
            <ul className="-mx-2 flex flex-col">
              {state.items.map((item) => (
                <HistoryRow
                  key={item.id}
                  item={item}
                  current={item.id === currentId}
                  onOpen={() => choose(item.id)}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function SearchResults({
  state,
  stale,
  query,
  everywhere,
  label,
  currentAgent,
  currentId,
  agentLabel,
  onScope,
  onOpen,
}: {
  state: SearchState;
  /** Résultats d'une frappe précédente, nouvelle recherche en cours */
  stale: boolean;
  query: string;
  everywhere: boolean;
  label: string;
  currentAgent: string;
  currentId: string | null;
  agentLabel: (name: string) => string;
  onScope: (everywhere: boolean) => void;
  onOpen: (id: string) => void;
}) {
  return (
    <div className="flex min-h-0 flex-col gap-2">
      <div role="group" aria-label="Où chercher" className="flex items-center gap-1 text-sm">
        <Button
          size="sm"
          variant={everywhere ? "ghost" : "secondary"}
          aria-pressed={!everywhere}
          onClick={() => onScope(false)}
        >
          Avec {label}
        </Button>
        <Button
          size="sm"
          variant={everywhere ? "secondary" : "ghost"}
          aria-pressed={everywhere}
          onClick={() => onScope(true)}
        >
          Tous les agents
        </Button>
      </div>

      {state.status === "loading" && <p className="text-sm text-muted-foreground">Recherche…</p>}
      {state.status === "error" && (
        <p role="alert" className="text-sm text-destructive">
          Recherche impossible : {state.message}
        </p>
      )}
      {state.status === "ready" && state.hits.length === 0 && (
        <div className="flex flex-col items-start gap-2 text-sm text-muted-foreground">
          <p>
            Aucune conversation {everywhere ? "" : `avec ${label} `}ne contient tous ces mots. Les accents et
            les majuscules ne comptent pas.
          </p>
          {!everywhere && (
            <Button size="sm" variant="outline" onClick={() => onScope(true)}>
              Chercher chez tous les agents
            </Button>
          )}
        </div>
      )}
      {state.status === "ready" && state.hits.length > 0 && (
        <>
          <p role="status" className="text-xs text-muted-foreground">
            {state.hits.length} conversation{state.hits.length > 1 ? "s" : ""}
            {state.hits.length >= 30 ? " (les plus récentes)" : ""}
          </p>
          <ul
            aria-busy={stale}
            className={cn("-mx-2 flex flex-col transition-opacity", stale && "opacity-60")}
          >
            {state.hits.map((hit) => (
              <li key={hit.id}>
                <button
                  type="button"
                  onClick={() => onOpen(hit.id)}
                  className={cn(
                    "flex w-full min-w-0 flex-col items-start gap-1 rounded-md px-2 py-2 text-left outline-none hover:bg-accent/60 focus-visible:ring-[3px] focus-visible:ring-ring",
                    hit.id === currentId && "bg-accent",
                  )}
                >
                  <span className="w-full truncate text-sm font-medium">
                    <Highlighted text={hit.title} query={query} />
                  </span>
                  {hit.snippet && hit.snippet !== hit.title && (
                    <span className="line-clamp-2 text-sm text-muted-foreground">
                      <Highlighted text={hit.snippet} query={query} />
                    </span>
                  )}
                  <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {hit.agent !== currentAgent && <Badge variant="outline">{agentLabel(hit.agent)}</Badge>}
                    <time dateTime={hit.updated_at}>{formatWhen(hit.updated_at)}</time>
                    {hit.artifact_count > 0 && (
                      <span>
                        {hit.artifact_count} artefact
                        {hit.artifact_count > 1 ? "s" : ""}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Highlighted({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlight(text, query).map((seg, i) =>
        seg.match ? (
          <mark key={i} className="rounded-sm bg-primary/15 px-0.5 text-foreground">
            {seg.text}
          </mark>
        ) : (
          <Fragment key={i}>{seg.text}</Fragment>
        ),
      )}
    </>
  );
}

function HistoryRow({
  item,
  current,
  onOpen,
}: {
  item: ConversationSummary;
  current: boolean;
  onOpen: () => void;
}) {
  const [mode, setMode] = useState<"view" | "rename" | "confirm">("view");
  const [title, setTitle] = useState(item.title);
  const rename = useChatStore((s) => s.rename);
  const remove = useChatStore((s) => s.remove);

  const saveTitle = () => {
    if (title.trim() && title.trim() !== item.title) void rename(item.id, title);
    setMode("view");
  };

  if (mode === "rename") {
    return (
      <li className="flex items-center gap-2 px-2 py-1.5">
        <Input
          autoFocus
          value={title}
          maxLength={120}
          aria-label="Nouveau titre"
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") saveTitle();
            if (e.key === "Escape") {
              e.stopPropagation(); // ne pas fermer la fenêtre
              setTitle(item.title);
              setMode("view");
            }
          }}
        />
        <Button size="icon-sm" variant="ghost" onClick={saveTitle} aria-label="Enregistrer le titre">
          <Check />
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={() => {
            setTitle(item.title);
            setMode("view");
          }}
          aria-label="Annuler"
        >
          <X />
        </Button>
      </li>
    );
  }

  if (mode === "confirm") {
    return (
      <li className="flex flex-wrap items-center gap-2 rounded-md bg-destructive/5 px-2 py-2">
        <p className="min-w-0 flex-1 text-sm">
          Supprimer « {item.title} » et ses {item.artifact_count} artefact(s) ?
        </p>
        <Button size="sm" variant="destructive" onClick={() => void remove(item.id)}>
          Supprimer
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setMode("view")}>
          Annuler
        </Button>
      </li>
    );
  }

  return (
    <li className={cn("group flex items-center gap-1 rounded-md px-2", current && "bg-accent")}>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-sm py-2 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
      >
        <span className="w-full truncate text-sm font-medium">{item.title}</span>
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          <time dateTime={item.updated_at}>{formatWhen(item.updated_at)}</time>
          {item.artifact_count > 0 && (
            <span>
              {item.artifact_count} artefact{item.artifact_count > 1 ? "s" : ""}
            </span>
          )}
          {current && <Badge variant="secondary">Ouverte</Badge>}
        </span>
      </button>
      <Button
        size="icon-sm"
        variant="ghost"
        onClick={() => setMode("rename")}
        aria-label={`Renommer « ${item.title} »`}
      >
        <Pencil />
      </Button>
      <Button
        size="icon-sm"
        variant="ghost"
        className="text-muted-foreground hover:text-destructive"
        onClick={() => setMode("confirm")}
        aria-label={`Supprimer « ${item.title} »`}
      >
        <Trash2 />
      </Button>
    </li>
  );
}
