"""LLMRouter — point d'entrée UNIQUE des agents vers les LLM.

Les agents ne connaissent ni `anthropic` ni `ollama` : ils envoient un `LLMRequest`
neutre et choisissent éventuellement un provider. Le routeur :
  1. résout le provider (demandé, sinon celui par défaut) ;
  2. relaie l'appel (complet ou streamé) ;
  3. bascule vers le provider de secours en cas de panne transitoire,
     uniquement si rien n'a encore été émis vers le client.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from functools import lru_cache

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.llm.errors import ProviderNotConfiguredError, ProviderUnavailableError
from app.core.llm.providers import AnthropicProvider, LLMProvider, OllamaProvider
from app.core.llm.providers.claude_code_provider import ClaudeCodeProvider, find_claude_binary
from app.core.llm.types import LLMRequest, LLMResponse, LLMStreamEvent, ProviderName

logger = logging.getLogger(__name__)

#: État des moteurs gardé en mémoire (contrat de la suite, SUITE.md §5.3) : l'interface le relit
#: toutes les 30 s, et le sonder lance un `claude auth status` ou un appel à l'API d'Anthropic
STATUS_TTL = 60.0
#: Un moteur indisponible est resondé plus vite (Ollama qu'on vient de lancer), et une
#: vérification demandée (`refresh`) ne relance rien avant ce délai
STATUS_RETRY = 10.0


class ProviderStatus(BaseModel):
    name: ProviderName
    configured: bool
    available: bool
    is_default: bool
    is_fallback: bool
    default_model: str
    models: list[str]
    error: str | None = None


class LLMRouter:
    def __init__(
        self,
        providers: Mapping[ProviderName, LLMProvider],
        *,
        default: ProviderName,
        fallback: ProviderName | None = None,
    ) -> None:
        if default not in providers:
            raise ValueError(f"Provider par défaut inconnu : {default}")
        self._providers = dict(providers)
        self.default = default
        self.fallback = fallback if fallback != default else None
        #: Dernier état lu : (instant de lecture, expiration, états) ; un routeur recréé
        #: (réglages enregistrés) repart sans cache
        self._status: tuple[float, float, list[ProviderStatus]] | None = None
        self._clock: Callable[[], float] = time.monotonic

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMRouter:
        api_key = (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )
        claude: LLMProvider = AnthropicProvider(
            api_key=api_key,
            default_model=settings.anthropic_model,
            timeout=settings.anthropic_timeout,
        )
        if settings.claude_mode == "cli" or (settings.claude_mode == "auto" and not api_key):
            binary = find_claude_binary(settings.claude_cli_path)
            if binary or settings.claude_mode == "cli":
                # Abonnement Claude par Claude Code (sans clé API)
                claude = ClaudeCodeProvider(
                    binary=binary,
                    default_model=settings.claude_cli_model,
                    timeout=settings.claude_cli_timeout,
                )
        providers: dict[ProviderName, LLMProvider] = {
            "anthropic": claude,
            "ollama": OllamaProvider(
                base_url=settings.ollama_base_url,
                default_model=settings.ollama_model,
                timeout=settings.ollama_timeout,
                num_ctx=settings.ollama_num_ctx,
            ),
        }
        default = settings.llm_default_provider
        if default == "anthropic" and not claude.is_configured:
            # Ni clé ni Claude Code : le modèle local répond par défaut (au lieu d'une erreur)
            default = "ollama"
        return cls(providers, default=default, fallback=settings.llm_fallback_provider)

    # ─── Résolution ───────────────────────────────────────────────

    @property
    def provider_names(self) -> list[ProviderName]:
        return list(self._providers)

    def get_provider(self, name: ProviderName | None = None) -> LLMProvider:
        resolved = name or self.default
        provider = self._providers.get(resolved)
        if provider is None:
            raise ProviderNotConfiguredError(f"Provider inconnu : {resolved}", provider=resolved)
        if not provider.is_configured:
            raise ProviderNotConfiguredError(
                f"Le provider « {resolved} » n'est pas configuré.", provider=resolved
            )
        return provider

    def _fallback_for(self, primary: ProviderName) -> LLMProvider | None:
        if self.fallback is None or self.fallback == primary:
            return None
        candidate = self._providers.get(self.fallback)
        return candidate if candidate is not None and candidate.is_configured else None

    @staticmethod
    def _for_fallback(request: LLMRequest) -> LLMRequest:
        # Un nom de modèle n'est pas portable d'un provider à l'autre
        return request.model_copy(update={"model": None})

    # ─── Appels ───────────────────────────────────────────────────

    async def complete(
        self,
        request: LLMRequest,
        *,
        provider: ProviderName | None = None,
        allow_fallback: bool = True,
    ) -> LLMResponse:
        primary = self.get_provider(provider)
        try:
            return await primary.complete(request)
        except ProviderUnavailableError as exc:
            backup = self._fallback_for(primary.name) if allow_fallback else None
            if backup is None:
                raise
            logger.warning("Repli %s → %s : %s", primary.name, backup.name, exc)
            return await backup.complete(self._for_fallback(request))

    async def stream(
        self,
        request: LLMRequest,
        *,
        provider: ProviderName | None = None,
        allow_fallback: bool = True,
    ) -> AsyncIterator[LLMStreamEvent]:
        primary = self.get_provider(provider)
        emitted = False
        try:
            async for event in primary.stream(request):
                emitted = True
                yield event
            return
        except ProviderUnavailableError as exc:
            backup = self._fallback_for(primary.name) if allow_fallback else None
            if backup is None or emitted:
                raise
            logger.warning("Repli %s → %s : %s", primary.name, backup.name, exc)
        async for event in backup.stream(self._for_fallback(request)):
            yield event

    # ─── Supervision ──────────────────────────────────────────────

    async def status(self, *, refresh: bool = False) -> list[ProviderStatus]:
        """État de chaque moteur, gardé `STATUS_TTL` (moins si l'un est indisponible) ;
        `refresh` le relit, au plus toutes les `STATUS_RETRY` secondes."""
        now = self._clock()
        if self._status is not None:
            read_at, expires, cached = self._status
            if now < (read_at + STATUS_RETRY if refresh else expires):
                return cached
        statuses = list(
            await asyncio.gather(*(self._probe(n, p) for n, p in self._providers.items()))
        )
        healthy = all(s.available for s in statuses if s.configured)
        self._status = (now, now + (STATUS_TTL if healthy else STATUS_RETRY), statuses)
        return statuses

    async def _probe(self, name: ProviderName, provider: LLMProvider) -> ProviderStatus:
        models: list[str] = []
        error: str | None = None
        available = False
        if provider.is_configured:
            try:
                models = await provider.list_models()
                available = True
            except Exception as exc:  # supervision : on rapporte, on ne lève pas
                error = str(exc)
        return ProviderStatus(
            name=name,
            configured=provider.is_configured,
            available=available,
            is_default=name == self.default,
            is_fallback=name == self.fallback,
            default_model=provider.default_model,
            models=models,
            error=error,
        )


@lru_cache
def get_llm_router() -> LLMRouter:
    """Dépendance FastAPI (surchargeable dans les tests)."""
    return LLMRouter.from_settings(get_settings())
