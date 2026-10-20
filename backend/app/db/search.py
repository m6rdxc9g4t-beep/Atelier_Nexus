"""Recherche dans l'historique : texte normalisé (minuscules, sans accents) des conversations.

`search_text` (colonne de `conversations`) réunit le titre, les messages de l'utilisateur et
de l'agent, et le titre et le contenu des artefacts. Les résultats d'outils n'y sont pas :
ils sont volumineux et souvent bruts. Fonctions pures, testées.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

MAX_SEARCH_TEXT = 200_000
SNIPPET = 160
#: Contexte gardé avant le mot trouvé (court : l'extrait s'affiche sur deux lignes)
LEAD = 40


def normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", plain.lower()).strip()


def message_texts(history: Iterable[dict[str, Any]]) -> list[str]:
    """Textes lisibles d'un historique au format neutre (sans résultats d'outils)."""
    out: list[str] = []
    for message in history:
        for block in message.get("content", []) if isinstance(message, dict) else []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                out.append(str(block["text"]))
    return out


def search_text(
    title: str, history: Iterable[dict[str, Any]], artifacts: Iterable[tuple[str, str]]
) -> str:
    parts = [title, *message_texts(history)]
    for art_title, content in artifacts:
        parts += [art_title, content[:20_000]]
    return normalize("\n".join(p for p in parts if p))[:MAX_SEARCH_TEXT]


def terms(query: str) -> list[str]:
    """Mots de la recherche (2 caractères au moins), normalisés, sans doublon, 8 au plus."""
    seen: list[str] = []
    for word in normalize(query).split():
        if len(word) >= 2 and word not in seen:
            seen.append(word)
    return seen[:8]


def like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def snippet(texts: Iterable[str], words: list[str]) -> str | None:
    """Extrait autour de la première occurrence, dans le texte d'origine (accents compris)."""
    for text in texts:
        flat = re.sub(r"\s+", " ", text).strip()
        norm = normalize(flat)
        # La normalisation garde la même longueur pour le français courant (accents retirés)
        positions = [norm.find(w) for w in words if w in norm]
        if not positions or len(norm) != len(flat):
            if positions:
                return flat[: SNIPPET * 2] + ("…" if len(flat) > SNIPPET * 2 else "")
            continue
        at = min(positions)
        start = max(0, at - LEAD)
        if start:  # commencer sur un début de mot
            space = flat.find(" ", start, at)
            start = space + 1 if space != -1 else start
        end = min(len(flat), start + SNIPPET + LEAD)
        if end < len(flat):
            space = flat.rfind(" ", at, end)
            end = space if space != -1 else end
        return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")
    return None
