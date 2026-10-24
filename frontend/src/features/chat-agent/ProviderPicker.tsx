"use client";

import { Lock } from "lucide-react";

import { NativeSelect } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/useChatStore";
import type { AgentInfo, ProviderName, ProviderStatus } from "@/types/api";

const PROVIDER_LABEL: Record<ProviderName, string> = { anthropic: "Claude", ollama: "Ollama (local)" };

function providerNote(p: ProviderStatus): string {
  if (!p.configured) return " — non configuré";
  if (!p.available) return " — injoignable";
  return "";
}

/**
 * Moteur d'IA de la conversation (Claude, Ollama ou celui par défaut) ; un agent « 100 % local »
 * est verrouillé sur Ollama et l'indique à la place du choix.
 */
export function ProviderPicker({
  agent,
  providers,
  className,
}: {
  agent: AgentInfo | undefined;
  providers: ProviderStatus[];
  className?: string;
}) {
  const provider = useChatStore((s) => s.provider);
  const setProvider = useChatStore((s) => s.setProvider);
  const fallback = providers.find((p) => p.is_default);
  const locked = agent?.local_only ?? false;

  return (
    <>
      <label htmlFor="provider-select" className="sr-only">
        Moteur d&apos;IA
      </label>
      {locked ? (
        <span
          id="provider-select"
          className={cn(
            "flex h-8 items-center gap-1.5 rounded-lg border border-atelier-line bg-signature-faint px-2.5 text-[13px] text-muted-foreground",
            className,
          )}
          title="Agent verrouillé sur le modèle local : ses données ne quittent pas la machine"
        >
          <Lock className="size-3.5 shrink-0" aria-hidden />
          <span className="truncate">Ollama (local) imposé</span>
        </span>
      ) : (
        <NativeSelect
          id="provider-select"
          className={className}
          value={provider ?? ""}
          onChange={(e) => setProvider((e.target.value || null) as ProviderName | null)}
        >
          <option value="">Par défaut{fallback ? ` (${PROVIDER_LABEL[fallback.name]})` : ""}</option>
          {providers.map((p) => (
            <option key={p.name} value={p.name} disabled={!p.configured}>
              {PROVIDER_LABEL[p.name]}
              {providerNote(p)}
            </option>
          ))}
        </NativeSelect>
      )}
    </>
  );
}
