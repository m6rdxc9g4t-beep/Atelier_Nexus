/**
 * Catalogue des étapes (GET /api/workflows/catalog) : regroupement par application, filtre,
 * libellés et couleurs signature. Logique pure, testée dans catalog.test.ts.
 */

import type { ActionKind, Catalog, CatalogEntry, NodeAppStatus, StepUses } from "@/types/api";

/** Couleurs signature de la suite (docs/SUITE.md §1.7, docs/workflows-v2-api.md §3). */
export const APP_COLORS: Record<string, string> = {
  viz: "#F2C811",
  tab: "#21A366",
  projets: "#94D82D",
  nexus: "#E8590C",
  cine: "#E64980",
  savoir: "#9B5DE5",
  tresorerie: "#3B5BDB",
  cuisine: "#E056E2",
  dates: "#E03131",
};

/** Applications dont la marque (atelier-brand.css) connaît la signature : `data-atelier-app` suffit. */
const BRAND_APPS = new Set(Object.keys(APP_COLORS));

/** Outil système (app null) : couleur de Nexus. */
export const SYSTEM_APP = "nexus";

export const appKey = (app: string | null | undefined): string => app || SYSTEM_APP;

export const KIND_LABEL: Record<ActionKind, string> = {
  read: "Lecture",
  write: "Écriture",
  destructive: "Destructif",
};

export const APP_STATUS_LABEL: Record<NodeAppStatus, string> = {
  ok: "joignable",
  unreachable: "injoignable",
  no_contract: "sans contrat",
  not_configured: "non configurée",
};

/**
 * Attributs qui mettent un élément dans la couleur de SON application : `data-atelier-app`
 * recalcule tous les jetons --atelier-* (bordures, halos, fonds) ; pour une application que la
 * marque ne connaît pas, la couleur reçue du backend est posée comme signature.
 */
export function appTheme(
  app: string | null | undefined,
  color?: string | null,
): { "data-atelier-app": string; style?: Record<string, string> } {
  const key = appKey(app);
  if (BRAND_APPS.has(key)) return { "data-atelier-app": key };
  const signature = color && /^#[0-9a-f]{3,8}$/i.test(color) ? color : APP_COLORS[SYSTEM_APP]!;
  return { "data-atelier-app": key, style: { "--atelier-signature": signature } };
}

export interface ParsedUses {
  source: "tool" | "node" | null;
  app: string | null;
  /** Nom de l'outil ou identifiant de l'action */
  name: string;
}

/** "tool:data_via_query" · "node:projets/work_items.create" */
export function parseUses(uses: StepUses): ParsedUses {
  if (uses.startsWith("tool:")) return { source: "tool", app: null, name: uses.slice(5) };
  if (uses.startsWith("node:")) {
    const rest = uses.slice(5);
    const slash = rest.indexOf("/");
    if (slash > 0) return { source: "node", app: rest.slice(0, slash), name: rest.slice(slash + 1) };
    return { source: "node", app: null, name: rest };
  }
  return { source: null, app: null, name: uses };
}

export const catalogIndex = (catalog: Catalog | null | undefined): Map<string, CatalogEntry> =>
  new Map((catalog?.entries ?? []).map((e) => [e.uses, e]));

export interface CatalogGroup {
  /** Identifiant de l'application ; null = outils système */
  app: string | null;
  key: string;
  name: string;
  status: NodeAppStatus;
  color: string;
  entries: CatalogEntry[];
  /** Nombre d'entrées avant filtrage */
  total: number;
}

/** Minuscules sans accents, pour un filtre tolérant (« écriture » = « ecriture »). */
export const fold = (text: string): string =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

export interface GroupOptions {
  /** Ne garder que ces natures d'action */
  kinds?: ActionKind[];
  /** Masquer les entrées indisponibles */
  availableOnly?: boolean;
}

/**
 * Groupes de la palette : un par application (ordre de `catalog.apps`), puis les applications
 * vues seulement dans les entrées, puis les outils système. Dans un groupe, les entrées
 * disponibles d'abord. Avec un filtre, les groupes sans résultat disparaissent ; sans filtre, une
 * application sans entrée reste visible (on voit qu'elle est injoignable ou sans contrat).
 */
export function groupCatalog(catalog: Catalog, query = "", options: GroupOptions = {}): CatalogGroup[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  const filtering = words.length > 0 || !!options.kinds || !!options.availableOnly;
  const groups = new Map<string, CatalogGroup>();
  const ensure = (app: string | null): CatalogGroup => {
    const key = app ?? "";
    let group = groups.get(key);
    if (!group) {
      const meta = app ? catalog.apps.find((a) => a.app === app) : undefined;
      group = {
        app,
        key: appKey(app),
        name: app ? (meta?.name ?? app) : "Outils Nexus",
        status: meta?.status ?? "ok",
        color: meta?.color ?? APP_COLORS[appKey(app)] ?? APP_COLORS[SYSTEM_APP]!,
        entries: [],
        total: 0,
      };
      groups.set(key, group);
    }
    return group;
  };
  for (const app of catalog.apps) ensure(app.app);

  for (const entry of catalog.entries) {
    const group = ensure(entry.app);
    group.total += 1;
    if (options.kinds && !options.kinds.includes(entry.kind)) continue;
    if (options.availableOnly && !entry.available) continue;
    if (words.length) {
      const haystack = fold(`${entry.label} ${entry.description} ${entry.uses} ${group.name} ${KIND_LABEL[entry.kind]}`);
      if (!words.every((w) => haystack.includes(w))) continue;
    }
    group.entries.push(entry);
  }

  const ordered = [...groups.values()].sort((a, b) => {
    if (a.app === null) return 1;
    if (b.app === null) return -1;
    return 0;
  });
  for (const group of ordered) {
    // Tri stable : disponibles d'abord, ordre du catalogue ensuite
    group.entries = group.entries
      .map((e, i) => ({ e, i }))
      .sort((x, y) => Number(y.e.available) - Number(x.e.available) || x.i - y.i)
      .map(({ e }) => e);
  }
  return filtering ? ordered.filter((g) => g.entries.length > 0) : ordered;
}

/** Libellé lisible d'une étape quand le catalogue ne la connaît pas. */
export function usesLabel(uses: StepUses, entry?: CatalogEntry | null): string {
  if (entry) return entry.label;
  const parsed = parseUses(uses);
  return parsed.app ? `${parsed.app} · ${parsed.name}` : parsed.name;
}
