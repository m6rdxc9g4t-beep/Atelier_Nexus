/**
 * Suivi d'une exécution v2 (GET /api/workflow-runs/{id}) : statuts lisibles, interrogation,
 * livrables nouveaux à envoyer au panneau Artefacts. Logique pure, testée dans run.test.ts.
 */

import type { Artifact, RunStatus, StepRun, WorkflowRun } from "@/types/api";

import type { StepDisplayStatus } from "./graph";

export const RUN_STATUS: Record<RunStatus, { label: string; variant: "default" | "success" | "destructive" | "warning" | "secondary" }> =
  {
    running: { label: "en cours", variant: "default" },
    awaiting_approval: { label: "validation demandée", variant: "warning" },
    completed: { label: "réussie", variant: "success" },
    failed: { label: "échec", variant: "destructive" },
    stopped: { label: "arrêtée", variant: "warning" },
  };

export const STEP_STATUS_LABEL: Record<StepDisplayStatus, string> = {
  pending: "en attente",
  running: "en cours",
  ok: "réussie",
  error: "en erreur",
  refused: "refusée",
  skipped: "non exécutée",
  awaiting_approval: "à valider",
};

/** Interroger encore ? Seulement tant que le moteur avance (pas en attente de validation). */
export const shouldPoll = (run: WorkflowRun | null | undefined): boolean => run?.status === "running";

/** Délai avant la prochaine interrogation : rapide au début, puis plus espacé (≤ 3 s). */
export const pollDelay = (attempt: number): number => Math.min(500 + attempt * 250, 3000);

/** Clé d'un livrable (une exécution relue plusieurs fois ne l'ajoute qu'une fois). */
export const artifactKey = (runId: string, index: number, artifact: Artifact) =>
  `${runId}#${index}#${artifact.kind}#${artifact.title}`;

/** Livrables pas encore envoyés au panneau Artefacts ; `seen` reçoit leurs clés. */
export function newArtifacts(run: WorkflowRun, seen: Set<string>): Artifact[] {
  const fresh: Artifact[] = [];
  run.artifacts.forEach((artifact, index) => {
    const key = artifactKey(run.id, index, artifact);
    if (seen.has(key)) return;
    seen.add(key);
    fresh.push(artifact);
  });
  return fresh;
}

/** Durée lisible d'une étape (« 1,2 s », « 2 min 5 s »). */
export function duration(start: string | null, end: string | null): string | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

/** Valeurs de lancement : défaut de chaque paramètre, saisie conservée. */
export const launchValues = (
  params: { name: string; default: string }[],
  previous: Record<string, string> = {},
): Record<string, string> => Object.fromEntries(params.map((p) => [p.name, previous[p.name] ?? p.default]));

/** Étapes dont le résultat se montre au-dessus de la validation suivante. */
const DONE_STATUSES = new Set<StepRun["status"]>(["ok", "error"]);

/**
 * Dernière étape exécutée (réussie ou en erreur) avant l'étape en attente, dans l'ordre
 * d'exécution : son résultat est affiché juste au-dessus de la carte de validation.
 */
export function previousStep(run: WorkflowRun, stepId: string): StepRun | null {
  const index = run.steps.findIndex((s) => s.id === stepId);
  const before = index < 0 ? [] : run.steps.slice(0, index);
  return before.findLast((s) => DONE_STATUSES.has(s.status)) ?? null;
}

/** Texte court d'un résultat d'étape (le détail complet reste dans la liste des étapes). */
export function resultExcerpt(step: StepRun, max = 600): string {
  const text = step.content.trim() || (step.data === null || step.data === undefined ? "" : JSON.stringify(step.data));
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
