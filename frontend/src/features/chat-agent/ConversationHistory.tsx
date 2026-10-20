"use client";

import { Check, History, Pencil, Plus, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

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
import type { ConversationSummary } from "@/types/api";

import { formatWhen } from "./formatWhen";

/** Bouton « Historique » et fenêtre des conversations enregistrées de l'agent. */
export function ConversationHistory({ agent, label }: { agent: string; label: string }) {
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
          <DialogDescription>Reprenez une conversation là où vous l&apos;aviez laissée.</DialogDescription>
        </DialogHeader>
        {/* Monté à chaque ouverture : la liste est relue à jour */}
        {open && <HistoryList agent={agent} onDone={() => setOpen(false)} />}
      </DialogContent>
    </Dialog>
  );
}

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: ConversationSummary[] };

function HistoryList({ agent, onDone }: { agent: string; onDone: () => void }) {
  const [state, setState] = useState<ListState>({ status: "loading" });
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

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <Button
        variant="outline"
        className="self-start"
        onClick={() => {
          reset();
          onDone();
        }}
      >
        <Plus />
        Nouvelle conversation
      </Button>

      {state.status === "loading" && <p className="text-sm text-muted-foreground">Chargement…</p>}
      {state.status === "error" && (
        <p role="alert" className="text-sm text-destructive">
          Historique indisponible : {state.message}
        </p>
      )}
      {state.status === "ready" && state.items.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Aucune conversation enregistrée avec cet agent. Elle apparaîtra ici dès votre premier
          message.
        </p>
      )}
      {state.status === "ready" && state.items.length > 0 && (
        <ul className="-mx-2 flex flex-col">
          {state.items.map((item) => (
            <HistoryRow
              key={item.id}
              item={item}
              current={item.id === currentId}
              onOpen={() => {
                void openConversation(item.id);
                onDone();
              }}
            />
          ))}
        </ul>
      )}
    </div>
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
