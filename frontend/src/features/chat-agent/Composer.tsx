"use client";

import { ArrowUp, CircleAlert, LoaderCircle, Paperclip, Square, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AttachmentBlock, AttachmentInfo } from "@/types/api";

import { FileIcon } from "./AttachmentView";
import { ACCEPT, MAX_FILES, describe, isImageName, pastedName, precheck, toBlock } from "./attachments";

interface ComposerProps {
  agentName: string;
  streaming: boolean;
  disabled?: boolean;
  onSend: (text: string, attachments: AttachmentBlock[]) => void;
  onStop: () => void;
  /** Choix du moteur, dans la barre d'outils (reste utilisable quand l'envoi est bloqué) */
  engine?: ReactNode;
}

interface PendingFile {
  key: string;
  name: string;
  /** Aperçu local d'une image (URL d'objet), avant même la fin de l'envoi */
  preview: string | null;
  status: "uploading" | "ready" | "error";
  info?: AttachmentInfo;
  error?: string;
}

let fileSeq = 0;

/**
 * Zone de saisie : Entrée envoie, Maj+Entrée va à la ligne. Fichiers : trombone, glisser-déposer
 * ou coller (captures d'écran). Chaque fichier est envoyé au serveur dès qu'il est ajouté.
 * Surface calme : le halo n'apparaît qu'au focus. Barre d'outils interne : Joindre, moteur,
 * aide clavier, Envoyer / Arrêter.
 */
