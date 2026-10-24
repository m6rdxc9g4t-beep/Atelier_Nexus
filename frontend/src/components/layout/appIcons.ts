import {
  ArrowRightLeft,
  BarChart3,
  CalendarCheck,
  CalendarDays,
  Clapperboard,
  CookingPot,
  GitBranch,
  GraduationCap,
  Landmark,
  type LucideIcon,
  type LucideProps,
  Network,
  Plug,
  Table2,
} from "lucide-react";
import { createElement } from "react";

/** Icône de chaque application de la suite (sélecteur, palette des workflows, carte de la suite). */
export const APP_ICONS: Record<string, LucideIcon> = {
  nexus: Network,
  viz: BarChart3,
  tab: Table2,
  projets: CalendarCheck,
  tresorerie: Landmark,
  cine: Clapperboard,
  savoir: GraduationCap,
  cuisine: CookingPot,
  dates: CalendarDays,
  convert: ArrowRightLeft,
  github: GitBranch,
};

/** Nom court de chaque application (puces, palette, accueil). */
export const APP_SHORT: Record<string, string> = {
  nexus: "Nexus",
  viz: "Viz",
  tab: "Tab",
  projets: "Projets",
  tresorerie: "Trésorerie",
  cine: "Ciné",
  savoir: "Savoir",
  cuisine: "Cuisine",
  dates: "Dates",
  convert: "Convert",
  github: "GitHub",
};

export const appShort = (app: string | null | undefined): string => APP_SHORT[app || "nexus"] ?? (app || "Nexus");

/** Application inconnue : prise générique. */
export const appIcon = (app: string | null | undefined): LucideIcon => APP_ICONS[app || "nexus"] ?? Plug;

/** Icône d'application (composant stable : la table d'icônes est figée au chargement). */
export function AppIcon({ app, ...props }: LucideProps & { app: string | null | undefined }) {
  return createElement(appIcon(app), props);
}
