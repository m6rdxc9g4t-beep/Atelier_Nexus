"""Contrat commun des fournisseurs LLM."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import ClassVar

from app.core.llm.types import LLMRequest, LLMResponse, LLMStreamEvent, ProviderName


class LLMProvider(ABC):
    name: ClassVar[ProviderName]

    def __init__(self, default_model: str) -> None:
        self.default_model = default_model

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Le provider a-t-il ce qu'il faut pour être appelé (clé, URL) ?"""

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Appel non streamé."""

    @abstractmethod
    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        """Émet des `TextDelta` puis exactement un `ResponseComplete`."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Modèles disponibles ; lève `ProviderUnavailableError` si injoignable."""

    def resolve_model(self, request: LLMRequest) -> str:
        return request.model or self.default_model
