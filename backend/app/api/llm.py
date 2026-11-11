"""Endpoints de supervision du routeur LLM."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.llm import LLMRouter, ProviderStatus, get_llm_router

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/providers", response_model=list[ProviderStatus])
async def list_providers(
    llm: Annotated[LLMRouter, Depends(get_llm_router)],
    refresh: bool = False,
) -> list[ProviderStatus]:
    """État de chaque provider : configuré, joignable, modèles disponibles. Gardé 60 s en
    mémoire (10 s si un moteur est indisponible) ; `refresh=true` le relit (au plus toutes les
    10 s)."""
    return await llm.status(refresh=refresh)
