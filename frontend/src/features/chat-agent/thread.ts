/**
 * Logique pure de l'affichage du fil : appels d'outils regroupés en lignes d'activité, état de
 * chaque action, paramètres lisibles par un humain, annonces pour les lecteurs d'écran.
 * Sans React ni réseau, donc testable (thread.test.ts).
 */

import { toolApp } from "./agentApps";
import type { ApprovalPart, ArtifactRefPart, AttachmentPart, Part, TextPart, ToolCallPart } from "./conversation";

/** Résultat d'un appel refusé : même texte que REFUSED (backend/app/agents/base.py). Sert aux
 * conversations rouvertes, où la décision elle-même n'est pas enregistrée. */
const REFUSED_PREFIX = "L'utilisateur a refusé cette action";

/** `queued` : autorisée, pas encore lancée ; `interrupted` : autorisée, jamais lancée (réponse
 * arrêtée ou en échec avant elle) ; `refused` : refusée sur la carte de validation. */
export type ActionStatus = "queued" | "running" | "done" | "error" | "refused" | "interrupted";

/** Une action du fil : l'appel d'outil, et sa validation quand il en a eu une. */
export interface ActivityEntry {
  id: string;
  name: string;
  input: Record<string, unknown>;
  /** Résumé lisible de la carte de validation */
  summary?: string;
  /** Décision prise sur la carte (absente : pas de validation demandée, ou conversation rouverte) */
  decision?: boolean;
  status: ActionStatus;
  result?: string;
}

/** Morceau affiché d'un tour : une ligne d'activité (appels consécutifs) ou une partie seule. */
export type Segment =
  | { kind: "activity"; key: string; entries: ActivityEntry[] }
  | { kind: "text"; key: string; part: TextPart }
  | { kind: "approval"; key: string; part: ApprovalPart }
  | { kind: "artifact"; key: string; part: ArtifactRefPart }
  | { kind: "attachment"; key: string; part: AttachmentPart };

type Groupable = ToolCallPart | ApprovalPart;

/** Appel d'outil, ou validation déjà envoyée (pas un prédicat de type : une validation en
 * attente a le même type et reste seule). */
const groupable = (part: Part): boolean => part.kind === "tool" || (part.kind === "approval" && part.submitted);

/** Ce qui coupe une ligne d'activité : texte non vide, validation en attente, livrable, fichier. */
const breaksRun = (part: Part): boolean => !groupable(part) && !(part.kind === "text" && !part.text.trim());

/** Résumé et décision d'un appel, pris sur sa carte de validation envoyée. */
type Decided = { summary: string; decision?: boolean };

/**
 * Regroupe les appels d'outils consécutifs en une ligne d'activité. Une validation déjà envoyée
 * rejoint l'activité (sa décision s'affiche sur l'action, comme un reçu) ; une validation en
 * attente reste seule, en carte. Un texte vide entre deux appels ne coupe pas le groupe.
 * Chaque action n'apparaît qu'une fois : là où son appel s'exécute (un livrable publié entre deux
 * appels validés ensemble coupe la ligne : l'appel suivant rejoint la ligne d'après, avec sa
 * décision), sinon sur sa carte tant qu'il attend son tour.
 * `live` : réponse en cours ; sinon, une action autorisée jamais lancée est « non exécutée ».
 * Clés stables : un groupe garde la clé de sa première action quand il s'allonge.
 */
