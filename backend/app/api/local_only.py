"""Garde « requêtes locales » de l'API, sur le modèle des autres applications de la suite
(`LocalOnlyMiddleware` de Viz et de Convert, gardes Host / Origin de Wiki, Formulaire et Hub).

Protège l'API contre les sites web visités dans le navigateur de l'utilisateur :

- « DNS rebinding » : un domaine externe qui pointe soudain vers 127.0.0.1 envoie un en-tête
  `Host` étranger ; sans garde, sa page lirait les conversations et validerait des actions à la
  place de l'utilisateur (`POST /api/workflow-runs/{id}/resume`, `PUT /api/settings`) ;
- requêtes d'un autre site (CSRF) : l'en-tête `Origin` d'une écriture désigne un hôte étranger.

Règles : `Host` de bouclage (`127.0.0.1`, `localhost`, `[::1]`, port quelconque),
hôte d'une origine de `CORS_ORIGINS` (le VPS : `nexus.<domaine>`) ou listé dans `ALLOWED_HOSTS` ;
pour les écritures (POST, PUT, PATCH, DELETE), `Origin` absente ou d'un de ces hôtes. L'origine
`null` (iframe isolée, fichier local) est refusée en écriture. Un appel sans navigateur (Hub,
scripts, sonde de l'app de bureau) n'envoie pas d'`Origin` et reste accepté. La santé (`/health`,
`/api/health`) répond à tout hôte : elle ne dit rien de privé et sert aux sondes.

Réglages relus à chaque requête : une modification à chaud (Réglages) s'applique aussitôt.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings, get_settings

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Sondes de santé (Docker, Hub, app de bureau) : ouvertes à tout hôte, en lecture
OPEN_PATHS = frozenset({"/health", "/api/health"})


def host_name(value: str) -> str:
    """Nom d'hôte d'un en-tête Host (« 127.0.0.1:8100 », « [::1]:8100 »), en minuscules, sans port."""
    host = value.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host[1:]
    # Une seule « : » = séparateur de port ; plusieurs = adresse IPv6 sans crochets
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def origin_host(origin: str) -> str | None:
    """Nom d'hôte d'un en-tête Origin (« http://localhost:3100 ») ; None s'il est illisible ou
    `null`."""
    try:
        parts = urlsplit(origin.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return parts.hostname.lower()


def allowed_hosts(origins: Iterable[str] = (), extra: Iterable[str] = ()) -> frozenset[str]:
    """Hôtes acceptés : bouclage, hôtes des origines CORS déclarées, liste `ALLOWED_HOSTS`."""
    declared = {origin_host(o) for o in origins}
    listed = {host_name(h) for h in extra if h.strip()}
    return LOCAL_HOSTS | {h for h in declared if h} | listed


def refusal(
    method: str, host: str | None, origin: str | None, hosts: frozenset[str]
) -> tuple[str, str] | None:
    """Refus d'une requête : `(code, message)`, ou None si elle est acceptée."""
    if host is None or host_name(host) not in hosts:
        return (
            "forbidden_host",
            f"Hôte « {host or ''} » refusé : l'API de Nexus n'accepte que les requêtes locales "
            "(voir ALLOWED_HOSTS).",
        )
    if origin is not None and method.upper() in UNSAFE_METHODS:
        name = origin_host(origin)
        if name is None or name not in hosts:
            return (
                "forbidden_origin",
                f"Origine « {origin} » refusée : seule l'interface de Nexus peut agir.",
            )
    return None


class LocalOnlyMiddleware:
    """Middleware ASGI : refuse (403, `{"error": {"code", "message"}}`) une requête non locale."""

    def __init__(self, app: ASGIApp, settings: Callable[[], Settings] = get_settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        # WebSocket : contrôlé comme une écriture
        method = scope.get("method", "GET") if scope["type"] == "http" else "POST"
        if method in {"GET", "HEAD"} and scope.get("path") in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        settings = self.settings()
        hosts = allowed_hosts(settings.cors_origin_list, settings.allowed_host_list)
        refused = refusal(method, headers.get("host"), headers.get("origin"), hosts)
        if refused is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        code, message = refused
        body = json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False)
        payload = body.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})
