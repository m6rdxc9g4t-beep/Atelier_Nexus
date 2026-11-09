import type { ExampleStep, ExampleStory } from "@/types/api";

/**
 * Exemples de la suite : histoire choisie mémorisée sur l'appareil, clé commune aux applications
 * de la suite servies depuis la même origine (atelier-exemples/1).
 */
export const EXAMPLE_STORAGE_KEY = "atelier:exemple";
export const THIS_APP = "nexus";

export const APP_LABELS: Record<string, string> = {
  convert: "Convert",
  tab: "Tab",
  viz: "Viz",
  tresorerie: "Trésorerie",
  nexus: "Nexus",
  projets: "Projets",
  wiki: "Wiki",
};

export function readRemembered(): string | null {
  try {
    return window.localStorage.getItem(EXAMPLE_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function remember(id: string): void {
  try {
    window.localStorage.setItem(EXAMPLE_STORAGE_KEY, id);
  } catch {
    // stockage indisponible : le choix n'est simplement pas gardé
  }
}

/** Histoire retenue : celle mémorisée si elle existe encore, sinon la première. */
export function pickStory(stories: ExampleStory[], remembered: string | null): ExampleStory | undefined {
  return stories.find((s) => s.id === remembered) ?? stories[0];
}

/** Étape de cette application dans le parcours, et la suivante. */
export function stepsAround(story: ExampleStory, app: string = THIS_APP): { current?: ExampleStep; next?: ExampleStep } {
  const index = story.parcours.findIndex((e) => e.app === app);
  if (index < 0) return {};
  return { current: story.parcours[index], next: story.parcours[index + 1] };
}
