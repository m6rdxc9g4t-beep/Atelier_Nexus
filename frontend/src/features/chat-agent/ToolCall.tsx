"use client";

import { ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import { ActionStatusIcon } from "./ActionStatusIcon";
import { type ActivityEntry, formatParams } from "./thread";

/** Libellés lisibles des outils connus ; les autres gardent leur nom technique.
 * Mêmes noms que `backend/app/tools/labels.py` (résumés des cartes de validation). */
const TOOL_LABELS: Record<string, string> = {
  current_datetime: "Date et heure",
  publish_artifact: "Publication d'un artefact",
  data_via_list_datasets: "Data Via · jeux de données",
  data_via_describe_dataset: "Data Via · schéma",
  data_via_query: "Data Via · requête",
  data_via_check_expression: "Data Via · vérification de mesure",
  projets_list_projects: "Projets · liste",
  projets_dashboard: "Projets · tableau de bord",
  projets_structure: "Projets · arborescence",
  projets_list_work_items: "Projets · éléments",
  projets_work_item: "Projets · détail d'un élément",
  projets_timesheet: "Projets · feuille de temps",
  projets_milestones: "Projets · jalons",
  projets_create_work_item: "Projets · création d'un élément",
  projets_update_work_item: "Projets · modification d'un élément",
  projets_add_time_entry: "Projets · saisie de temps",
  projets_add_log_entry: "Projets · journal d'avancement",
  tresorerie_dashboard: "Trésorerie · synthèse",
  tresorerie_accounts: "Trésorerie · comptes",
  tresorerie_categories: "Trésorerie · catégories",
  tresorerie_transactions: "Trésorerie · opérations",
  tresorerie_budgets: "Trésorerie · budgets",
  tresorerie_goals: "Trésorerie · objectifs",
  tresorerie_holdings: "Trésorerie · placements",
  tab_list_tables: "Tab · tables",
  tab_read_table: "Tab · lecture d'une table",
  tab_aggregate: "Tab · totaux",
  tab_check_table: "Tab · contrôle",
  tab_set_cells: "Tab · modification de cellules",
  tab_add_rows: "Tab · ajout de lignes",
  tab_delete_rows: "Tab · suppression de lignes",
  tab_add_column: "Tab · ajout d'une colonne",
  tab_create_table: "Tab · création d'une table",
  projets_preview_tab_import: "Projets · aperçu de l'import Tab",
  projets_import_tab_table: "Projets · import d'une table Tab",
  cine_library: "Ciné · médiathèque",
  cine_title: "Ciné · fiche",
  cine_library_report: "Ciné · bilan",
  cine_ai_summary: "Ciné · synopsis (IA locale)",
  cine_scan: "Ciné · analyse des dossiers",
  savoir_overview: "Savoir · vue d'ensemble",
  savoir_course: "Savoir · cours",
  savoir_chapter: "Savoir · chapitre",
  savoir_flashcards: "Savoir · cartes",
  savoir_due_cards: "Savoir · séance du jour",
  savoir_create_course: "Savoir · création d'un cours",
  savoir_add_chapter: "Savoir · ajout d'un chapitre",
  savoir_add_flashcards: "Savoir · ajout de cartes",
  savoir_record_reviews: "Savoir · résultats de la séance",
  cuisine_stock: "Cuisine · stock",
  cuisine_meal_plan: "Cuisine · planning des repas",
  cuisine_shopping_list: "Cuisine · liste de courses",
  cuisine_budget: "Cuisine · budget du mois",
  github_repo_overview: "GitHub · dépôt",
  github_list_files: "GitHub · fichiers",
  github_read_file: "GitHub · lecture d'un fichier",
  github_search_code: "GitHub · recherche de code",
  github_list_pull_requests: "GitHub · pull requests",
  github_list_issues: "GitHub · tickets",
  github_create_branch: "GitHub · création de branche",
  github_commit_files: "GitHub · commit",
  github_open_pull_request: "GitHub · pull request",
  delegate_to_agent: "Délégation à un agent",
};

/** Libellés envoyés par le backend avec la fiche des agents (outils des extensions, nouveaux
 * outils) : complètent la liste ci-dessus sans la remplacer. */
const backendLabels = new Map<string, string>();

export function registerToolLabels(agents: { tools: { name: string; label?: string }[] }[]): void {
  for (const agent of agents) {
    for (const tool of agent.tools) {
      if (tool.label && tool.label !== tool.name) backendLabels.set(tool.name, tool.label);
    }
  }
}

export const toolLabel = (name: string) => TOOL_LABELS[name] ?? backendLabels.get(name) ?? name;

/**
 * Une action de la chronologie d'activité (ToolActivity) : ligne sans boîte — état, libellé,
 * résumé de sa validation et décision — qui se déplie sur ses paramètres et son résultat.
 */
export function ToolCall({ entry, label }: { entry: ActivityEntry; label: string }) {
  return (
    <li>
      <details className="group/tool">
        <summary className="-mx-1.5 flex cursor-pointer list-none items-start gap-2 rounded-md px-1.5 py-1 text-muted-foreground select-none hover:bg-accent hover:text-foreground [&::-webkit-details-marker]:hidden">
          <ActionStatusIcon status={entry.status} className="mt-0.5" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-foreground">{label}</span>
            {entry.summary && <span className="block truncate text-xs">{entry.summary}</span>}
          </span>
          {entry.decision !== undefined && (
            <Badge variant={entry.decision ? "success" : "outline"}>{entry.decision ? "Autorisée" : "Refusée"}</Badge>
          )}
          <ChevronRight className="mt-0.5 size-4 shrink-0 transition-transform group-open/tool:rotate-90" aria-hidden />
        </summary>
        <div className="mt-1 mb-2 flex flex-col gap-2 pl-6">
          <Detail label="Paramètres">{formatParams(entry.input)}</Detail>
          {entry.result !== undefined && <Detail label="Résultat">{entry.result}</Detail>}
        </div>
      </details>
    </li>
  );
}

function Detail({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <p className="mb-1 text-xs text-muted-foreground">{label}</p>
      <pre className="max-h-64 overflow-auto rounded-md border border-atelier-line bg-sunken p-2.5 font-mono text-xs leading-snug break-words whitespace-pre-wrap">
        {children}
      </pre>
    </div>
  );
}
