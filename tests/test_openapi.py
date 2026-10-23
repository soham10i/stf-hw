"""The API's public contract (docs/openapi.json, `make api-spec`).

Guards what the distributed-API and Postman workflows promise: the OpenAPI
document the app serves enumerates every route the frontend and external
clients call, stays JSON-serializable, and carries the product identity.
"""

import importlib
import json

import pytest

fastapi = pytest.importorskip("fastapi")

EXPECTED_PATHS = {
    "/chat",
    "/chat/status",
    "/chat/stream",
    "/chat/stt",
    "/chat/tts",
    "/command",
    "/copilot/sessions/{sid}",
    "/guest",
    "/health",
    "/layout",
    "/twin/records",
    "/vision/captures",
}


@pytest.fixture()
def spec():
    import services.api.app as appmod

    appmod = importlib.reload(appmod)
    return appmod.app.openapi()


def test_expected_paths_present(spec):
    missing = EXPECTED_PATHS - set(spec["paths"])
    assert not missing, f"openapi() is missing routes: {sorted(missing)}"


def test_identity(spec):
    assert spec["info"]["title"] == "STF Digital Twin"
    assert spec["info"]["version"]
    assert spec["openapi"].startswith("3.")


def test_serializable(spec):
    # the exported docs/openapi.json and Postman's importer both need plain JSON
    round_tripped = json.loads(json.dumps(spec))
    assert round_tripped["paths"] == spec["paths"]
