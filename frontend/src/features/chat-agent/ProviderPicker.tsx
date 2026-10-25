"use client";

import { ChevronDown, Cpu, Lock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { PROVIDER_LABEL, PROVIDER_SHORT, effectiveProvider, providerProblem } from "@/lib/labels";
import { useChatStore } from "@/stores/useChatStore";
import type { AgentInfo, ProviderName, ProviderStatus } from "@/types/api";

/**
 * Moteur d'IA de la conversation, dans la barre d'outils du composer : puce qui ouvre un choix
 * « Par défaut / Claude / Ollama (local) » (moteurs non configurés désactivés, avec la raison).
 * Un agent « 100 % local » est verrouillé sur Ollama : une étiquette non interactive le dit.
 */
export function ProviderPicker({ agent, providers }: { agent: AgentInfo | undefined; providers: ProviderStatus[] }) {
  const provider = useChatStore((s) => s.provider);
  const setProvider = useChatStore((s) => s.setProvider);

  if (agent?.local_only) {
    return (
      <Badge
        variant="signature"
        className="h-7 rounded-full px-2.5"
        title="Agent verrouillé sur le modèle local : ses données ne quittent pas la machine"
      >
        <Lock aria-hidden />
        Ollama · local imposé
      </Badge>
    );
  }

  // « Par défaut » = défaut de l'agent, sinon celui du serveur
  const fallback = effectiveProvider(agent, null, providers);
  const defaultLabel = `Par défaut${fallback ? ` (${PROVIDER_SHORT[fallback]})` : ""}`;
  const current = provider ? PROVIDER_SHORT[provider] : defaultLabel;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 max-w-48 gap-1 rounded-full px-2.5 text-xs"
          aria-label={`Moteur d'IA : ${current}`}
        >
          <Cpu className="size-3.5" aria-hidden />
          <span className="truncate">{current}</span>
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="min-w-56">
        <DropdownMenuLabel>Moteur d&apos;IA de la conversation</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={provider ?? ""}
          onValueChange={(value) => setProvider((value || null) as ProviderName | null)}
        >
          <DropdownMenuRadioItem value="">{defaultLabel}</DropdownMenuRadioItem>
          {providers.map((p) => {
            const problem = providerProblem(p);
            return (
              <DropdownMenuRadioItem
                key={p.name}
                value={p.name}
                disabled={!p.configured}
                className="data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
              >
                <span className="flex-1">{PROVIDER_LABEL[p.name]}</span>
                {problem && <span className="text-xs text-muted-foreground">{problem}</span>}
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
