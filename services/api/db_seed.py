"""Compatibility CLI runner for db_seed.

Canonical location: services/api/storage/db_seed.py
"""

import sys
import services.api.storage.db_seed as _target_module

globals().update({
    k: getattr(_target_module, k)
    for k in dir(_target_module)
    if not (k.startswith("__") and k.endswith("__"))
})

def __getattr__(name: str):
    return getattr(_target_module, name)

if __name__ == "__main__":
    if hasattr(_target_module, "main"):
        try:
            sys.exit(_target_module.main(sys.argv[1:]))
        except TypeError:
            sys.exit(_target_module.main())
    elif hasattr(_target_module, "cli"):
        _target_module.cli()
