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
