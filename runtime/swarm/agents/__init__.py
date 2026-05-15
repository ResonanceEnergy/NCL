"""
NCL Swarm Agent Registry.

All specialized agent implementations are registered here for discovery
by the Supervisor during task decomposition and assignment.
"""

from __future__ import annotations

from typing import Type

from ..agent_base import SwarmAgent

# Registry mapping agent_type string → agent class
_AGENT_REGISTRY: dict[str, Type[SwarmAgent]] = {}


def register_agent(agent_type: str):
    """
    Decorator to register an agent class in the swarm registry.

    Usage:
        @register_agent("research")
        class ResearchAgent(SwarmAgent):
            ...
    """

    def decorator(cls: Type[SwarmAgent]) -> Type[SwarmAgent]:
        if agent_type in _AGENT_REGISTRY:
            raise ValueError(
                f"Agent type '{agent_type}' already registered by {_AGENT_REGISTRY[agent_type].__name__}"
            )
        _AGENT_REGISTRY[agent_type] = cls
        return cls

    return decorator


def get_agent_class(agent_type: str) -> Type[SwarmAgent]:
    """
    Retrieve a registered agent class by type name.

    Args:
        agent_type: The registered type string (e.g., "research", "code", "review").

    Returns:
        The SwarmAgent subclass registered under that type.

    Raises:
        KeyError: If no agent is registered under the given type.
    """
    if agent_type not in _AGENT_REGISTRY:
        available = ", ".join(sorted(_AGENT_REGISTRY.keys())) or "(none)"
        raise KeyError(
            f"No agent registered for type '{agent_type}'. Available: {available}"
        )
    return _AGENT_REGISTRY[agent_type]


def list_agent_types() -> list[str]:
    """Return all registered agent type names."""
    return sorted(_AGENT_REGISTRY.keys())


def get_registry() -> dict[str, Type[SwarmAgent]]:
    """Return a copy of the full agent registry."""
    return dict(_AGENT_REGISTRY)


# Import all agent modules to trigger @register_agent decorators
from . import scholar  # noqa: E402, F401
from . import scout  # noqa: E402, F401
from . import architect  # noqa: E402, F401
from . import coder  # noqa: E402, F401
from . import analyst  # noqa: E402, F401
from . import scribe  # noqa: E402, F401
from . import sentinel  # noqa: E402, F401
