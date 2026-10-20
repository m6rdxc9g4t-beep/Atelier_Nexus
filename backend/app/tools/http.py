"""Client HTTP commun aux connecteurs des applications (Projets, Trésorerie, GitHub).

Chaque connecteur hérite de `AppClient` : erreurs homogènes (`AppError` et dérivées,
portant le nom de l'application), réponses validées par Pydantic, jamais de redirection.
"""

from __future__ import annotations

from typing import Any, ClassVar, Self

import httpx
from pydantic import BaseModel, ValidationError


class AppError(Exception):
    """Base des erreurs de connecteur ; `app` = identifiant (projets, tresorerie, github)."""

    def __init__(self, message: str, *, app: str) -> None:
        super().__init__(message)
        self.app = app


class AppNotConfiguredError(AppError):
    pass


class AppUnavailableError(AppError):
    """Application arrêtée, injoignable, délai dépassé ou 5xx."""


class AppNotFoundError(AppError):
    pass


class AppRequestError(AppError):
    """Requête refusée (4xx) ou réponse non conforme au contrat."""


class AppClient:
    app: ClassVar[str]
    label: ClassVar[str]
    #: Clés JSON où chercher le message d'erreur, dans l'ordre
    error_keys: ClassVar[tuple[str, ...]] = ("message", "error", "detail")

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.base_url + "/",
            headers={"Accept": "application/json", **(headers or {})},
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    def _unavailable_hint(self) -> str:
        return f"{self.label} est-il lancé ?"

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Appel brut ; renvoie le JSON décodé (None pour 204)."""
        try:
            response = await self._http.request(
                method, path.lstrip("/"), json=json_body, params=params, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise AppUnavailableError(f"{self.label} ne répond pas.", app=self.app) from exc
        except httpx.TransportError as exc:
            raise AppUnavailableError(
                f"{self.label} injoignable sur {self.base_url} : {self._unavailable_hint()}",
                app=self.app,
            ) from exc
        status = response.status_code
        if status == 204:
            return None
        if status == 404:
            raise AppNotFoundError(self._detail(response) or "Ressource introuvable.", app=self.app)
        if status >= 500:
            raise AppUnavailableError(
                f"{self.label} : erreur {status} ({self._detail(response) or 'sans détail'}).",
                app=self.app,
            )
        if status >= 400:
            raise AppRequestError(
                f"{self.label} : {self._detail(response) or f'erreur {status}'}", app=self.app
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AppRequestError(f"Réponse de {self.label} illisible.", app=self.app) from exc

    def _detail(self, response: httpx.Response) -> str | None:
        try:
            body = response.json()
        except ValueError:
            return None
        if isinstance(body, dict):
            for key in self.error_keys:
                value = body.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    def parse[T: BaseModel](self, model: type[T], data: Any) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise AppRequestError(
                f"Réponse de {self.label} non conforme au contrat ({model.__name__}) : "
                f"{exc.error_count()} erreur(s).",
                app=self.app,
            ) from exc

    def parse_list[T: BaseModel](self, model: type[T], data: Any) -> list[T]:
        if not isinstance(data, list):
            raise AppRequestError(f"Liste attendue de la part de {self.label}.", app=self.app)
        return [self.parse(model, item) for item in data]


def safe_id(value: int) -> int:
    """Identifiant numérique d'une ressource (refuse 0, négatifs et valeurs démesurées)."""
    if not 0 < value < 2**31:
        raise ValueError("Identifiant invalide.")
    return value
