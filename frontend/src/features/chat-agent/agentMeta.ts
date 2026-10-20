import { type LucideProps } from "lucide-react";
import { createElement } from "react";
import {
  Bot,
  ChartColumn,
  Code2,
  Landmark,
  ListChecks,
  type LucideIcon,
  Megaphone,
  Network,
  Receipt,
  Sparkles,
} from "lucide-react";

/** Icône Lucide déclarée par l'agent (champ `icon`), sinon déduite de son nom. */
const BY_ICON: Record<string, LucideIcon> = {
  bot: Bot,
  sparkles: Sparkles,
  "chart-column": ChartColumn,
  "list-checks": ListChecks,
  code: Code2,
  landmark: Landmark,
  receipt: Receipt,
  megaphone: Megaphone,
  network: Network,
};

export function agentIcon(icon?: string | null): LucideIcon {
  return (icon && BY_ICON[icon]) || Bot;
}

export { BY_ICON as AGENT_ICONS };

/** Icône d'agent (composant stable : la table d'icônes est figée au chargement). */
export function AgentIcon({ icon, ...props }: LucideProps & { icon?: string | null }) {
  return createElement(agentIcon(icon), props);
}
