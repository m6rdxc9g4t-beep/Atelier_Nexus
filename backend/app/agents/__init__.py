from app.agents.base import (
    AgentEvent,
    AgentResult,
    AnyAgentEvent,
    ApprovalRequiredEvent,
    ArtifactEvent,
    BaseAgent,
    DoneEvent,
    PendingCall,
    ReviewRequiredEvent,
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from app.agents.catalog import AgentCatalog
from app.agents.registry import (
    AgentInfo,
    AgentNotFoundError,
    builtin_names,
    describe,
    get_agent_class,
    list_agent_classes,
    register_agent,
)

# Boîte « délégation » puis agents experts : leur import déclenche l'enregistrement
from app.agents import delegation  # noqa: E402, F401  isort: skip
from app.agents import experts  # noqa: E402, F401  isort: skip

# Extensions nommées dans NEXUS_PLUGINS : après les agents fournis (ordre d'affichage)
# (réglages lus à part : le cache de get_settings() n'est pas figé à l'import)
from app.core.config import Settings  # noqa: E402  isort: skip
from app.plugins import add_plugin_paths, load_plugins, parse_plugin_list  # noqa: E402  isort: skip

_settings = Settings()
add_plugin_paths(_settings.nexus_plugin_paths)
load_plugins(parse_plugin_list(_settings.nexus_plugins))

__all__ = [
    "AgentCatalog",
    "AgentEvent",
    "AgentInfo",
    "AgentNotFoundError",
    "AgentResult",
    "AnyAgentEvent",
    "ApprovalRequiredEvent",
    "ArtifactEvent",
    "BaseAgent",
    "DoneEvent",
    "PendingCall",
    "ReviewRequiredEvent",
    "TextDeltaEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "builtin_names",
    "describe",
    "get_agent_class",
    "list_agent_classes",
    "register_agent",
]
