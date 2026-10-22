/**
 * Mode pas à pas (revue de chaque résultat), retenu dans ce navigateur. Activé par défaut :
 * c'est le choix de l'utilisateur ; on le désactive pour une question rapide. Il ne touche pas
 * à la validation des actions (réglage APPROVAL_MODE, côté serveur).
 */

const KEY = "nexus.stepMode";

export function loadStepMode(): boolean {
  try {
    return localStorage.getItem(KEY) !== "off";
  } catch {
    return true; // stockage indisponible : le plus prudent
  }
}

export function saveStepMode(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // sans stockage, le choix vaut pour la session
  }
}
