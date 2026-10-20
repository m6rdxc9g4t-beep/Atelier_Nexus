"""Préparation d'un fichier joint (fonctions pures, bloquantes : appeler via asyncio.to_thread).

- Images (PNG, JPEG, GIF, WebP) : vérifiées, réduites à `MAX_IMAGE_SIDE` px de côté et
  réencodées. Le réencodage retire les métadonnées (EXIF : position GPS, appareil…).
- Documents : le texte est extrait une fois pour toutes à l'import —
  PDF (pypdf), Word .docx (python-docx), Excel .xlsx (openpyxl, valeurs calculées),
  CSV / TSV, texte, Markdown, JSON, code, DAX, M, SQL…
Le fichier d'origine est conservé tel quel (sauf les images, gardées réduites).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from app.core.llm.types import AttachmentKind

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_SIDE = 1568  # au-delà, Claude réduit lui-même l'image : autant l'envoyer plus légère
MAX_TEXT_CHARS = 500_000
MAX_SHEET_ROWS = 5_000
MAX_PDF_PAGES = 500

IMAGE_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TEXT_TYPES = {
    "txt": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "json": "application/json",
    "xml": "application/xml",
    "html": "text/html",
    "htm": "text/html",
    "yaml": "text/yaml",
    "yml": "text/yaml",
    "toml": "text/plain",
    "ini": "text/plain",
    "log": "text/plain",
    "sql": "text/x-sql",
    "dax": "text/plain",
    "m": "text/plain",
    "pq": "text/plain",
    "py": "text/x-python",
    "js": "text/javascript",
    "jsx": "text/javascript",
    "ts": "text/x-typescript",
    "tsx": "text/x-typescript",
    "css": "text/css",
    "sh": "text/x-shellscript",
    "r": "text/plain",
    "java": "text/plain",
    "c": "text/plain",
    "cpp": "text/plain",
    "cs": "text/plain",
    "go": "text/plain",
    "rs": "text/plain",
    "swift": "text/plain",
    "kt": "text/plain",
    "php": "text/plain",
    "rb": "text/plain",
    "vue": "text/plain",
    "svg": "image/svg+xml",  # lu comme texte (jamais affiché en image : risque de script)
}
DOCUMENT_TYPES = {"pdf": PDF, "docx": DOCX, "xlsx": XLSX, "xlsm": XLSX, **TEXT_TYPES}

#: Pour le message d'erreur et l'attribut `accept` du sélecteur de fichiers
SUPPORTED = sorted({*IMAGE_TYPES, *DOCUMENT_TYPES})


class AttachmentError(ValueError):
    """Fichier refusé ; `status` = code HTTP à renvoyer."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class ProcessedAttachment:
    name: str
    kind: AttachmentKind
    media_type: str
    data: bytes
    text: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def clean_name(raw: str | None) -> str:
    """Nom de fichier affichable : sans chemin ni caractère de contrôle, 255 caractères au plus."""
    name = PurePath((raw or "").replace("\\", "/")).name
    name = "".join(
        c for c in unicodedata.normalize("NFC", name) if unicodedata.category(c)[0] != "C"
    )
    name = name.strip().strip(".") or "fichier"
    if len(name) > 255:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 250 - len(ext)] + dot + ext) if dot and len(ext) < 10 else name[:255]
    return name


def extension(name: str) -> str:
    return name.rpartition(".")[2].lower() if "." in name else ""


def _truncate(text: str, meta: dict[str, Any]) -> str:
    text = text.replace("\x00", "")
    if len(text) > MAX_TEXT_CHARS:
        meta["truncated"] = (
            f"document très long : seuls les {MAX_TEXT_CHARS:,} premiers caractères ont été gardés".replace(
                ",", " "
            )
        )
        text = text[:MAX_TEXT_CHARS]
    meta["chars"] = len(text)
    return text


