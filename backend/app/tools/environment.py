"""Environnement d'outils d'UNE exécution d'agent : clients HTTP créés à la demande,
fermés à la fin (`aclose`). Les tests injectent des transports simulés par application."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from app.core.config import Settings
from app.tools.cine import CineClient
from app.tools.cuisine import CuisineClient
from app.tools.data_via import DataViaClient, DataViaNotConfiguredError
from app.tools.github import GitHubClient
from app.tools.http import AppNotConfiguredError
from app.tools.projets import ProjetsClient
from app.tools.savoir import SavoirClient
from app.tools.tab import TabSnapshots
from app.tools.tab_mcp import TabMcpClient
from app.tools.tresorerie import TresorerieClient

if TYPE_CHECKING:
    from app.suite.nodes import SuiteNodes


class ToolEnvironment:
    def __init__(
        self,
        settings: Settings,
        *,
        transports: dict[str, httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        self.settings = settings
        self._transports = transports or {}
        self._clients: dict[str, Any] = {}
        # Renseignés par la couche API pour la délégation (orchestrateur)
        self.router: Any = None
        self.catalog: Any = None
        self.delegation_roster: list[tuple[str, str, bool]] = []

    def transport(self, app: str) -> httpx.AsyncBaseTransport | None:
        """Transport simulé d'une application (tests) ; None = réseau réel."""
        return self._transports.get(app)

    def suite(self) -> SuiteNodes:
        """Nœuds de la suite (manifestes, actions, événements) : Viz, Projets, Tab."""
        from app.suite.nodes import SuiteNodes

        client: SuiteNodes = self._get("suite", lambda: SuiteNodes(self))
        return client

    def _get(self, app: str, factory: Any) -> Any:
        if app not in self._clients:
            self._clients[app] = factory()
        return self._clients[app]

    def data_via(self) -> DataViaClient:
        def make() -> DataViaClient:
            url = self.settings.data_via_base_url
            if not url:
                raise DataViaNotConfiguredError("DATA_VIA_BASE_URL n'est pas défini.")
            key = self.settings.data_via_api_key
            return DataViaClient(
                url,
                api_key=key.get_secret_value() if key else None,
                timeout=self.settings.data_via_timeout,
                transport=self._transports.get("data_via"),
            )

        client: DataViaClient = self._get("data_via", make)
        return client

    def projets(self) -> ProjetsClient:
        def make() -> ProjetsClient:
            c = ProjetsClient.from_settings(self.settings, self._transports.get("projets"))
            if c is None:
                raise AppNotConfiguredError("PROJETS_BASE_URL n'est pas défini.", app="projets")
            return c

        client: ProjetsClient = self._get("projets", make)
        return client

    def tresorerie(self) -> TresorerieClient:
        def make() -> TresorerieClient:
            c = TresorerieClient.from_settings(self.settings, self._transports.get("tresorerie"))
            if c is None:
                raise AppNotConfiguredError(
                    "TRESORERIE_BASE_URL n'est pas défini.", app="tresorerie"
                )
            return c

        client: TresorerieClient = self._get("tresorerie", make)
        return client

    def cine(self) -> CineClient:
        def make() -> CineClient:
            c = CineClient.from_settings(self.settings, self._transports.get("cine"))
            if c is None:
                raise AppNotConfiguredError("CINE_BASE_URL n'est pas défini.", app="cine")
            return c

        client: CineClient = self._get("cine", make)
        return client

    def savoir(self) -> SavoirClient:
        def make() -> SavoirClient:
            c = SavoirClient.from_settings(self.settings, self._transports.get("savoir"))
            if c is None:
                raise AppNotConfiguredError("SAVOIR_BASE_URL n'est pas défini.", app="savoir")
            return c

        client: SavoirClient = self._get("savoir", make)
        return client

    def cuisine(self) -> CuisineClient:
        def make() -> CuisineClient:
            c = CuisineClient.from_settings(self.settings, self._transports.get("cuisine"))
            if c is None:
                raise AppNotConfiguredError(
                    "Atelier Cuisine n'est pas configuré (CUISINE_SUPABASE_URL, clé publique, "
                    "e-mail + mot de passe ou jeton de rafraîchissement).",
                    app="cuisine",
                )
            return c

        client: CuisineClient = self._get("cuisine", make)
        return client

    def tab(self) -> TabSnapshots:
        def make() -> TabSnapshots:
            c = TabSnapshots.from_settings(self.settings)
            if c is None:
                raise AppNotConfiguredError("TAB_EXPORTS_DIR n'est pas défini.", app="tab")
            return c

        client: TabSnapshots = self._get("tab", make)
        return client

    def tab_mcp(self) -> TabMcpClient:
        def make() -> TabMcpClient:
            c = TabMcpClient.from_settings(self.settings)
            if c is None:
                raise AppNotConfiguredError(
                    "TAB_MCP_COMMAND n'est pas défini : Atelier Tab est en lecture seule.",
                    app="tab",
                )
            return c

        client: TabMcpClient = self._get("tab_mcp", make)
        return client

    def github(self) -> GitHubClient:
        def make() -> GitHubClient:
            c = GitHubClient.from_settings(self.settings, self._transports.get("github"))
            if c is None:
                raise AppNotConfiguredError(
                    "GITHUB_REPO n'est pas défini : aucun dépôt autorisé.", app="github"
                )
            return c

        client: GitHubClient = self._get("github", make)
        return client

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