export function groupParts(parts: Part[], { live = false }: { live?: boolean } = {}): Segment[] {
  // Ligne d'activité de chaque partie (nombre de coupures avant elle), appels exécutés et décisions
  const runOf: number[] = [];
  const toolRun = new Map<string, number>();
  const decided = new Map<string, Decided>();
  let breaks = 0;
  parts.forEach((part, index) => {
    runOf[index] = breaks;
    if (part.kind === "tool" && !toolRun.has(part.id)) toolRun.set(part.id, breaks);
    if (part.kind === "approval" && part.submitted) {
      for (const call of part.calls) decided.set(call.id, { summary: call.summary, decision: part.decisions[call.id] });
    }
    if (breaksRun(part)) breaks += 1;
  });

  const out: Segment[] = [];
  const used = new Set<string>();
  // Clé déjà prise (identifiant répété par un moteur) : suffixe, pour ne jamais dupliquer une clé React
  const unique = (key: string, index: number) => {
    const k = used.has(key) ? `${key}-${index}` : key;
    used.add(k);
    return k;
  };
  let run: Groupable[] = [];
  let runIndex = 0;
  const flush = (index: number) => {
    const entries = activityEntries(run, runIndex, toolRun, decided, live);
    if (entries.length) out.push({ kind: "activity", key: unique(`activity-${entries[0]!.id}`, index), entries });
    run = [];
  };
  parts.forEach((part, index) => {
    if (groupable(part)) {
      if (!run.length) runIndex = runOf[index]!;
      run.push(part as Groupable);
      return;
    }
    if (part.kind === "text" && !part.text.trim()) return;
    flush(index);
    if (part.kind === "text") out.push({ kind: "text", key: unique(`text-${index}`, index), part });
    else if (part.kind === "approval")
      out.push({ kind: "approval", key: unique(`approval-${part.calls.map((c) => c.id).join("-")}`, index), part });
    else if (part.kind === "artifact")
      out.push({ kind: "artifact", key: unique(`artifact-${part.artifactId}`, index), part });
    else if (part.kind === "attachment") out.push({ kind: "attachment", key: unique(`attachment-${index}`, index), part });
  });
  flush(parts.length);
  return out;
}

/** Actions d'un groupe, dans l'ordre d'apparition ; la carte et l'appel d'un même id fusionnent.
 * Un appel validé ici mais exécuté dans une autre ligne n'est montré que là-bas. */
function activityEntries(
  run: Groupable[],
  runIndex: number,
  toolRun: Map<string, number>,
  decided: Map<string, Decided>,
  live: boolean,
): ActivityEntry[] {
  type Draft = Omit<ActivityEntry, "status"> & { tool?: ToolCallPart["status"] };
  const byId = new Map<string, Draft>();
  const entry = (id: string, name: string, input: Record<string, unknown>): Draft => {
    let found = byId.get(id);
    if (!found) {
      found = { id, name, input };
      const known = decided.get(id);
      if (known) {
        found.summary = known.summary;
        if (known.decision !== undefined) found.decision = known.decision;
      }
      byId.set(id, found);
    }
    return found;
  };
  for (const part of run) {
    if (part.kind === "approval") {
      for (const call of part.calls) {
        const ran = toolRun.get(call.id);
        if (ran === undefined || ran === runIndex) entry(call.id, call.name, call.input);
      }
    } else {
      const e = entry(part.id, part.name, part.input);
      e.input = part.input;
      e.tool = part.status;
      e.result = part.result;
    }
  }
  return [...byId.values()].map(({ tool, ...e }) => ({ ...e, status: statusOf(e.decision, tool, e.result, live) }));
}

function statusOf(
  decision: boolean | undefined,
  tool: ToolCallPart["status"] | undefined,
  result: string | undefined,
  live: boolean,
): ActionStatus {
  if (decision === false) return "refused";
  if (!tool) return live ? "queued" : "interrupted";
  if (tool === "error" && result?.startsWith(REFUSED_PREFIX)) return "refused";
  return tool;
}

export interface ActivitySummary {
  count: number;
  /** Applications touchées, sans doublon, dans l'ordre des actions */
  apps: string[];
  /** État global : en cours tant qu'une action tourne ; en erreur si une action a échoué ou n'a
   * pas été exécutée ; refusé si toutes l'ont été */
  status: "running" | "error" | "done" | "refused";
  refused: number;
  errors: number;
  /** Autorisées mais jamais lancées (réponse arrêtée ou en échec avant elles) */
  interrupted: number;
  /** Action en cours, nommée sur la ligne repliée */
  current?: ActivityEntry;
}

export function activitySummary(entries: ActivityEntry[]): ActivitySummary {
  const apps: string[] = [];
  for (const e of entries) {
    const app = toolApp(e.name);
    if (app && !apps.includes(app)) apps.push(app);
  }
  const count = entries.length;
  const refused = entries.filter((e) => e.status === "refused").length;
  const errors = entries.filter((e) => e.status === "error").length;
  const interrupted = entries.filter((e) => e.status === "interrupted").length;
  const current = entries.findLast((e) => e.status === "running") ?? entries.find((e) => e.status === "queued");
  const status = current
    ? "running"
    : errors || interrupted
      ? "error"
      : count && refused === count
        ? "refused"
        : "done";
  return { count, apps, status, refused, errors, interrupted, current };
}

