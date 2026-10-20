"use client";

import { ArrowUp, Square } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ComposerProps {
  agentName: string;
  streaming: boolean;
  disabled?: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** Zone de saisie : Entrée envoie, Maj+Entrée va à la ligne. */
export function Composer({ agentName, streaming, disabled, onSend, onStop }: ComposerProps) {
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim() || streaming || disabled) return;
    onSend(text);
    setText("");
  };

  return (
    <form
      className="mx-auto w-full max-w-3xl px-4 pb-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="relative rounded-lg border border-input bg-card shadow-sm focus-within:border-primary focus-within:ring-[3px] focus-within:ring-ring">
        <label htmlFor="composer" className="sr-only">
          Message pour {agentName}
        </label>
        <Textarea
          id="composer"
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={`Écrire à ${agentName}…`}
          rows={1}
          className="max-h-60 min-h-12 resize-none border-0 bg-transparent py-3 pr-14 shadow-none focus-visible:ring-0"
        />
        <div className="absolute right-2 bottom-2">
          {streaming ? (
            <Button type="button" size="icon-sm" variant="secondary" onClick={onStop} aria-label="Arrêter la réponse">
              <Square className="size-3.5 fill-current" />
            </Button>
          ) : (
            <Button type="submit" size="icon-sm" disabled={!text.trim() || disabled} aria-label="Envoyer">
              <ArrowUp />
            </Button>
          )}
        </div>
      </div>
      <p className="mt-1.5 text-center text-xs text-muted-foreground">
        Les agents peuvent se tromper : vérifiez les chiffres et le code avant de les utiliser.
      </p>
    </form>
  );
}
