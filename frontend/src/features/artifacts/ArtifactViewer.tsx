"use client";

import { Check, ChevronDown, Copy, Download, Ellipsis, Plug, Trash2, WrapText } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Markdown } from "@/features/chat-agent/Markdown";
import { saveFile } from "@/lib/desktop";
import { cn } from "@/lib/utils";
import type { StoredArtifact } from "@/stores/useArtifactStore";

import { downloadName, exportPayload, notesTitle, rowCount, showsAsCode } from "./panel";
import { type TableData, formatCell, parsePreview } from "./preview";

/** Retour visuel bref d'une action (Copier, Télécharger), puis retour au libellé. */
type Feedback = { action: "copy" | "save"; label: string } | null;

/**
 * Corps du panneau Livrables : actions (Copier, Télécharger, menu ⋯ avec retrait confirmé),
 * notes d'intégration repliables, puis le contenu (code, document, tableau de données).
 * `onRemove` : retrait décidé par le panneau, qui choisit le livrable montré ensuite.
 */
export function ArtifactViewer({ artifact, onRemove }: { artifact: StoredArtifact; onRemove: () => void }) {
  const preview = useMemo(
    () => (artifact.kind === "data_preview" ? parsePreview(artifact.content) : null),
    [artifact],
  );
  const notes = typeof artifact.metadata.notes === "string" && artifact.metadata.notes.trim() ? artifact.metadata.notes : null;
  // CSV d'un gros aperçu : calculé une fois par livrable, pas à chaque retour d'action
  const payload = useMemo(() => exportPayload(artifact.content, preview), [artifact.content, preview]);
  const code = showsAsCode(artifact.kind, preview);

  const [wrap, setWrap] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  // Le menu ⋯ rend le focus à son bouton en se fermant : sauf s'il ouvre la confirmation
  const focusConfirm = useRef(false);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const flash = (next: Feedback) => {
    if (timer.current) clearTimeout(timer.current);
    setFeedback(next);
    timer.current = setTimeout(() => setFeedback(null), 1800);
  };

  const copy = async () => {
    setError(null);
    try {
      await navigator.clipboard.writeText(payload.text);
      flash({ action: "copy", label: "Copié" });
    } catch {
      setError("Copie impossible : le presse-papiers n'est pas accessible.");
    }
  };

  const download = async () => {
    setError(null);
    try {
      const outcome = await saveFile(downloadName(artifact.title, artifact.kind), payload.text, payload.type);
      if (outcome.kind === "saved") flash({ action: "save", label: "Enregistré" });
      else if (outcome.kind === "downloaded") flash({ action: "save", label: "Téléchargé" });
    } catch (err) {
      setError(`Enregistrement impossible${err instanceof Error && err.message ? ` : ${err.message}` : "."}`);
    }
  };

  const copied = feedback?.action === "copy" ? feedback.label : null;
  const saved = feedback?.action === "save" ? feedback.label : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-atelier-line px-3 py-1.5">
        {code && (
          <Button
            variant="ghost"
            size="sm"
            aria-pressed={wrap}
            onClick={() => setWrap((w) => !w)}
            className={cn("h-7 px-2 text-xs", wrap && "bg-signature-faint text-accent-ink")}
          >
            <WrapText className="size-3.5" />
            <span className="sr-only sm:not-sr-only">Retour à la ligne</span>
          </Button>
        )}
        <div className="ml-auto flex items-center gap-0.5">
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => void copy()}>
            {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
            <span className="sr-only sm:not-sr-only">{copied ?? "Copier"}</span>
          </Button>
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => void download()}>
            {saved ? <Check className="size-3.5 text-success" /> : <Download className="size-3.5" />}
            <span className="sr-only sm:not-sr-only">{saved ?? "Télécharger"}</span>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button ref={menuTrigger} variant="ghost" size="icon-xs" aria-label="Plus d'actions">
                <Ellipsis />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              onCloseAutoFocus={(e) => {
                if (!focusConfirm.current) return;
                focusConfirm.current = false;
                e.preventDefault();
                cancelButton.current?.focus();
              }}
            >
              <DropdownMenuItem
                className="text-destructive-ink focus:bg-destructive/10 [&_svg]:text-destructive"
                onSelect={() => {
                  focusConfirm.current = true;
                  setConfirming(true);
                }}
              >
                <Trash2 />
                Retirer du panneau…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {/* Annonce des retours d'action aux lecteurs d'écran */}
        <span role="status" className="sr-only">
          {feedback ? (feedback.action === "copy" ? "Copié dans le presse-papiers" : `Fichier ${feedback.label.toLowerCase()}`) : ""}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4 p-4">
          {confirming && (
            // Groupe nommé : le focus arrive sur « Annuler », la question est annoncée avec lui
            <Callout
              tone="destructive"
              icon={Trash2}
              title="Retirer ce livrable du panneau ?"
              role="group"
              aria-label="Retirer ce livrable du panneau ?"
            >
              <p>La conversation ou l&apos;exécution enregistrée, s&apos;il y en a une, le conserve.</p>
              <div className="mt-2.5 flex flex-wrap gap-2">
                <Button size="sm" variant="destructive" onClick={onRemove}>
                  Retirer
                </Button>
                <Button
                  ref={cancelButton}
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setConfirming(false);
                    menuTrigger.current?.focus();
                  }}
                >
                  Annuler
                </Button>
              </div>
            </Callout>
          )}
          {error && (
            <Callout tone="destructive" role="alert">
              {error}
            </Callout>
          )}
          {notes && <NotesCallout title={notesTitle(artifact.kind, notes)} notes={notes} />}

          {preview?.view === "table" && <DataTable table={preview.table} />}
          {preview?.view === "schema" && (
            <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
              <DataTable
                caption="Colonnes"
                table={{
                  headers: ["Colonne", "Type", "Distinctes", "Vides"],
                  numeric: [false, false, true, true],
                  rows: preview.schema.columns.map((c) => [c.name, c.type, c.distinct, c.nulls]),
                }}
              />
              {preview.schema.measures.length > 0 && (
                <DataTable
                  caption="Mesures calculées"
                  table={{
                    headers: ["Mesure", "Expression"],
                    numeric: [false, false],
                    rows: preview.schema.measures.map((m) => [m.name, m.expression]),
                  }}
                />
              )}
              {preview.schema.sample && <DataTable caption="Échantillon" table={preview.schema.sample} />}
            </div>
          )}
          {!preview && artifact.kind === "markdown" && <Markdown>{artifact.content}</Markdown>}
          {code && <CodeBlock code={artifact.content} wrap={wrap} />}
        </div>
      </div>
    </div>
  );
}