// ─── Paramètres lisibles ──────────────────────────────────────────

const pad = (depth: number) => "  ".repeat(depth);

/** Retours à la ligne, y compris ceux qu'un navigateur affiche sans qu'on les voie venir. */
const LINE_BREAK = /\r\n|[\n\r\u2028\u2029]/;

/** Clé telle quelle, ou entre guillemets si elle pourrait se faire passer pour autre chose
 * (retour à la ligne, « : », puce, gouttière, espaces aux bords, clé vide). */
function keyText(key: string): string {
  const odd = !key || key !== key.trim() || LINE_BREAK.test(key) || key.includes(" : ") || /^(- |│)/.test(key);
  return odd ? JSON.stringify(key) : key;
}

/** Valeur qui tient sur la ligne de sa clé, ou null (objet, liste, texte sur plusieurs lignes). */
function inline(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return "(vide)";
  if (typeof value === "string") return LINE_BREAK.test(value) ? null : value;
  if (typeof value === "boolean") return value ? "oui" : "non";
  if (typeof value === "number" || typeof value === "bigint") return String(value);
  if (Array.isArray(value)) return value.length ? null : "(aucun)";
  if (typeof value === "object") return Object.keys(value).length ? null : "(vide)";
  return String(value);
}

/** Lignes d'une valeur composée, indentées. Un texte sur plusieurs lignes garde une gouttière
 * « │ » : aucune de ses lignes ne peut passer pour une autre clé. */
function block(value: unknown, depth: number): string[] {
  if (typeof value === "string") return value.split(LINE_BREAK).map((line) => `${pad(depth)}│ ${line}`);
  if (Array.isArray(value)) return value.flatMap((item) => itemLines(item, depth));
  return Object.entries(value as Record<string, unknown>).flatMap(([key, v]) => entryLines(key, v, depth));
}

function entryLines(key: string, value: unknown, depth: number): string[] {
  const text = inline(value);
  const name = keyText(key);
  return text !== null ? [`${pad(depth)}${name} : ${text}`] : [`${pad(depth)}${name} :`, ...block(value, depth + 1)];
}

function itemLines(item: unknown, depth: number): string[] {
  const text = inline(item);
  if (text !== null) return [`${pad(depth)}- ${text}`];
  if (typeof item === "string") return [`${pad(depth)}-`, ...block(item, depth + 1)];
  const lines = block(item, depth + 1);
  lines[0] = `${pad(depth)}- ${lines[0]!.trimStart()}`;
  return lines;
}

/**
 * Paramètres d'un appel tels qu'un humain les relit avant d'autoriser : « clé : valeur », listes
 * à puces, textes longs (contenu d'un fichier, d'un chapitre, d'une carte) en bloc, tels qu'ils
 * seront écrits. Rien n'est coupé : c'est exactement ce que l'utilisateur autorise. Une entrée
 * qui n'est pas un objet (moteur fautif) est montrée telle quelle.
 */
export function formatParams(input: unknown): string {
  if (input === null || input === undefined) return "(aucun paramètre)";
  if (typeof input !== "object" || Array.isArray(input)) {
    const text = inline(input);
    return text ?? block(input, 0).join("\n");
  }
  return Object.keys(input).length ? block(input, 0).join("\n") : "(aucun paramètre)";
}

// ─── Annonces pour les lecteurs d'écran ───────────────────────────

/** État du fil observé d'un rendu à l'autre : réponse en cours, validation en attente (clé). */
export interface LiveSnapshot {
  streaming: boolean;
  pending: string | null;
  failed: boolean;
}

/** Ce que la région aria-live annonce entre deux états, ou null (rien de neuf). */
export function liveMessage(before: LiveSnapshot, after: LiveSnapshot): string | null {
  if (after.pending && after.pending !== before.pending) return "Validation demandée";
  if (before.streaming && !after.streaming) {
    if (after.failed) return "La réponse a échoué";
    return after.pending ? null : "Réponse terminée";
  }
  return null;
}
