"""Pièces jointes : import d'un fichier, aperçu / téléchargement, retrait avant envoi.

Le fichier est préparé à l'import (texte extrait, image réduite) puis cité dans les messages
par son identifiant (`{"type": "attachment", "id": …}`) ; son contenu n'est ajouté qu'au
moment d'appeler le modèle."""

from __future__ import annotations

import asyncio
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Path, Response, UploadFile, status

from app.api.deps import get_attachment_repository
from app.api.settings import Guard
from app.attachments.processing import MAX_FILE_BYTES, AttachmentError, process_upload
from app.db.attachments import AttachmentRepository
from app.db.repository import StorageError
from app.schemas.attachments import AttachmentInfo

router = APIRouter(prefix="/api/attachments", tags=["attachments"])
RepoDep = Annotated[AttachmentRepository, Depends(get_attachment_repository)]
AttachmentId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _unavailable(exc: StorageError) -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, f"Pièces jointes indisponibles : {exc}"
    )


@router.post("", response_model=AttachmentInfo, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    _: Guard, repo: RepoDep, file: Annotated[UploadFile, File(description="Fichier à joindre")]
) -> AttachmentInfo:
    """Image (PNG, JPEG, GIF, WebP), PDF, Word .docx, Excel .xlsx, CSV, texte, JSON ou code ;
    20 Mo au plus. 413 trop gros, 415 format non lu, 422 fichier illisible."""
    data = await file.read(MAX_FILE_BYTES + 1)
    try:
        item = await asyncio.to_thread(process_upload, file.filename, data)
    except AttachmentError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    try:
        return await repo.create(item)
    except StorageError as exc:
        raise _unavailable(exc) from exc


@router.get("/{attachment_id}/content")
async def attachment_content(attachment_id: AttachmentId, repo: RepoDep) -> Response:
    """Images : affichées telles quelles. Autres fichiers : toujours en téléchargement, jamais
    interprétés par le navigateur (un .html ou un .svg joint ne s'exécute pas)."""
    try:
        found = await repo.get(attachment_id)
    except StorageError as exc:
        raise _unavailable(exc) from exc
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pièce jointe introuvable.")
    info, data = found
    inline = info.media_type in INLINE
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=info.media_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(info.name)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_attachment(_: Guard, attachment_id: AttachmentId, repo: RepoDep) -> Response:
    """Retire un fichier joint pas encore envoyé (une fois envoyé, il part avec la conversation)."""
    try:
        removed = await repo.delete_unattached(attachment_id)
    except StorageError as exc:
        raise _unavailable(exc) from exc
    if removed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pièce jointe introuvable.")
    if removed is False:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cette pièce jointe a déjà été envoyée : supprimez la conversation pour la retirer.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
