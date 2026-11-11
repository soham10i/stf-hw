"""Compatibility CLI runner for eval_grounding.

Canonical location: services/api/eval/eval_grounding.py
"""

import services.api.eval.eval_grounding as _target_module

globals().update({
    k: getattr(_target_module, k)
    for k in dir(_target_module)
    if not (k.startswith("__") and k.endswith("__"))
})


def __getattr__(name: str):
    return getattr(_target_module, name)


if __name__ == "__main__":
    _target_module.main()
