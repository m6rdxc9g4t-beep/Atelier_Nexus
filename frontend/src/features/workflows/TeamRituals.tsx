"use client";

import { CalendarClock, Check, Loader2, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { TeamRitual } from "@/types/api";

/**
 * Rituels de l'équipe (docs/equipe.md) : workflows sans modèle lancés à heure fixe, installés en
 * un clic. Chaque étape attend ensuite « Autoriser » dans la boîte « À valider ».
 */
export function TeamRituals({ version }: { version: number }) {
  const [items, setItems] = useState<TeamRitual[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const bump = useWorkflowStudioStore((s) => s.bump);
  const openEditor = useWorkflowStudioStore((s) => s.openEditor);

  useEffect(() => {
    const controller = new AbortController();
    api
      .teamRituals(controller.signal)
      .then((list) => {
        setItems(list);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        // Backend antérieur aux rituels (404) : la section ne s'affiche pas ; sinon on le dit
        if (err instanceof ApiError && err.status === 404) setItems([]);
        else setLoadError(err instanceof ApiError ? err.message : "Rituels indisponibles pour l'instant.");
      });
    return () => controller.abort();
  }, [version, refresh]);

  if (loadError && !items) {
    return (
      <p role="status" className="rounded-md border border-atelier-border-soft p-3 text-xs text-muted-foreground">
        Rituels de l&apos;équipe : {loadError}
      </p>
    );
  }
  if (!items || items.length === 0) return null;

  const install = async (id: string) => {
    setError(null);
    setBusy(id);
    try {
      await api.installTeamRitual(id);
      setRefresh((r) => r + 1);
      bump();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Installation impossible.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="team-rituals" className="rounded-md border border-atelier-border-soft bg-signature-faint p-3">
      <h3 id="team-rituals" className="flex items-center gap-1.5 text-sm font-medium">
        <CalendarClock className="size-4 text-accent-ink" aria-hidden />
        Rituels de l&apos;équipe
      </h3>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Lancés tout seuls à heure fixe, sans modèle ; chaque étape attend votre validation dans « À valider ».
      </p>
      {error && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {error}
        </p>
      )}
      <ul className="mt-2 grid grid-cols-[minmax(0,1fr)] gap-2">
        {items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-start gap-2 rounded-md bg-card p-2">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="font-medium">{r.title}</span>
                <Badge variant="outline">{r.when}</Badge>
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">{r.description}</p>
              {r.missing.length > 0 && !r.workflow_id && (
                <p className="mt-0.5 text-xs text-warning">À configurer d&apos;abord : {r.missing.join(", ")}.</p>
              )}
            </div>
            {r.workflow_id ? (
              <Button size="sm" variant="ghost" onClick={() => openEditor({ kind: "open", id: r.workflow_id! })}>
                <Check className="text-success" />
                Installé
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null || r.missing.length > 0}
                aria-label={`Installer le rituel ${r.title}`}
                onClick={() => void install(r.id)}
              >
                {busy === r.id ? <Loader2 className="animate-spin" /> : <Plus />}
                Installer
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
