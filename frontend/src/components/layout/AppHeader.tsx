"use client";

import { Layers } from "lucide-react";

import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useArtifactStore } from "@/stores/useArtifactStore";
import { useChatStore } from "@/stores/useChatStore";
import type { AgentInfo, DataViaStatus, ProviderName, ProviderStatus } from "@/types/api";

import { AtelierBrand } from "./AtelierBrand";
import { SuiteSwitcher } from "./SuiteSwitcher";
import { ThemeMenu } from "./ThemeMenu";

const PROVIDER_LABEL: Record<ProviderName, string> = { anthropic: "Claude", ollama: "Ollama (local)" };

function providerNote(p: ProviderStatus): string {
  if (!p.configured) return " — non configuré";
  if (!p.available) return " — injoignable";
  return "";
}

interface AppHeaderProps {
  agents: AgentInfo[];
  providers: ProviderStatus[];
  dataVia: DataViaStatus | null;
}

export function AppHeader({ agents, providers, dataVia }: AppHeaderProps) {
  const agent = useChatStore((s) => s.agent);
  const setAgent = useChatStore((s) => s.setAgent);
  const provider = useChatStore((s) => s.provider);
  const setProvider = useChatStore((s) => s.setProvider);
  const streaming = useChatStore((s) => s.streaming);
  const artifactCount = useArtifactStore((s) => s.artifacts.length);
  const panelOpen = useArtifactStore((s) => s.panelOpen);
  const setPanelOpen = useArtifactStore((s) => s.setPanelOpen);

  const fallback = providers.find((p) => p.is_default);

  return (
    <header className="flex h-14 shrink-0 items-center gap-1.5 border-b bg-card px-2 sm:gap-2 sm:px-3">
      <SuiteSwitcher />
      <AtelierBrand />

      {/* Petits écrans : choix de l'agent ici (la barre latérale est masquée) */}
      <label htmlFor="agent-select" className="sr-only">
        Agent
      </label>
      <NativeSelect
        id="agent-select"
        className="ml-1 min-w-0 flex-1 basis-0 sm:max-w-48 sm:flex-none sm:basis-auto lg:hidden"
        value={agent}
        disabled={streaming}
        onChange={(e) => setAgent(e.target.value)}
      >
        {agents.map((a) => (
          <option key={a.name} value={a.name}>
            {a.display_name}
          </option>
        ))}
      </NativeSelect>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {dataVia && (
          <span
            className="hidden items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground md:flex"
            title={dataVia.error ?? dataVia.base_url ?? undefined}
          >
            <span
              aria-hidden
              className={cn("size-1.5 rounded-full", dataVia.available ? "bg-success" : "bg-muted-foreground/50")}
            />
            Data Via {dataVia.available ? `· ${dataVia.datasets ?? 0} jeux` : "arrêté"}
          </span>
        )}

        <label htmlFor="provider-select" className="sr-only">
          Moteur d&apos;IA
        </label>
        <NativeSelect
          id="provider-select"
          className="w-28 sm:w-52"
          value={provider ?? ""}
          onChange={(e) => setProvider((e.target.value || null) as ProviderName | null)}
        >
          <option value="">
            Par défaut{fallback ? ` (${PROVIDER_LABEL[fallback.name]})` : ""}
          </option>
          {providers.map((p) => (
            <option key={p.name} value={p.name} disabled={!p.configured}>
              {PROVIDER_LABEL[p.name]}
              {providerNote(p)}
            </option>
          ))}
        </NativeSelect>

        {artifactCount > 0 && !panelOpen && (
          <Button variant="ghost" size="sm" onClick={() => setPanelOpen(true)}>
            <Layers />
            <span className="hidden sm:inline">Artefacts</span>
            <span className="text-muted-foreground">{artifactCount}</span>
          </Button>
        )}
        <ThemeMenu />
      </div>
    </header>
  );
}
