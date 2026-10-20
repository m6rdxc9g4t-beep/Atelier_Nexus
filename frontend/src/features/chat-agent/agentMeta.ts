import {
  Bot,
  Briefcase,
  CalendarCheck,
  ChartColumn,
  Clapperboard,
  Code2,
  GraduationCap,
  Headset,
  Landmark,
  Lightbulb,
  ListChecks,
  type LucideIcon,
  type LucideProps,
  Megaphone,
  Network,
  PenLine,
  Receipt,
  Scale,
  ShieldCheck,
  Sparkles,
  Table2,
  Users,
} from "lucide-react";
import { createElement } from "react";

/** Icônes Lucide proposées aux agents (liste identique à app/schemas/agents.py). */
const BY_ICON: Record<string, LucideIcon> = {
  bot: Bot,
  sparkles: Sparkles,
  network: Network,
  "chart-column": ChartColumn,
  "list-checks": ListChecks,
  code: Code2,
  landmark: Landmark,
  receipt: Receipt,
  megaphone: Megaphone,
  "pen-line": PenLine,
  briefcase: Briefcase,
  scale: Scale,
  users: Users,
  lightbulb: Lightbulb,
  "graduation-cap": GraduationCap,
  clapperboard: Clapperboard,
  headset: Headset,
  "shield-check": ShieldCheck,
  "calendar-check": CalendarCheck,
  "table-2": Table2,
};

export function agentIcon(icon?: string | null): LucideIcon {
  return (icon && BY_ICON[icon]) || Bot;
}

export { BY_ICON as AGENT_ICONS };

/** Icône d'agent (composant stable : la table d'icônes est figée au chargement). */
export function AgentIcon({ icon, ...props }: LucideProps & { icon?: string | null }) {
  return createElement(agentIcon(icon), props);
}
