"use client";

import { Check, Copy, Download, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/features/chat-agent/Markdown";
import { saveFile } from "@/lib/desktop";
import { cn } from "@/lib/utils";
import { type StoredArtifact, useArtifactStore } from "@/stores/useArtifactStore";

import { ChartView } from "./charts/ChartView";
import { chartToCsv, parseChart } from "./charts/spec";
import { type TableData, formatCell, parsePreview, toCsv } from "./preview";

export const KIND_LABELS: Record<StoredArtifact["kind"], string> = {
  sql: "SQL",
  dax: "DAX",
  powerquery: "Power Query (M)",
  python: "Python",
  react: "React",
  code: "Code",
  markdown: "Document",
  json: "JSON",
  data_preview: "Données",
  chart: "Graphique",
};

const EXTENSIONS: Record<StoredArtifact["kind"], string> = {
  sql: "sql",
  dax: "dax",
  powerquery: "pq",
  python: "py",
  react: "tsx",
  code: "txt",
  markdown: "md",
  json: "json",
  data_preview: "csv",
  chart: "csv",
};


const slug = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase() || "artefact";

export function ArtifactViewer({ artifact }: { artifact: StoredArtifact }) {
  const remove = useArtifactStore((s) => s.remove);
  const [copied, setCopied] = useState(false);
  const preview = useMemo(
    () => (artifact.kind === "data_preview" ? parsePreview(artifact.content) : null),
    [artifact],
  );
  const chart = useMemo(() => (artifact.kind === "chart" ? parseChart(artifact.content) : null), [artifact]);
  const notes = typeof artifact.metadata.notes === "string" ? artifact.metadata.notes : null;

  const exportable: { text: string; type: string } = (() => {
    if (chart) return { text: chartToCsv(chart), type: "text/csv" };
    if (preview?.view === "table") return { text: toCsv(preview.table), type: "text/csv" };
    if (preview?.view === "schema" && preview.schema.sample)
      return { text: toCsv(preview.schema.sample), type: "text/csv" };
    return { text: artifact.content, type: "text/plain" };
  })();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-start gap-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Badge>{KIND_LABELS[artifact.kind]}</Badge>
            <span className="text-xs text-muted-foreground">
              {new Date(artifact.createdAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
          <h2 className="mt-1 truncate text-sm font-semibold" title={artifact.title}>
            {artifact.title}
          </h2>
        </div>
        <div className="flex shrink-0 gap-0.5">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={copied ? "Copié" : "Copier"}
            onClick={async () => {
              await navigator.clipboard.writeText(exportable.text);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? <Check className="text-success" /> : <Copy />}
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Télécharger"
            onClick={() =>
              void saveFile(
                `${slug(artifact.title)}.${EXTENSIONS[artifact.kind]}`,
                exportable.text,
                exportable.type,
              ).catch(() => undefined)
            }
          >
            <Download />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Supprimer l'artefact" onClick={() => remove(artifact.id)}>
            <Trash2 />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {notes && (
          <div className="border-b bg-signature-faint px-4 py-3">
            <p className="mb-1 text-xs font-medium text-accent-ink">{chart ? "Lecture" : "Intégration"}</p>
            <Markdown className="text-sm">{notes}</Markdown>
          </div>
        )}
        <div className="p-4">
          {chart && <ChartView spec={chart} />}
          {preview?.view === "table" && <DataTable table={preview.table} />}
          {preview?.view === "schema" && (
            <div className="space-y-5">
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
          {!preview && !chart && artifact.kind === "markdown" && <Markdown>{artifact.content}</Markdown>}
          {!preview && !chart && artifact.kind !== "markdown" && <CodeBlock code={artifact.content} />}
        </div>
      </div>
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  const lines = code.replace(/\n$/, "").split("\n");
  return (
    <pre className="overflow-x-auto rounded-md border border-atelier-border-soft bg-sunken py-3 font-mono text-[0.8125rem] leading-relaxed">
      <code className="grid grid-cols-[auto_1fr]">
        {lines.map((line, i) => (
          <span key={i} className="contents">
            <span className="select-none px-3 text-right text-muted-foreground/70" aria-hidden>
              {i + 1}
            </span>
            <span className="pr-4 whitespace-pre">{line || " "}</span>
          </span>
        ))}
      </code>
    </pre>
  );
}

function DataTable({ table, caption }: { table: TableData; caption?: string }) {
  return (
    <div>
      {caption && <h3 className="mb-2 text-xs font-medium text-muted-foreground">{caption}</h3>}
      <div className="overflow-x-auto rounded-md border border-atelier-border bg-card shadow-glow">
        <table className="w-full text-sm">
          <thead className="bg-signature-faint text-accent-ink">
            <tr>
              {table.headers.map((h, i) => (
                <th
                  key={`${h}-${i}`}
                  scope="col"
                  className={cn(
                    "px-2.5 py-1.5 font-medium whitespace-nowrap",
                    table.numeric[i] ? "text-right" : "text-left",
                  )}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, r) => (
              <tr key={r} className="border-t">
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
      <p className="mt-1.5 text-xs text-muted-foreground">
        {table.rows.length} ligne{table.rows.length > 1 ? "s" : ""}
      </p>
    </div>
  );
}
