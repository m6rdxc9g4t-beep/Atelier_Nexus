"""Fichiers joints à la conversation, mis à la disposition des outils (`env.conversation_files()`).

Un outil qui doit envoyer un fichier à une application (jeu de données vers Atelier Viz, relevé
vers Atelier Convert…) le retrouve ici par son nom ou son identifiant.

Garde-fou : seuls les fichiers **cités par les messages de la conversation en cours** sont
accessibles (identifiants calculés par la couche API avec `referenced_ids`). Un outil ne peut
donc jamais lire la pièce jointe d'une autre conversation, même s'il en connaît l'identifiant.
Hors conversation (workflows, déclencheurs), la liste est vide.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Protocol

from app.schemas.attachments import AttachmentInfo
from app.tools.http import AppError


class FilesError(AppError):
    """Fichier absent, ambigu ou illisible : message clair au modèle."""

    def __init__(self, message: str) -> None:
        super().__init__(message, app="fichiers")


class AttachmentStore(Protocol):
    async def get(self, attachment_id: str) -> tuple[AttachmentInfo, bytes] | None: ...


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


class ConversationFiles:
    """Accès en lecture aux fichiers d'UNE conversation (créé par la couche API)."""

    def __init__(self, store: AttachmentStore | None, ids: Sequence[str]) -> None:
        self._store = store
        self._ids = list(dict.fromkeys(ids))
        self._loaded: dict[str, tuple[AttachmentInfo, bytes]] = {}

    async def _load_all(self) -> list[tuple[AttachmentInfo, bytes]]:
        if self._store is None:
            return []
        for attachment_id in self._ids:
            if attachment_id not in self._loaded:
                found = await self._store.get(attachment_id)
                if found is not None:
                    self._loaded[attachment_id] = found
        return [self._loaded[i] for i in self._ids if i in self._loaded]

    async def list(self) -> list[AttachmentInfo]:
        return [info for info, _ in await self._load_all()]

    async def load(self, ref: str) -> tuple[AttachmentInfo, bytes]:
        """Fichier désigné par son identifiant ou son nom (casse, accents et extension ignorés)."""
        items = await self._load_all()
        if not items:
            raise FilesError(
                "Aucun fichier n'est joint à cette conversation : demandez à l'utilisateur de "
                "glisser le fichier dans le chat."
            )
        for info, data in items:
            if info.id == ref:
                return info, data
        wanted = _norm(ref)
        matches = [(i, d) for i, d in items if _norm(i.name) == wanted]
        if not matches:  # nom sans extension (« ventes » pour « ventes.csv »)
            matches = [(i, d) for i, d in items if _norm(i.name).rsplit(".", 1)[0] == wanted]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise FilesError(
                f"Plusieurs fichiers s'appellent « {ref} » : utilisez leur identifiant."
            )
        names = ", ".join(f"« {i.name} »" for i, _ in items)
        raise FilesError(f"Fichier « {ref} » introuvable. Fichiers joints : {names}.")
