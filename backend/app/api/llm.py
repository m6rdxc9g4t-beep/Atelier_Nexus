"""Endpoints de supervision du routeur LLM."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.llm import LLMRouter, ProviderStatus, get_llm_router

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/providers", response_model=list[ProviderStatus])
async def list_providers(
    llm: Annotated[LLMRouter, Depends(get_llm_router)],
) -> list[ProviderStatus]:
    """État de chaque provider : configuré, joignable, modèles disponibles."""
    return await llm.status()
