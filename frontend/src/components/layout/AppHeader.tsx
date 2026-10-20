"use client";

import { Layers, Lock } from "lucide-react";

import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/select";
import { SettingsDialog } from "@/features/settings/SettingsDialog";
import { useArtifactStore } from "@/stores/useArtifactStore";
import { useChatStore } from "@/stores/useChatStore";
import type { AgentInfo, AppStatus, ProviderName, ProviderStatus } from "@/types/api";

import { AppsMenu } from "./AppsMenu";
import { AtelierBrand } from "./AtelierBrand";
import { SuiteSwitcher } from "./SuiteSwitcher";

const PROVIDER_LABEL: Record<ProviderName, string> = { anthropic: "Claude", ollama: "Ollama (local)" };

function providerNote(p: ProviderStatus): string {
  if (!p.configured) return " — non configuré";
  if (!p.available) return " — injoignable";
  return "";
}

interface AppHeaderProps {
  agents: AgentInfo[];
  providers: ProviderStatus[];
  apps: AppStatus[];
  /** Après un changement de réglages : recharger agents, moteurs et apps. */
  onSettingsSaved: () => Promise<void> | void;
}

export function AppHeader({ agents, providers, apps, onSettingsSaved }: AppHeaderProps) {
  const agent = useChatStore((s) => s.agent);
  const setAgent = useChatStore((s) => s.setAgent);
  const provider = useChatStore((s) => s.provider);
  const setProvider = useChatStore((s) => s.setProvider);
  const streaming = useChatStore((s) => s.streaming);
  const artifactCount = useArtifactStore((s) => s.artifacts.length);
  const panelOpen = useArtifactStore((s) => s.panelOpen);
  const setPanelOpen = useArtifactStore((s) => s.setPanelOpen);

  const fallback = providers.find((p) => p.is_default);
  const current = agents.find((a) => a.name === agent);
  const locked = current?.local_only ?? false;

  return (
    <header className="relative z-10 flex h-14 shrink-0 items-center gap-1.5 border-b border-atelier-border-soft bg-sidebar/85 px-2 shadow-glow backdrop-blur-md sm:gap-2 sm:px-3">
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
        {apps.length > 0 && <AppsMenu apps={apps} />}

        <label htmlFor="provider-select" className="sr-only">
          Moteur d&apos;IA
        </label>
        {locked ? (
          <span
            id="provider-select"
            className="flex h-8 w-28 items-center gap-1.5 rounded-md border border-input bg-signature-faint px-2.5 text-sm text-muted-foreground sm:w-52"
            title="Agent verrouillé sur le modèle local : ses données ne quittent pas la machine"
          >
            <Lock className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">Ollama (local) imposé</span>
          </span>
        ) : (
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
        )}

        {artifactCount > 0 && !panelOpen && (
          <Button variant="ghost" size="sm" onClick={() => setPanelOpen(true)}>
            <Layers />
            <span className="hidden sm:inline">Artefacts</span>
            <span className="text-muted-foreground">{artifactCount}</span>
          </Button>
        )}
        {/* Clair / Sombre / Système ; sur petit écran, dans les Réglages (rubrique Apparence) */}
        <ThemeToggle className="hidden sm:inline-flex" />
        <SettingsDialog onSaved={onSettingsSaved} />
      </div>
    </header>
  );
}
