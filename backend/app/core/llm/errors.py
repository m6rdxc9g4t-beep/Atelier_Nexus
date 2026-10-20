"""Erreurs du routeur LLM, indépendantes des SDK fournisseurs."""


class LLMError(Exception):
    """Base de toutes les erreurs LLM."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderNotConfiguredError(LLMError):
    """Provider inconnu ou non configuré (ex. clé API Anthropic absente)."""


class ProviderUnavailableError(LLMError):
    """Panne transitoire (réseau, timeout, surcharge, 5xx) : éligible au repli."""


class ProviderRequestError(LLMError):
    """Requête refusée (4xx, modèle introuvable, authentification) : pas de repli."""
