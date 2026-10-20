/**
 * Pont avec l'application de bureau macOS (pywebview, backend/app/desktop.py).
 * Dans la fenêtre native, `a.download` et `window.open` sont ignorés par WKWebView :
 * tout enregistrement passe par `saveFile` et tout lien externe par `openExternal`.
 */

interface DesktopBridge {
  save_file(name: string, dataBase64: string): Promise<{ saved: string | null; error?: string }>;
  open_external(url: string): Promise<boolean>;
}

export type SaveOutcome = { kind: "saved"; path: string } | { kind: "downloaded" } | { kind: "cancelled" };

function desktopBridge(): DesktopBridge | null {
  if (typeof window === "undefined") return null;
  const api = (window as unknown as { pywebview?: { api?: Partial<DesktopBridge> } }).pywebview?.api;
  return api?.save_file && api.open_external ? (api as DesktopBridge) : null;
}

/** Vrai dans l'application de bureau. */
export const isDesktop = (): boolean => desktopBridge() !== null;

/** Texte → base64 (UTF-8), pour le pont. */
export function textToBase64(text: string): string {
  return bytesToBase64(new TextEncoder().encode(text));
}

/** Enregistre un fichier texte : boîte « Enregistrer sous » native, sinon téléchargement. */
export async function saveFile(name: string, text: string, type: string): Promise<SaveOutcome> {
  const bridge = desktopBridge();
  if (bridge) {
    const res = await bridge.save_file(name, textToBase64(text));
    if (res.error) throw new Error(res.error);
    return res.saved ? { kind: "saved", path: res.saved } : { kind: "cancelled" };
  }
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
  return { kind: "downloaded" };
}

/** Octets → base64, pour le pont. */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

/** Enregistre un fichier binaire (pièce jointe) : « Enregistrer sous » natif, sinon téléchargement. */
export async function saveBlob(name: string, blob: Blob): Promise<SaveOutcome> {
  const bridge = desktopBridge();
  if (bridge) {
    const res = await bridge.save_file(name, bytesToBase64(new Uint8Array(await blob.arrayBuffer())));
    if (res.error) throw new Error(res.error);
    return res.saved ? { kind: "saved", path: res.saved } : { kind: "cancelled" };
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
  return { kind: "downloaded" };
}

/** Ouvre un lien dans le navigateur (ou l'app de la suite installée, dans l'application de bureau). */
export function openExternal(url: string): void {
  const bridge = desktopBridge();
  if (bridge) void bridge.open_external(url);
  else window.open(url, "_blank", "noopener,noreferrer");
}
