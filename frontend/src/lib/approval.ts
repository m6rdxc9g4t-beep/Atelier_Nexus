/**
 * Validation des actions (réglage APPROVAL_MODE) : lecture du réglage et textes de l'interface
 * qui en dépendent. Logique pure, testée dans approval.test.ts.
 *
 * `every_step` (défaut, choix de l'utilisateur) : toute action d'agent ou étape de workflow,
 * lectures comprises, attend « Autoriser ». `writes_only` : seulement les écritures.
 */

import type { ApprovalMode, CallKind, SettingsView } from "@/types/api";

export const APPROVAL_MODE_KEY = "APPROVAL_MODE";

/** Défaut du serveur, et le plus prudent quand le réglage n'a pas pu être lu. */
export const DEFAULT_APPROVAL_MODE: ApprovalMode = "every_step";

/** Mode effectif d'après la vue des réglages (valeur inconnue ou absente : chaque action). */
export function approvalModeOf(view: SettingsView | null | undefined): ApprovalMode {
  const field = view?.fields.find((f) => f.key === APPROVAL_MODE_KEY);
  return field?.value === "writes_only" ? "writes_only" : DEFAULT_APPROVAL_MODE;
}

/** Libellés des choix dans Réglages. */
export const APPROVAL_CHOICES: Record<ApprovalMode, { label: string; help: string }> = {
  every_step: {
    label: "Chaque action (recommandé)",
    help: "Chaque action d'un agent et chaque étape d'un workflow, lectures comprises, attend « Autoriser » : vous voyez tout avant que ça s'exécute.",
  },
  writes_only: {
    label: "Seulement les écritures",
    help: "Les lectures s'exécutent seules ; seules les actions qui modifient des données attendent « Autoriser ».",
  },
};

/** Badge d'un appel d'agent sur sa carte de validation. */
export const CALL_KIND_LABEL: Record<CallKind, string> = {
  read: "Lecture",
  write: "Écriture",
  delegation: "Délégation",
};

/** Nature d'un appel ; les tours enregistrés avant ce réglage ne demandaient que des écritures. */
export const callKind = (kind: CallKind | undefined): CallKind => kind ?? "write";

/** Rappel des déclencheurs : « … dans À valider : … » (le nom de la boîte est mis en valeur). */
export function triggerReminder(mode: ApprovalMode): { lead: string; tail: string } {
  return mode === "every_step"
    ? { lead: "Chaque étape attendra votre validation dans", tail: " : rien ne s'exécute sans vous." }
    : { lead: "Les étapes qui écrivent attendront votre validation dans", tail: " : rien n'est modifié sans vous." };
}

/** Textes de la boîte « À valider ». */
export function inboxTexts(mode: ApprovalMode): { title: string; description: string; empty: string } {
  return mode === "every_step"
    ? {
        title: "À valider : étapes des workflows en attente de votre accord",
        description:
          "Les workflows s'arrêtent avant chaque étape, même lancés tout seuls. Vérifiez le résultat de l'étape précédente et l'entrée résolue, puis autorisez ou refusez : la suite reprend aussitôt.",
        empty: "Aucune étape n'attend votre accord. Les workflows lancés par un horaire ou un événement s'arrêteront ici avant chaque étape.",
      }
    : {
        title: "À valider : écritures des workflows en attente de votre accord",
        description:
          "Les workflows s'arrêtent avant chaque écriture, même lancés tout seuls. Vérifiez l'entrée résolue, puis autorisez ou refusez : la suite reprend aussitôt.",
        empty: "Aucune écriture n'attend votre accord. Les workflows lancés par un horaire ou un événement s'arrêteront ici avant d'écrire.",
      };
}

/** Message après une décision dans « À valider ». */
export function decisionText(allow: boolean, stillWaiting: boolean): string {
  if (!allow) return "Refusé : l'exécution est arrêtée, rien de plus n'a été exécuté.";
  return stillWaiting ? "Autorisé : l'étape suivante attend votre validation." : "Autorisé : le workflow a repris.";
}

/** Phrase des éditeurs (agent, workflow) : ce qui demandera une validation. */
export const approvalPromise = (mode: ApprovalMode): string =>
  mode === "every_step"
    ? "Chaque action, lectures comprises, demandera votre validation."
    : "Les actions qui modifient des données demanderont toujours votre validation.";
