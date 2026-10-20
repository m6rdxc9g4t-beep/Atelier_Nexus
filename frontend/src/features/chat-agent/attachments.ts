/**
 * Pièces jointes côté interface : formats acceptés, contrôles avant envoi, libellés.
 * Fonctions pures (testées dans attachments.test.ts) ; la préparation des fichiers (texte
 * extrait, image réduite) est faite par le serveur (backend/app/attachments/processing.py).
 */

import type { AttachmentBlock, AttachmentInfo } from "@/types/api";

export const MAX_FILES = 10;
export const MAX_BYTES = 20 * 1024 * 1024;

const IMAGES = ["png", "jpg", "jpeg", "gif", "webp"];
const DOCUMENTS = [
  "pdf", "docx", "xlsx", "xlsm", "csv", "tsv", "txt", "md", "markdown", "json", "xml", "html", "htm",
  "yaml", "yml", "toml", "ini", "log", "sql", "dax", "m", "pq", "py", "js", "jsx", "ts", "tsx", "css",
  "sh", "r", "java", "c", "cpp", "cs", "go", "rs", "swift", "kt", "php", "rb", "vue", "svg",
]; // prettier-ignore

/** Attribut `accept` du sélecteur de fichiers. */
export const ACCEPT = [...IMAGES, ...DOCUMENTS].map((e) => `.${e}`).join(",");

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** Contrôle immédiat (le serveur refait tous les contrôles) ; null = fichier accepté. */
export function precheck(file: Pick<File, "name" | "size">): string | null {
  const ext = extensionOf(file.name);
  if (file.size === 0) return "Fichier vide.";
  if (file.size > MAX_BYTES) return `Plus de ${MAX_BYTES / (1024 * 1024)} Mo : joignez un extrait.`;
  if (ext === "heic" || ext === "heif") return "Photo HEIC : exportez-la en JPEG avant de la joindre.";
  if (["doc", "xls", "ppt", "pptx", "pages", "numbers", "key"].includes(ext))
    return `Format .${ext} non lu : enregistrez-le en PDF, .docx ou .xlsx.`;
  if (!IMAGES.includes(ext) && !DOCUMENTS.includes(ext))
    return "Format non pris en charge : images, PDF, Word, Excel, CSV, texte ou code.";
  return null;
}

/** Une capture collée s'appelle « image.png » : on lui donne un nom parlant. */
export function pastedName(file: Pick<File, "name" | "type">, now = new Date()): string {
  if (file.name && file.name !== "image.png") return file.name;
  const ext = file.type === "image/jpeg" ? "jpg" : (file.type.split("/")[1] ?? "png");
  const pad = (n: number) => String(n).padStart(2, "0");
  return `capture-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.${ext}`;
}

export function isImageName(name: string): boolean {
  return IMAGES.includes(extensionOf(name));
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
}

/** « 3 pages », « 2 feuilles », « 1 568 × 882 » ; sinon la taille. */
export function describe(info: Pick<AttachmentInfo, "kind" | "size" | "meta">): string {
  const { meta } = info;
  const plural = (n: number, word: string) => `${n.toLocaleString("fr-FR")} ${word}${n > 1 ? "s" : ""}`;
  if (meta.pages) return plural(meta.pages, "page");
  if (meta.sheets?.length) return plural(meta.sheets.length, "feuille");
  if (meta.rows) return plural(meta.rows, "ligne");
  if (info.kind === "image" && meta.width && meta.height)
    return `${meta.width.toLocaleString("fr-FR")} × ${meta.height.toLocaleString("fr-FR")}`;
  return formatSize(info.size);
}

export function toBlock(info: AttachmentInfo): AttachmentBlock {
  return {
    type: "attachment",
    id: info.id,
    name: info.name,
    media_type: info.media_type,
    kind: info.kind,
    size: info.size,
  };
}

/** Icône selon le type : tableur, code, texte. */
export function fileFamily(name: string, mediaType: string): "sheet" | "code" | "text" | "image" {
  const ext = extensionOf(name);
  if (mediaType.startsWith("image/") && ext !== "svg") return "image";
  if (["xlsx", "xlsm", "csv", "tsv"].includes(ext)) return "sheet";
  if (["pdf", "docx", "txt", "md", "markdown", "log"].includes(ext)) return "text";
  return "code";
}
