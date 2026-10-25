/**
 * Applications de la suite qu'un agent utilise, déduites de ses boîtes à outils
 * (docs/agents.md §2). Logique pure, testée dans agentApps.test.ts.
 */

/** Boîte à outils → application (null : outils système, sans application). */
const TOOLSET_APP: Record<string, string | null> = {
  core: null,
  delegation: null,
  data_via: "viz",
  tab: "tab",
  tab_write: "tab",
  tab_projets: "projets",
  projets_read: "projets",
  projets_write: "projets",
  tresorerie: "tresorerie",
  cine: "cine",
  cine_write: "cine",
  savoir_read: "savoir",
  savoir_write: "savoir",
  cuisine: "cuisine",
  cuisine_budget: "cuisine",
  github_read: "github",
  github_write: "github",
  // Boîtes de l'extension Agent_DatAnalyst (le cœur n'ajoute que le nœud de workflow)
  convert: "convert",
  convert_write: "convert",
};

/** Préfixe d'un nom d'outil → application (boîtes des extensions, outils isolés). */
const TOOL_PREFIX_APP: [string, string][] = [
  ["data_via_", "viz"],
  ["tab_", "tab"],
  ["projets_", "projets"],
  ["tresorerie_", "tresorerie"],
  ["cine_", "cine"],
  ["savoir_", "savoir"],
  ["cuisine_", "cuisine"],
  ["github_", "github"],
  ["convert_", "convert"],
];

/** Application d'un outil d'après son nom, ou null (outil système ou inconnu). */
export function toolApp(name: string): string | null {
  for (const [prefix, app] of TOOL_PREFIX_APP) if (name.startsWith(prefix)) return app;
  return null;
}

/**
 * Applications d'un agent, sans doublon, dans l'ordre de ses boîtes ; une boîte inconnue (extension)
 * est rattachée par le préfixe de ses outils.
 */
export function agentApps(agent: { toolsets?: string[]; tools?: { name: string }[] }): string[] {
  const out: string[] = [];
  const add = (app: string | null | undefined) => {
    if (app && !out.includes(app)) out.push(app);
  };
  for (const id of agent.toolsets ?? []) add(id in TOOLSET_APP ? TOOLSET_APP[id] : null);
  for (const tool of agent.tools ?? []) add(toolApp(tool.name));
  return out;
}
