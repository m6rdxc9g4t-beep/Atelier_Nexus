"use client";

import { Download, FileCode, FileSpreadsheet, FileText, ImageOff, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { attachmentUrl } from "@/lib/api";
import { saveBlob } from "@/lib/desktop";
import { cn } from "@/lib/utils";
import type { AttachmentBlock } from "@/types/api";

import { fileFamily, formatSize } from "./attachments";

/** Icône d'un fichier joint selon sa famille (tableur, texte, code). */
export function FileIcon({
  name,
  mediaType,
  className,
}: {
  name: string;
  mediaType: string;
  className?: string;
}) {
  const family = fileFamily(name, mediaType);
  const Icon = family === "sheet" ? FileSpreadsheet : family === "text" ? FileText : FileCode;
  return <Icon className={cn("size-4", className)} aria-hidden />;
}

/** Télécharge le fichier d'origine (boîte « Enregistrer sous » dans l'app de bureau). */
async function download(item: AttachmentBlock): Promise<void> {
  const response = await fetch(attachmentUrl(item.id));
  if (!response.ok)
    throw new Error(response.status === 404 ? "Fichier supprimé." : `Erreur ${response.status}`);
  await saveBlob(item.name, await response.blob());
}

/** Fichiers joints d'un message de l'utilisateur : vignettes d'images, puces de documents. */
export function MessageAttachments({ items }: { items: AttachmentBlock[] }) {
  const [zoom, setZoom] = useState<AttachmentBlock | null>(null);
  return (
    <>
      <ul aria-label="Fichiers joints" className="flex max-w-[85%] flex-wrap justify-end gap-2">
        {items.map((item) => (
          <li key={item.id}>
            {item.kind === "image" ? (
              <ImageThumb item={item} onOpen={() => setZoom(item)} />
            ) : (
              <DocumentChip item={item} />
            )}
          </li>
        ))}
      </ul>
      <Dialog open={zoom !== null} onOpenChange={(open) => !open && setZoom(null)}>
        <DialogContent className="max-w-4xl grid-cols-[minmax(0,1fr)]">
          {zoom && (
            <>
              <DialogHeader>
                <DialogTitle className="truncate pr-6">{zoom.name}</DialogTitle>
                <DialogDescription>
                  Image transmise à l&apos;agent (réduite à 1 568 px au plus).
                </DialogDescription>
              </DialogHeader>
              {/* eslint-disable-next-line @next/next/no-img-element -- image servie par l'API locale */}
              <img
                src={attachmentUrl(zoom.id)}
                alt={zoom.name}
                className="max-h-[70vh] w-full rounded-md border object-contain"
              />
              <DownloadButton item={zoom} className="justify-self-end" />
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function ImageThumb({ item, onOpen }: { item: AttachmentBlock; onOpen: () => void }) {
  const [failed, setFailed] = useState(false);
  if (failed)
    return (
      <span className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm text-muted-foreground">
        <ImageOff className="size-4" aria-hidden />
        {item.name} (supprimée)
      </span>
    );
  return (
    <button
      type="button"
      onClick={onOpen}
      className="block overflow-hidden rounded-md border border-atelier-border-soft outline-none focus-visible:shadow-focus"
      aria-label={`Agrandir « ${item.name} »`}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- image servie par l'API locale */}
      <img
        src={attachmentUrl(item.id)}
        alt={item.name}
        loading="lazy"
        onError={() => setFailed(true)}
        className="h-28 max-w-56 bg-muted object-cover"
      />
    </button>
  );
}

function DocumentChip({ item }: { item: AttachmentBlock }) {
  const [state, setState] = useState<"idle" | "busy" | string>("idle");
  const problem = state !== "idle" && state !== "busy" ? state : null;
  return (
    <button
      type="button"
      onClick={() => {
        setState("busy");
        download(item)
          .then(() => setState("idle"))
          .catch((err: unknown) =>
            setState(err instanceof Error ? err.message : "Téléchargement impossible."),
          );
      }}
      title={`Télécharger « ${item.name} »`}
      className="flex max-w-72 items-center gap-2.5 rounded-md border border-atelier-border-soft bg-card px-3 py-2 text-left text-sm outline-none hover:border-primary focus-visible:shadow-focus"
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-sm bg-accent-soft text-accent-ink">
        {state === "busy" ? (
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
        ) : (
          <FileIcon name={item.name} mediaType={item.media_type} />
        )}
      </span>
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-medium">{item.name}</span>
        <span className={cn("text-xs text-muted-foreground", problem && "text-destructive")}>
          {problem ?? formatSize(item.size)}
        </span>
      </span>
    </button>
  );
}

function DownloadButton({ item, className }: { item: AttachmentBlock; className?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      className={className}
      disabled={busy}
      onClick={() => {
        setBusy(true);
        void download(item).finally(() => setBusy(false));
      }}
    >
      {busy ? <LoaderCircle className="animate-spin" /> : <Download />}
      Télécharger
    </Button>
  );
}
