/**
 * Sortie de l'éditeur en graphe : simple fermeture (retour à la fenêtre d'origine), ou passage aux
 * modèles de la suite (« Partir d'un modèle de la suite » du canevas vide). La confirmation des
 * modifications non enregistrées est demandée avant, par la fenêtre de l'éditeur. Logique pure
 * sur les actions du store, testée dans leave.test.ts.
 */

/** Où mène la sortie de l'éditeur. */
export type EditorExit = "close" | "templates";

/**
 * Ferme l'éditeur ; pour les modèles, ouvre ensuite le Studio sur « Modèles de la suite » (sans
 * agent suivi) : choisir un modèle rouvre l'éditeur sur un brouillon prérempli, et le Studio
 * redevient la fenêtre de retour.
 */
export function leaveEditor(store: { closeEditor: () => void; openTemplates: () => void }, to: EditorExit): void {
  store.closeEditor();
  if (to === "templates") store.openTemplates();
}
