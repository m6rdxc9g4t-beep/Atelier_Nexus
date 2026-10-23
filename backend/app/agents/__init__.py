from app.agents.base import (
    AgentEvent,
    AgentResult,
    AnyAgentEvent,
    ApprovalRequiredEvent,
    ArtifactEvent,
    BaseAgent,
    DoneEvent,
    PendingCall,
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
from app.plugins import load_plugins, parse_plugin_list  # noqa: E402  isort: skip

load_plugins(parse_plugin_list(Settings().nexus_plugins))

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
    "TextDeltaEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "builtin_names",
    "describe",
    "get_agent_class",
    "list_agent_classes",
    "register_agent",
]