def decode_text(data: bytes) -> str:
    """UTF-8 (avec ou sans BOM), sinon UTF-16 avec BOM, sinon Windows-1252 (fichiers Excel FR)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _looks_binary(data: bytes) -> bool:
    sample = data[:4096]
    return b"\x00" in sample and not sample.startswith((b"\xff\xfe", b"\xfe\xff"))


# ─── Images ───────────────────────────────────────────────────────


def process_image(name: str, data: bytes) -> ProcessedAttachment:
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 100_000_000  # bombe de décompression : refusée au-delà
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image: Image.Image = Image.open(io.BytesIO(data))
        fmt = (image.format or "").upper()
        animated = bool(getattr(image, "is_animated", False))
        image = ImageOps.exif_transpose(image)  # photo de téléphone : bon sens de lecture
        image.load()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise AttachmentError(f"« {name} » n'est pas une image lisible ({exc}).") from exc
    if fmt not in {"PNG", "JPEG", "GIF", "WEBP", "MPO"}:
        raise AttachmentError(
            f"Format d'image non pris en charge : {fmt or 'inconnu'} (PNG, JPEG, GIF ou WebP).", 415
        )
    original = image.size
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    if fmt in {"JPEG", "MPO"} or (
        image.mode not in ("RGBA", "LA", "P") and fmt == "WEBP" and not animated
    ):
        image.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        media = "image/jpeg"
    else:
        # PNG / GIF / WebP avec transparence : PNG (première image d'un GIF animé)
        if image.mode not in ("RGB", "RGBA", "L", "LA"):
            image = image.convert("RGBA")
        image.save(out, "PNG", optimize=True)
        media = "image/png"
    meta: dict[str, Any] = {"width": image.width, "height": image.height}
    if image.size != original:
        meta["original_size"] = list(original)
    if animated:
        meta["truncated"] = "image animée : seule la première image est transmise"
    return ProcessedAttachment(
        name=name, kind="image", media_type=media, data=out.getvalue(), meta=meta
    )


# ─── Documents ────────────────────────────────────────────────────


def pdf_text(data: bytes, meta: dict[str, Any]) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise AttachmentError(
                "Ce PDF est protégé par un mot de passe : enregistrez-en une copie sans protection."
            )
        pages = reader.pages
        meta["pages"] = len(pages)
        chunks = []
        for number, page in enumerate(pages[:MAX_PDF_PAGES], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append(f"--- Page {number} ---\n{text}")
    except AttachmentError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise AttachmentError(f"PDF illisible ({exc}).") from exc
    if len(pages) > MAX_PDF_PAGES:
        meta["truncated"] = f"seules les {MAX_PDF_PAGES} premières pages ont été lues"
    if not chunks:
        raise AttachmentError(
            "Ce PDF ne contient pas de texte (document numérisé ?). Joignez plutôt des captures "
            "d'écran de ses pages : elles seront lues comme des images."
        )
    return "\n\n".join(chunks)


def docx_text(data: bytes, meta: dict[str, Any]) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(data))
    except (PackageNotFoundError, ValueError, KeyError, OSError) as exc:
        raise AttachmentError(f"Document Word illisible ({exc}).") from exc
    lines: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style is not None else "") or ""
        level = re.match(r"(?:Heading|Titre)\s*(\d)", style)
        lines.append(f"{'#' * int(level.group(1))} {text}" if level else text)
    for index, table in enumerate(document.tables, start=1):
        lines.append(f"\nTableau {index} :")
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells))
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\n", " ").strip()


def xlsx_text(data: bytes, meta: dict[str, Any]) -> str:
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, ValueError, KeyError, OSError) as exc:
        raise AttachmentError(f"Classeur Excel illisible ({exc}).") from exc
    sections: list[str] = []
    cut: list[str] = []
    try:
        meta["sheets"] = list(workbook.sheetnames)
        for sheet in workbook.worksheets:
            rows: list[str] = []
            total = 0
            for row in sheet.iter_rows(values_only=True):
                values = [_cell(v) for v in row]
                while values and not values[-1]:
                    values.pop()
                if not values:
                    continue
                total += 1
                if total <= MAX_SHEET_ROWS:
                    rows.append(";".join(values))
            if total > MAX_SHEET_ROWS:
                cut.append(f"« {sheet.title} » : {MAX_SHEET_ROWS} lignes sur {total}")
            body = "\n".join(rows) if rows else "(feuille vide)"
            sections.append(
                f"--- Feuille « {sheet.title} » ({total} lignes, séparateur ;) ---\n{body}"
            )
    finally:
        workbook.close()
    if cut:
        meta["truncated"] = "lignes coupées : " + ", ".join(cut)
    return "\n\n".join(sections)


def delimited_rows(text: str, meta: dict[str, Any]) -> None:
    """CSV : nombre de lignes et séparateur détecté, à titre d'information."""
    try:
        dialect = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t|")
        meta["delimiter"] = dialect.delimiter
    except csv.Error:
        pass
    meta["rows"] = text.count("\n") + (0 if text.endswith("\n") else 1)


def process_document(name: str, data: bytes, ext: str) -> ProcessedAttachment:
    meta: dict[str, Any] = {}
    media = DOCUMENT_TYPES[ext]
    if media == PDF:
        if not data.startswith(b"%PDF"):
            raise AttachmentError(f"« {name} » n'est pas un PDF valide.")
        text = pdf_text(data, meta)
    elif media == DOCX:
        text = docx_text(data, meta)
    elif media == XLSX:
        text = xlsx_text(data, meta)
    else:
        if _looks_binary(data):
            raise AttachmentError(f"« {name} » ne contient pas de texte lisible.")
        text = decode_text(data)
        if ext in ("csv", "tsv"):
            delimited_rows(text, meta)
    text = _truncate(text, meta)
    if not text.strip():
        raise AttachmentError(f"« {name} » est vide.")
    return ProcessedAttachment(
        name=name, kind="document", media_type=media, data=data, text=text, meta=meta
    )


def process_upload(raw_name: str | None, data: bytes) -> ProcessedAttachment:
    """Fichier envoyé par l'interface → pièce jointe prête à enregistrer (ou AttachmentError)."""
    name = clean_name(raw_name)
    if not data:
        raise AttachmentError(f"« {name} » est vide.")
    if len(data) > MAX_FILE_BYTES:
        raise AttachmentError(
            f"« {name} » dépasse {MAX_FILE_BYTES // (1024 * 1024)} Mo : réduisez-le ou joignez un extrait.",
            413,
        )
    ext = extension(name)
    if ext in IMAGE_TYPES:
        return process_image(name, data)
    if ext in DOCUMENT_TYPES:
        return process_document(name, data, ext)
    if ext in ("heic", "heif"):
        raise AttachmentError(
            "Les photos HEIC ne sont pas lues : exportez-les en JPEG (Aperçu → Fichier → Exporter).",
            415,
        )
    if ext in ("doc", "xls", "ppt", "pptx", "pages", "numbers", "key"):
        raise AttachmentError(
            f"Format .{ext} non lu : enregistrez le fichier en PDF, .docx ou .xlsx, puis joignez-le.",
            415,
        )
    raise AttachmentError(
        f"Type de fichier non pris en charge ({'.' + ext if ext else 'sans extension'}). "
        "Formats lus : images (PNG, JPEG, GIF, WebP), PDF, Word (.docx), Excel (.xlsx), CSV, "
        "texte, Markdown, JSON et code.",
        415,
    )