export function Composer({ agentName, streaming, disabled, onSend, onStop, engine }: ComposerProps) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const controllers = useRef(new Map<string, AbortController>());
  const previews = useRef(new Set<string>());

  // Aperçus libérés et envois en cours annulés en quittant
  useEffect(() => {
    const urls = previews.current;
    const uploads = controllers.current;
    return () => {
      for (const url of urls) URL.revokeObjectURL(url);
      for (const c of uploads.values()) c.abort();
    };
  }, []);

  const patch = (key: string, change: Partial<PendingFile>) =>
    setFiles((list) => list.map((f) => (f.key === key ? { ...f, ...change } : f)));

  const release = (file: PendingFile) => {
    if (file.preview) {
      URL.revokeObjectURL(file.preview);
      previews.current.delete(file.preview);
    }
  };

  const add = (incoming: File[]) => {
    if (!incoming.length || disabled) return;
    const room = MAX_FILES - files.filter((f) => f.status !== "error").length;
    const added: PendingFile[] = incoming.map((raw, index) => {
      const name = pastedName(raw);
      const file = name === raw.name ? raw : new File([raw], name, { type: raw.type });
      const key = `f${++fileSeq}`;
      const problem = index >= room ? `${MAX_FILES} fichiers au plus par message.` : precheck(file);
      if (problem) return { key, name, preview: null, status: "error", error: problem };
      const preview = isImageName(name) ? URL.createObjectURL(file) : null;
      if (preview) previews.current.add(preview);
      const controller = new AbortController();
      controllers.current.set(key, controller);
      api
        .uploadAttachment(file, controller.signal)
        .then((info) => patch(key, { status: "ready", info }))
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          patch(key, { status: "error", error: err instanceof ApiError ? err.message : "Envoi impossible." });
        })
        .finally(() => controllers.current.delete(key));
      return { key, name, preview, status: "uploading" };
    });
    setFiles((list) => [...list, ...added]);
  };

  const remove = (file: PendingFile) => {
    controllers.current.get(file.key)?.abort();
    if (file.status === "ready" && file.info) void api.removeAttachment(file.info.id).catch(() => undefined);
    release(file);
    setFiles((list) => list.filter((f) => f.key !== file.key));
  };

  const uploading = files.some((f) => f.status === "uploading");
  const ready = files.filter((f) => f.status === "ready" && f.info);
  const canSend = (text.trim().length > 0 || ready.length > 0) && !uploading && !disabled;

  const submit = () => {
    if (!canSend || streaming) return;
    onSend(
      text.trim(),
      ready.flatMap((f) => (f.info ? [toBlock(f.info)] : [])),
    );
    files.forEach(release);
    setFiles([]);
    setText("");
  };

  return (
    <form
      className="mx-auto w-full max-w-3xl px-4 pt-1 pb-[max(1rem,env(safe-area-inset-bottom))]"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDragOver={(e) => {
        if (disabled || !e.dataTransfer.types.includes("Files")) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(e) => {
        if (!e.dataTransfer.files.length) return;
        e.preventDefault();
        setDragging(false);
        add([...e.dataTransfer.files]);
      }}
    >
      <div
        className={cn(
          "relative rounded-[20px] border border-atelier-border-soft bg-atelier-field transition-[border-color,box-shadow] focus-within:border-primary focus-within:shadow-focus",
          dragging && "border-dashed border-primary bg-accent-soft",
        )}
      >
        {dragging && (
          <p className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-[20px] text-sm font-medium text-accent-ink">
            Déposez les fichiers pour les joindre
          </p>
        )}
        {files.length > 0 && (
          <ul
            aria-label="Fichiers joints"
            className={cn("flex flex-wrap gap-2 px-3 pt-3", dragging && "opacity-30")}
          >
            {files.map((file) => (
              <PendingChip key={file.key} file={file} onRemove={() => remove(file)} />
            ))}
          </ul>
        )}
        <label htmlFor="composer" className="sr-only">
          Message pour {agentName}
        </label>
        <Textarea
          id="composer"
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onPaste={(e) => {
            const pasted = [...e.clipboardData.files];
            if (pasted.length) {
              e.preventDefault();
              add(pasted);
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={`Écrire à ${agentName}…`}
          rows={1}
          aria-describedby="composer-keys"
          className={cn(
            "max-h-60 min-h-11 resize-none rounded-none border-0 bg-transparent px-4 pt-3 pb-1 shadow-none focus-visible:shadow-none",
            dragging && "opacity-30",
          )}
        />
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            add([...(e.target.files ?? [])]);
            e.target.value = ""; // le même fichier pourra être rejoint
          }}
        />
        <div className={cn("flex items-center gap-1 px-2 pb-2", dragging && "opacity-30")}>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            className="rounded-full"
            disabled={disabled}
            onClick={() => input.current?.click()}
            aria-label="Joindre des fichiers"
            title="Joindre des fichiers : images, PDF, Word, Excel, CSV, texte ou code (vous pouvez aussi les glisser ou coller une capture)"
          >
            <Paperclip />
          </Button>
          {engine}
          <span className="flex-1" />
          <span id="composer-keys" className="mr-1 hidden items-center gap-1 text-xs text-muted-foreground sm:flex">
            {/* Espaces explicites : la description lue (aria-describedby) garde ses mots séparés */}
            <Kbd className="h-5 text-xs">Entrée</Kbd> envoyer · <Kbd className="h-5 text-xs">Maj+Entrée</Kbd> à la
            ligne
          </span>
          {streaming ? (
            <Button
              type="button"
              size="icon-sm"
              variant="secondary"
              className="rounded-full"
              onClick={onStop}
              aria-label="Arrêter la réponse"
            >
              <Square className="size-3.5 fill-current" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon-sm"
              className="rounded-full"
              disabled={!canSend}
              aria-label={uploading ? "Envoi des fichiers en cours" : "Envoyer"}
            >
              {uploading ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}

function PendingChip({ file, onRemove }: { file: PendingFile; onRemove: () => void }) {
  const error = file.status === "error";
  return (
    <li
      className={cn(
        "flex max-w-full items-center gap-2 rounded-md border border-atelier-border-soft bg-card py-1 pr-1 pl-1 text-sm sm:max-w-72",
        error && "border-destructive/40 bg-destructive/5",
      )}
    >
      {file.preview && !error ? (
        // eslint-disable-next-line @next/next/no-img-element -- aperçu local (URL d'objet)
        <img src={file.preview} alt="" className="size-9 shrink-0 rounded-sm object-cover" />
      ) : (
        <span
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-sm bg-muted text-muted-foreground",
            error && "bg-transparent text-destructive",
          )}
        >
          {error ? (
            <CircleAlert className="size-4" aria-hidden />
          ) : (
            <FileIcon name={file.name} mediaType={file.info?.media_type ?? ""} />
          )}
        </span>
      )}
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-medium" title={file.name}>
          {file.name}
        </span>
        <span
          role="status"
          className={cn(
            "truncate text-xs text-muted-foreground",
            error && "whitespace-normal text-destructive-ink",
          )}
        >
          {file.status === "uploading" && "Préparation…"}
          {file.status === "ready" && file.info && describe(file.info)}
          {error && file.error}
        </span>
      </span>
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        className="shrink-0 self-start text-muted-foreground"
        onClick={onRemove}
        aria-label={`Retirer « ${file.name} »`}
      >
        <X />
      </Button>
    </li>
  );
}
