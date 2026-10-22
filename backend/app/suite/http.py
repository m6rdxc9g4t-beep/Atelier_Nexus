"""Client HTTP d'un nœud de la suite (Viz, Projets) : manifeste, actions, événements.

Même infrastructure que les connecteurs (`AppClient` : transport injectable en test, jamais de
redirection suivie), avec les gardes du contrat `atelier-node/1` :
- adresse de bouclage uniquement (`127.0.0.1`, `localhost`, `::1`) : rien ne sort de la machine ;
- réponse lue en flux et bornée en taille ;
- une redirection est une erreur (jamais suivie) ;
- erreurs `{detail, code}` de l'application relayées telles quelles.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any

import httpx

from app.tools.http import AppClient, AppError, AppUnavailableError

LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


def is_loopback(url: str) -> bool:
    try:
        host = httpx.URL(url).host
    except (httpx.InvalidURL, TypeError):
        return False
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def split_base(base_url: str) -> tuple[str, str]:
    """`http://127.0.0.1:8000/api` → (`http://127.0.0.1:8000`, `/api`) : les chemins d'action du
    manifeste sont absolus (`/api/query`), le manifeste et les événements sont sous la base
    configurée (`{base}/atelier/manifest`)."""
    url = httpx.URL(base_url)
    origin = str(url.copy_with(path="/", query=None, fragment=None)).rstrip("/")
    return origin, url.path.rstrip("/")


class NodeActionError(AppError):
    """Action refusée ou en échec ; `code` = code machine de l'application (§7.5) ou de Nexus."""

    def __init__(self, message: str, *, app: str, code: str, status: int | None = None) -> None:
        super().__init__(message, app=app)
        self.code = code
        self.status = status


class NodeResponse:
    def __init__(self, status: int, headers: httpx.Headers, body: Any) -> None:
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def replayed(self) -> bool:
        value: str = self.headers.get("idempotency-replayed", "")
        return value.lower() == "true"


class NodeHttpClient(AppClient):
    """Client d'UNE application (`app`, `label` fixés à la construction)."""

    def __init__(
        self,
        app: str,
        label: str,
        base_url: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        # Attributs de classe d'AppClient renseignés par instance : un client par application
        self.app = app  # type: ignore[misc]
        self.label = label  # type: ignore[misc]
        if not is_loopback(base_url):
            raise NodeActionError(
                f"{label} : adresse {base_url} refusée, le contrat atelier-node/1 n'autorise que "
                "le bouclage (127.0.0.1, localhost, ::1).",
                app=app,
                code="FORBIDDEN_HOST",
            )
        origin, self.api_path = split_base(base_url)
        super().__init__(origin, timeout=timeout, transport=transport)
        self.max_bytes = max_bytes

    async def call(
        self,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> NodeResponse:
        """Appel brut : statut ≥ 300 → `NodeActionError` (code de l'application si fourni)."""
        kwargs: dict[str, Any] = {"params": params, "headers": headers}
        if json_body is not None:
            kwargs["json"] = json_body
        try:
            async with self._http.stream(method, path.lstrip("/"), **kwargs) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw += chunk
                    if len(raw) > self.max_bytes:
                        raise NodeActionError(
                            f"{self.label} : réponse trop volumineuse (plus de "
                            f"{self.max_bytes // (1024 * 1024)} Mo).",
                            app=self.app,
                            code="RESPONSE_TOO_LARGE",
                        )
                status, response_headers = response.status_code, response.headers
        except httpx.TimeoutException as exc:
            raise NodeActionError(
                f"{self.label} ne répond pas.", app=self.app, code="UNREACHABLE"
            ) from exc
        except httpx.TransportError as exc:
            raise NodeActionError(
                f"{self.label} injoignable sur {self.base_url} : l'application est-elle lancée ?",
                app=self.app,
                code="UNREACHABLE",
            ) from exc
        body: Any = None
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                body = None
        if 300 <= status < 400:
            raise NodeActionError(
                f"{self.label} : redirection refusée (statut {status}).",
                app=self.app,
                code="REDIRECT",
                status=status,
            )
        if status >= 400:
            detail, code = _error(body)
            raise NodeActionError(
                f"{self.label} : {detail or f'erreur {status}'}",
                app=self.app,
                code=code or ("NOT_FOUND" if status == 404 else f"HTTP_{status}"),
                status=status,
            )
        if raw and body is None:
            raise NodeActionError(
                f"Réponse de {self.label} illisible (JSON attendu).",
                app=self.app,
                code="BAD_RESPONSE",
            )
        return NodeResponse(status, response_headers, body)

    async def get_json(self, path: str, params: list[tuple[str, str]] | None = None) -> Any:
        return (await self.call("GET", path, params=params)).body


def _error(body: Any) -> tuple[str | None, str | None]:
    """`{detail, code}` du contrat (ou `message` / `error` des routes plus anciennes)."""
    if not isinstance(body, dict):
        return None, None
    detail = next(
        (body[k] for k in ("detail", "message", "error") if isinstance(body.get(k), str)), None
    )
    code = body.get("code") if isinstance(body.get("code"), str) else None
    return detail, code


__all__ = [
    "AppUnavailableError",
    "NodeActionError",
    "NodeHttpClient",
    "NodeResponse",
    "split_base",
    "is_loopback",
]
