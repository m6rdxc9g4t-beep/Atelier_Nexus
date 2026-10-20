/** Mise en évidence des mots recherchés, sans tenir compte des accents ni de la casse
 * (même règle que la recherche côté serveur, app/db/search.py). */

export interface Segment {
  text: string;
  match: boolean;
}

/** Forme comparable d'un caractère : minuscule, sans accent. */
function fold(char: string): string {
  return char.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

/** Mots de la recherche (2 caractères au moins), comme `terms()` côté serveur. */
export function searchTerms(query: string): string[] {
  const words = [...query]
    .map(fold)
    .join("")
    .split(/\s+/)
    .filter((w) => w.length >= 2);
  return [...new Set(words)].slice(0, 8);
}

/** Découpe `text` en segments, les occurrences des mots de `query` marquées `match`. */
export function highlight(text: string, query: string): Segment[] {
  const words = searchTerms(query);
  if (!words.length || !text) return text ? [{ text, match: false }] : [];
  // Texte replié + position d'origine de chaque caractère replié
  let folded = "";
  const origin: number[] = [];
  let offset = 0;
  for (const char of text) {
    const f = fold(char);
    for (let i = 0; i < f.length; i++) origin.push(offset);
    folded += f;
    offset += char.length;
  }
  origin.push(text.length);
  const marked = new Array<boolean>(text.length).fill(false);
  for (const word of words) {
    for (let at = folded.indexOf(word); at !== -1; at = folded.indexOf(word, at + word.length)) {
      const start = origin[at] ?? 0;
      const end = origin[at + word.length] ?? text.length;
      for (let i = start; i < end; i++) marked[i] = true;
    }
  }
  const segments: Segment[] = [];
  for (let i = 0; i < text.length; i++) {
    const match = marked[i] ?? false;
    const last = segments[segments.length - 1];
    if (last && last.match === match) last.text += text[i];
    else segments.push({ text: text[i] ?? "", match });
  }
  return segments;
}
