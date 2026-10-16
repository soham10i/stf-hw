"""The Python name cleaner agrees with the web one on the shared cases."""

import json
import os

from services.api.names import clean, clean_deep

# the cases live with the web app (web/src/shared), so the web build - which sees only web/ in the
# Docker image - is self-contained; this test reads them from there
CASES = json.load(
    open(os.path.join(os.path.dirname(__file__), "..", "web", "src", "shared", "names_cases.json"))
)


def test_shared_cases():
    for inp, out in CASES:
        assert clean(inp) == out, inp


def test_values_not_keys():
    assert clean_deep({"U9": {"what": "before (U9)"}}) == {"U9": {"what": "before"}}
