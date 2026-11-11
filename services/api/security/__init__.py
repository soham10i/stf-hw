"""Security domain package."""

import sys
import types

from . import rules
from . import rules as security


class _SecurityDomainModule(types.ModuleType):
    def __getattr__(self, name):
        return getattr(rules, name)

    def __setattr__(self, name, value):
        if hasattr(rules, name):
            setattr(rules, name, value)
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _SecurityDomainModule