/** Notes d'intégration (`metadata.notes`, ex. étapes dans Power BI Desktop), repliées par défaut. */
function NotesCallout({ title, notes }: { title: string; notes: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <Callout
      tone="signature"
      icon={Plug}
      title={
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 rounded-sm text-left font-semibold focus-visible:shadow-focus focus-visible:outline-none"
        >
          {title}
          <ChevronDown className={cn("ml-auto size-4 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
        </button>
      }
    >
      <div id={id} hidden={!open} className="pt-1">
        <Markdown className="text-sm">{notes}</Markdown>
      </div>
    </Callout>
  );
}

function CodeBlock({ code, wrap }: { code: string; wrap: boolean }) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <pre className="overflow-x-auto rounded-lg border border-atelier-line bg-sunken py-3 font-mono text-[0.8125rem] leading-relaxed">
      {/* Sans retour à la ligne, la colonne prend la largeur de la plus longue ligne (défilement horizontal) */}
      <code className={cn("grid", wrap ? "grid-cols-[auto_minmax(0,1fr)]" : "grid-cols-[auto_1fr]")}>
        {lines.map((line, i) => (
          <span key={i} className="contents">
            <span className="px-3 text-right text-muted-foreground tabular-nums select-none" aria-hidden>
              {i + 1}
            </span>
            <span className={cn("pr-4", wrap ? "break-words whitespace-pre-wrap" : "whitespace-pre")}>{line || " "}</span>
          </span>
        ))}
      </code>
    </pre>
  );
}

/**
 * Tableau d'aperçu : en-tête collant, lignes zébrées, défilement interne au-delà de 60 % de la hauteur.
 * La zone qui défile prend le focus (tabIndex 0) : au clavier, WKWebView (app de bureau) ne la
 * ferait pas défiler sinon.
 */
function DataTable({ table, caption }: { table: TableData; caption?: string }) {
  const captionId = useId();
  return (
    <section className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
      {caption && (
        <h3 id={captionId} className="text-xs font-semibold text-muted-foreground">
          {caption}
        </h3>
      )}
      <div
        role="region"
        tabIndex={0}
        aria-labelledby={caption ? captionId : undefined}
        aria-label={caption ? undefined : "Aperçu des données"}
        className="max-h-[60vh] overflow-auto rounded-lg border border-atelier-line bg-card focus-visible:shadow-focus focus-visible:outline-none"
      >
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-atelier-surface-2">
            <tr>
              {table.headers.map((h, i) => (
                <th
                  key={`${h}-${i}`}
                  scope="col"
                  className={cn(
                    // Trait sous l'en-tête en ombre : il reste visible quand l'en-tête colle
                    "px-2.5 py-1.5 text-xs font-semibold whitespace-nowrap shadow-[inset_0_-1px_0_var(--atelier-line)]",
                    table.numeric[i] ? "text-right" : "text-left",
                  )}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.length === 0 && (
              <tr>
                <td colSpan={Math.max(table.headers.length, 1)} className="px-2.5 py-3 text-center text-muted-foreground">
                  Aucune ligne
                </td>
              </tr>
            )}
            {table.rows.map((row, r) => (
              <tr key={r} className="even:bg-signature-faint">
                {row.map((cell, c) => (
                  <td
                    key={c}
                    className={cn(
                      "px-2.5 py-1.5 whitespace-nowrap",
                      table.numeric[c] && "text-right tabular-nums",
                      cell === null && "text-muted-foreground",
                    )}
                  >
                    {formatCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">{rowCount(table.rows.length)}</p>
    </section>
  );
}
