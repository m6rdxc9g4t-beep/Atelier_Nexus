"use client";

import { BookOpen, ExternalLink, RefreshCw, Trash2, Waypoints } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/select";
import { ApiError, api } from "@/lib/api";
import { suiteApps } from "@/lib/suite";
import { cn } from "@/lib/utils";
import { useWorkflowStudioStore } from "@/stores/useWorkflowStudioStore";
import type { ExampleLoaded, ExampleStory } from "@/types/api";

import { APP_LABELS, THIS_APP, pickStory, readRemembered, remember, stepsAround } from "./examples";

type Result = { tone: "success" | "warning" | "destructive"; title: string; lines: string[] };

const message = (err: unknown) => (err instanceof ApiError ? err.message : "Le serveur ne répond pas.");

function loadedResult(r: ExampleLoaded): Result {
  const lines = [
    ...r.workflows.map((w) => `Workflow « ${w.title} »`),
    ...(r.trigger_id ? ["Déclencheur sur l'alerte Viz de l'histoire"] : []),
    ...(r.tab ? ["Projet de l'histoire chargé dans les fichiers de Tab (serveur MCP)"] : []),
    ...r.notes,
  ];
  return {
    tone: r.notes.length > 0 ? "warning" : "success",
    title:
      r.workflows.length > 0
        ? `${r.workflows.length} workflow${r.workflows.length > 1 ? "s" : ""} prêt${r.workflows.length > 1 ? "s" : ""} : rien n'est lancé, chaque écriture attendra « Autoriser »`
        : "Aucun workflow créé",
    lines,
  };
}

/**
 * « Exemples de la suite » : une histoire fictive suivie d'une application à l'autre (Convert → Tab
 * → Viz → Trésorerie → Nexus → Projets → Wiki). Ici, ses workflows : copiés de la bibliothèque,
 * paramètres résolus dans Viz et Projets, déclencheur sur l'alerte Viz de l'histoire.
 */
export function SuiteExamples() {
  const [stories, setStories] = useState<ExampleStory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [version, setVersion] = useState(0);
  const setListSection = useWorkflowStudioStore((s) => s.setListSection);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .suiteExamples(ctrl.signal)
      .then((r) => {
        setStories(r.histoires);
        setSelected((current) => current ?? readRemembered());
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        // Serveur plus ancien, sans exemples : le panneau ne s'affiche pas
        if (err instanceof ApiError && err.status === 404) setStories([]);
        else setError(message(err));
      });
    return () => ctrl.abort();
  }, [version]);

  if (error) {
    return (
      <Callout tone="warning" title="Exemples de la suite indisponibles">
        {error}
      </Callout>
    );
  }
  if (!stories || stories.length === 0) return null;
  const story = pickStory(stories, selected);
  if (!story) return null;
  const { current, next } = stepsAround(story, THIS_APP);
  const nextApp = next ? suiteApps().find((a) => a.id === next.app) : undefined;
  const loaded = story.workflows.length > 0;

  const choose = (id: string) => {
    setSelected(id);
    setResult(null);
    remember(id);
  };

  const load = async () => {
    setBusy(true);
    setResult(null);
    try {
      setResult(loadedResult(await api.loadSuiteExample(story.id)));
    } catch (err) {
      setResult({ tone: "destructive", title: "Chargement impossible", lines: [message(err)] });
    } finally {
      setBusy(false);
      setVersion((v) => v + 1);
    }
  };

  const unload = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api.removeSuiteExample(story.id);
      setResult({ tone: "success", title: `Exemple retiré (${r.retires} workflow${r.retires > 1 ? "s" : ""})`, lines: [] });
    } catch (err) {
      setResult({ tone: "destructive", title: "Retrait impossible", lines: [message(err)] });
    } finally {
      setBusy(false);
      setVersion((v) => v + 1);
    }
  };

  return (
    <Card role="region" className="gap-3 p-4" aria-labelledby="exemples-suite-titre">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        {/* Base de 16rem : sur un écran étroit, le choix de l'histoire passe dessous au lieu d'écraser le texte */}
        <div className="min-w-0 flex-[1_1_16rem]">
          <h2 id="exemples-suite-titre" className="flex items-center gap-1.5 text-sm font-semibold">
            <BookOpen className="size-4 text-atelier-faint" aria-hidden />
            Exemples de la suite
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Des histoires fictives qui traversent toute la suite, avec les mêmes chiffres partout. Ici, leurs workflows.
          </p>
        </div>
        <label className="grid gap-1 text-xs text-muted-foreground">
          Histoire
          <NativeSelect className="w-72 max-w-full" value={story.id} onChange={(e) => choose(e.target.value)}>
            {stories.map((s) => (
              <option key={s.id} value={s.id}>
                {s.secteur} · {s.titre}
              </option>
            ))}
          </NativeSelect>
        </label>
      </div>

      <div>
        <p className="text-sm font-medium">
          {story.titre} <span className="font-normal text-muted-foreground">— {story.sous_titre}</span>
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{story.resume}</p>
      </div>

      <ol className="flex flex-wrap gap-1.5" aria-label="Parcours de l'histoire dans la suite">
        {story.parcours.map((step, i) => (
          <li
            key={step.app}
            title={step.texte}
            aria-current={step.app === THIS_APP ? "step" : undefined}
            className={cn(
              "inline-flex h-6 items-center gap-1.5 rounded-md border px-2 text-xs",
              step.app === THIS_APP
                ? "border-primary bg-atelier-selected text-foreground"
                : "border-atelier-line text-muted-foreground",
            )}
          >
            <span className="text-atelier-faint tabular-nums">{i + 1}</span>
            {APP_LABELS[step.app] ?? step.app}
          </li>
        ))}
      </ol>

      {current && <p className="text-sm">{current.texte}</p>}
      {loaded && (
        <p className="text-xs text-muted-foreground">
          Déjà chargé : {story.workflows.map((w) => `« ${w.title} »`).join(", ")}. Recharger les recrée (vos
          workflows ne sont pas touchés).
        </p>
      )}

      {result && (
        <Callout tone={result.tone} title={result.title} className="text-xs">
          {result.lines.length > 0 && (
            <ul className="grid gap-0.5">
              {result.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </Callout>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={busy} onClick={() => void load()}>
          {loaded ? <RefreshCw aria-hidden /> : <BookOpen aria-hidden />}
          {loaded ? "Recharger l'exemple" : "Charger l'exemple"}
        </Button>
        {loaded && (
          <>
            <Button size="sm" variant="soft" onClick={() => setListSection("mine")}>
              <Waypoints aria-hidden />
              Voir mes workflows
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void unload()}>
              <Trash2 aria-hidden />
              Retirer
            </Button>
          </>
        )}
      </div>

      {next && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-atelier-line pt-3 text-sm text-muted-foreground">
          <p className="min-w-0">
            <span className="font-medium text-foreground">Ensuite, {APP_LABELS[next.app] ?? next.app}</span> —{" "}
            {next.texte}
          </p>
          {nextApp && (
            <Button size="sm" variant="ghost" asChild>
              <a href={nextApp.url} target="_blank" rel="noreferrer">
                Ouvrir {nextApp.name}
                <ExternalLink aria-hidden />
              </a>
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
