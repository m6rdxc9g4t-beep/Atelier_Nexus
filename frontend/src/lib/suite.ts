/**
 * Suite Atelier : adresses des applications et état de leurs API (docs/SUITE.md §2 et §3).
 * Chaque adresse se surcharge par une variable NEXT_PUBLIC_ATELIER_*_URL.
 */

export type SuiteAppId =
  | "nexus"
  | "viz"
  | "tab"
  | "projets"
  | "tresorerie"
  | "cine"
  | "savoir"
  | "cuisine";

export interface SuiteApp {
  id: SuiteAppId;
  /** Nom accessible (« Atelier Viz »). */
  name: string;
  /** Nom affiché après « atelier_ » dans la marque (SUITE.md §1.6). */
  short: string;
  description: string;
  url: string;
  /** `GET /api/health` (ou équivalent) des applications qui ont une API ; sinon null. */
  healthUrl: string | null;
  /**
   * Application en ligne (hébergée, ex. Atelier Cuisine sur Vercel) : jamais sondée,
   * affichée « en ligne » au lieu d'un état.
   */
  online?: boolean;
}

export type SuiteStatus = "unknown" | "up" | "down";

/** Délai maximal d'une vérification d'état (SUITE.md §3). */
export const HEALTH_TIMEOUT_MS = 1500;

export const CURRENT_APP: SuiteAppId = "nexus";

const clean = (url: string | undefined, fallback: string) =>
  url?.trim() ? url.trim().replace(/\/+$/, "") : fallback;

export function suiteApps(): SuiteApp[] {
  // Vide = même origine (application de bureau : le backend sert l'interface)
  const api =
    process.env.NEXT_PUBLIC_API_URL === ""
      ? ""
      : clean(process.env.NEXT_PUBLIC_API_URL, "http://localhost:8100");
  const projetsApi = clean(process.env.NEXT_PUBLIC_ATELIER_PROJETS_API_URL, "http://127.0.0.1:3000");
  const tresorerie = clean(process.env.NEXT_PUBLIC_ATELIER_TRESORERIE_URL, "http://127.0.0.1:5050");
  const viz = clean(process.env.NEXT_PUBLIC_ATELIER_VIZ_URL, "http://127.0.0.1:8000");
  // Ciné sert son interface sur le port de son API en production (4000 ; app Mac : 47321)
  const cine = clean(process.env.NEXT_PUBLIC_ATELIER_CINE_URL, "http://127.0.0.1:4000");
  // Savoir écoute sur 5050 par défaut, comme Trésorerie : lancé sur 5051 (docs/apps/savoir.md)
  const savoir = clean(process.env.NEXT_PUBLIC_ATELIER_SAVOIR_URL, "http://127.0.0.1:5051");
  // Cuisine est une app en ligne (PWA Vercel + app Mac Tauri) : jamais sondée
  const cuisine = clean(
    process.env.NEXT_PUBLIC_ATELIER_CUISINE_URL,
    "https://atelier-cuisine-iota.vercel.app",
  );
  return [
    {
      id: "nexus",
      name: "Atelier Nexus",
      short: "Nexus",
      description: "Agents IA de la suite",
      url: clean(process.env.NEXT_PUBLIC_ATELIER_NEXUS_URL, "http://localhost:3100"),
      healthUrl: `${api}/api/health`,
    },
    {
      id: "viz",
      name: "Atelier Viz",
      short: "Viz",
      description: "BI locale : rapports, visuels, IA",
      url: viz,
      healthUrl: `${viz}/api/health`,
    },
    {
      id: "tab",
      name: "Atelier Tab",
      short: "Tab",
      description: "Tableur et base typée",
      url: clean(process.env.NEXT_PUBLIC_ATELIER_TAB_URL, "http://127.0.0.1:4175"),
      healthUrl: null,
    },
    {
      id: "projets",
      name: "Atelier Projets",
      short: "Projets",
      description: "Projets agiles, Git, temps passé",
      url: clean(process.env.NEXT_PUBLIC_ATELIER_PROJETS_URL, "http://127.0.0.1:4174"),
      healthUrl: `${projetsApi}/api/health`,
    },
    {
      id: "tresorerie",
      name: "Atelier Trésorerie",
      short: "Trésorerie",
      description: "Comptes, budgets, placements",
      url: tresorerie,
      healthUrl: `${tresorerie}/api/ping`,
    },
    {
      id: "cine",
      name: "Atelier Ciné",
      short: "Ciné",
      description: "Médiathèque : films et séries",
      url: cine,
      healthUrl: `${cine}/api/health`,
    },
    {
      id: "savoir",
      name: "Atelier Savoir",
      short: "Savoir",
      description: "Cours et cartes de révision",
      url: savoir,
      healthUrl: `${savoir}/api/stats`,
    },
    {
      id: "cuisine",
      name: "Atelier Cuisine",
      short: "Cuisine",
      description: "Stock, repas, courses et budget du foyer",
      url: cuisine,
      healthUrl: null,
      online: true,
    },
  ];
}

/** Libellé affiché à la place de l'état pour une application en ligne. */
export const ONLINE_LABEL = "en ligne";

export function statusLabel(status: SuiteStatus): string {
  return status === "up" ? "en marche" : status === "down" ? "arrêtée" : "vérification…";
}

/**
 * Vérifie qu'une API répond, sans jamais lever : `no-cors` (réponse opaque, mais une
 * réponse = serveur en marche), abandon après `timeoutMs`.
 */
export async function checkHealth(
  url: string,
  timeoutMs = HEALTH_TIMEOUT_MS,
  fetcher: typeof fetch = fetch,
): Promise<Exclude<SuiteStatus, "unknown">> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    await fetcher(url, { mode: "no-cors", cache: "no-store", signal: ctrl.signal });
    return "up";
  } catch {
    return "down";
  } finally {
    clearTimeout(timer);
  }
}
