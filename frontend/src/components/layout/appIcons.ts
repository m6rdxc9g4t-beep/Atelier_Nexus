import {
  ArrowLeftRight,
  BookOpen,
  ChartColumn,
  Clapperboard,
  ClipboardList,
  GitBranch,
  GraduationCap,
  Heart,
  Kanban,
  type LucideIcon,
  type LucideProps,
  Plug,
  Table,
  Utensils,
  Wallet,
  Workflow,
} from "lucide-react";
import { createElement } from "react";

/**
 * Icône de chaque application de la suite (sélecteur, palette des workflows, carte de la suite) :
 * mêmes glyphes Lucide que le portail (SUITE.md §1.6). GitHub n'est pas une app de la suite.
 */
export const APP_ICONS: Record<string, LucideIcon> = {
  nexus: Workflow,
  viz: ChartColumn,
  tab: Table,
  projets: Kanban,
  tresorerie: Wallet,
  cine: Clapperboard,
  savoir: GraduationCap,
  cuisine: Utensils,
  dates: Heart,
  convert: ArrowLeftRight,
  wiki: BookOpen,
  formulaire: ClipboardList,
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
  wiki: "Wiki",
  formulaire: "Formulaire",
  github: "GitHub",
};

export const appShort = (app: string | null | undefined): string => APP_SHORT[app || "nexus"] ?? (app || "Nexus");

/** Application inconnue : prise générique. */
export const appIcon = (app: string | null | undefined): LucideIcon => APP_ICONS[app || "nexus"] ?? Plug;

/** Icône d'application (composant stable : la table d'icônes est figée au chargement). */
export function AppIcon({ app, ...props }: LucideProps & { app: string | null | undefined }) {
  return createElement(appIcon(app), props);
}
