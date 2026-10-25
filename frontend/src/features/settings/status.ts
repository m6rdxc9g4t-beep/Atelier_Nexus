/**
 * Navigation des Réglages, sans React (testée dans status.test.ts) : rubriques (Apparence, puis
 * les groupes du serveur), état de chaque rubrique d'après les moteurs (`api.providers()`) et les
 * applications (`api.appsStatus()`), modifications en attente et erreurs par rubrique.
 */

import type { DotStatus } from "@/components/ui/status-dot";
import { PROVIDER_LABEL } from "@/lib/labels";
import type { AppStatus, ProviderStatus, SettingsGroup, SettingsView } from "@/types/api";

/** Rubrique : « Apparence » (préférence de cet appareil) ou un groupe de champs du serveur. */
export type Section = "Apparence" | SettingsGroup;

export interface Check {
  providers: ProviderStatus[];
  apps: AppStatus[];
}

/** Ligne d'état d'un moteur ou d'une application, affichée en tête de sa rubrique. */
export interface CheckLine {
  id: string;
  label: string;
  ok: boolean;
  /** Configuré mais injoignable (≠ pas configuré du tout) */
  down: boolean;
  detail: string;
}

export interface SectionStatus {
  status: DotStatus;
  /** Sens de la pastille, en toutes lettres (la couleur n'est jamais seule porteuse de sens) */
  label: string;
}

/** Titre affiché d'une rubrique (« Modèles » : le groupe du serveur règle les moteurs d'IA). */
export const SECTION_TITLE: Record<Section, string> = {
  Apparence: "Apparence",
  "Validation des actions": "Validation des actions",
  Modèles: "Moteurs d'IA",
  "Applications Atelier": "Applications Atelier",
  "Atelier Cuisine": "Atelier Cuisine",
  GitHub: "GitHub",
};

/** Applications vérifiées dans leur propre rubrique ; les autres vont dans « Applications Atelier ». */
const OWN_APP: Partial<Record<SettingsGroup, string>> = { "Atelier Cuisine": "cuisine", GitHub: "github" };

/** Rubrique qui a une pastille d'état (moteurs ou applications à joindre). */
export function hasStatus(section: Section): boolean {
  return section !== "Apparence" && section !== "Validation des actions";
}

/** Rubriques dans l'ordre : Apparence, puis les groupes du serveur qui ont des champs. */
export function sections(groups: SettingsGroup[]): Section[] {
  return ["Apparence", ...groups];
}

function appsOf(section: Section, apps: AppStatus[]): AppStatus[] {
  if (section === "Applications Atelier") {
    const own = new Set(Object.values(OWN_APP));
    return apps.filter((a) => !own.has(a.id));
  }
  const id = section === "Apparence" ? undefined : OWN_APP[section];
  return id ? apps.filter((a) => a.id === id) : [];
}

/**
 * Lignes d'état d'une rubrique : chaque moteur (configuré ou non) pour « Modèles », chaque
 * application configurée pour les autres ; aucune pour Apparence et Validation des actions.
 */
export function checkLines(section: Section, check: Check): CheckLine[] {
  if (section === "Modèles") {
    return check.providers.map((p) => ({
      id: p.name,
      label: PROVIDER_LABEL[p.name] ?? p.name,
      ok: p.configured && p.available,
      down: p.configured && !p.available,
      detail: !p.configured
        ? "non configuré"
        : p.available
          ? `${p.is_default ? "moteur par défaut, " : ""}${p.default_model}`
          : (p.error ?? "injoignable"),
    }));
  }
  return appsOf(section, check.apps)
    .filter((a) => a.configured)
    .map((a) => ({
      id: a.id,
      label: a.label,
      ok: a.available,
      down: !a.available,
      detail: a.available ? (a.detail ?? "joignable") : (a.error ?? "injoignable"),
    }));
}

/**
 * Pastille d'une rubrique : verte si tout ce qui est configuré répond, orange si une partie
 * seulement, rouge si rien ne répond, grise si rien n'est configuré. Null : rubrique sans état
 * (Apparence, Validation des actions) ; `pending` pendant la vérification.
 */
export function sectionStatus(section: Section, check: Check | null, checking: boolean): SectionStatus | null {
  if (!hasStatus(section)) return null;
  if (checking) return { status: "pending", label: "Vérification…" };
  if (!check) return null;
  const configured = checkLines(section, check).filter((l) => l.ok || l.down);
  const up = configured.filter((l) => l.ok).length;
  const total = configured.length;
  if (total === 0) return { status: "off", label: "Non configuré" };
  if (total === 1) return up ? { status: "up", label: "Joignable" } : { status: "down", label: "Injoignable" };
  const label = `${up} sur ${total} joignable${up >= 2 ? "s" : ""}`;
  if (up === total) return { status: "up", label };
  return { status: up === 0 ? "down" : "warning", label };
}

/** Nombre de clés (changements en attente, erreurs) par rubrique. */
export function countBySection(view: SettingsView, keys: string[]): Partial<Record<Section, number>> {
  const out: Partial<Record<Section, number>> = {};
  for (const key of keys) {
    const group = view.fields.find((f) => f.key === key)?.group;
    if (group) out[group] = (out[group] ?? 0) + 1;
  }
  return out;
}

/** Première rubrique (dans l'ordre affiché) qui contient l'une des clés, ou null. */
export function firstSectionWith(view: SettingsView, order: Section[], keys: string[]): Section | null {
  const counts = countBySection(view, keys);
  return order.find((s) => (counts[s] ?? 0) > 0) ?? null;
}

/** Premier champ de la rubrique (dans l'ordre du serveur) qui porte l'une des clés, ou null. */
export function firstFieldWith(view: SettingsView, section: Section, keys: string[]): string | null {
  return view.fields.find((f) => f.group === section && keys.includes(f.key))?.key ?? null;
}

/** « 1 modification non enregistrée », « 3 modifications non enregistrées » ; vide à 0. */
export function pendingLabel(count: number): string {
  if (count <= 0) return "";
  return count === 1 ? "1 modification non enregistrée" : `${count} modifications non enregistrées`;
}
