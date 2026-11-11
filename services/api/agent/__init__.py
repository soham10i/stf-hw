"""Agent domain package."""

import sys
import types

from . import graph
from . import graph as agent


class _AgentDomainModule(types.ModuleType):
    def __getattr__(self, name):
        return getattr(graph, name)

    def __setattr__(self, name, value):
        if hasattr(graph, name) or name == "HAVE_LANGGRAPH":
            setattr(graph, name, value)
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _AgentDomainModule
