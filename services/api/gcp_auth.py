"""
Google Cloud access for the Vertex AI lane: an OAuth access token, never a key in the code.

The $300 trial credit pays for Gemini on Vertex AI (aiplatform.googleapis.com), not for the
AI Studio endpoint (generativelanguage.googleapis.com) that GEMINI_API_KEY and
GEMINI_CLOUD_API_KEY call. Vertex takes a bearer token of a principal with the
roles/aiplatform.user role. Where the token comes from, first that has one:

  GOOGLE_OAUTH_ACCESS_TOKEN   a token set by hand (a test, a CI job); used as given
  the metadata server         on Cloud Run: the service's own service account, no secret to store
  gcloud                      on a laptop: `gcloud auth print-access-token` (`gcloud auth login`)

A token is kept until a minute before it expires (they last an hour), so a question costs one
token fetch an hour, not one per call.

  GEMINI_VERTEX_PROJECT    the project whose credit pays (unset: the Vertex lane is off)
  GEMINI_VERTEX_LOCATION   default global (Gemini 3 models are served from the global endpoint)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request

from .logging_config import get_logger

logger = get_logger(__name__)

METADATA = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
EARLY_S = 60.0  # a token is renewed this long before it expires
GCLOUD_TTL_S = 50 * 60.0  # gcloud does not say when its token expires; they last an hour


class NoToken(RuntimeError):
    """No source could give a Google Cloud access token."""


def endpoint(project: str, location: str, model: str) -> str:
    """The Vertex AI generateContent URL of a Gemini model in a project and location."""
    host = "aiplatform.googleapis.com"
    if location != "global":
        host = f"{location}-{host}"
    return (
        f"https://{host}/v1/projects/{project}/locations/{location}"
        f"/publishers/google/models/{model}:generateContent"
    )


def _metadata() -> tuple[str, float]:
    """The service account's token from the metadata server (Cloud Run, GCE)."""
    req = urllib.request.Request(METADATA, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=2.0) as r:  # noqa: S310 - fixed metadata URL
        data = json.loads(r.read())
    return data["access_token"], float(data.get("expires_in", 3600))


def _gcloud() -> tuple[str, float]:
    """The signed-in user's token from the gcloud CLI (a laptop)."""
    exe = shutil.which("gcloud")
    if not exe:
        raise NoToken("gcloud is not installed")
    out = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [exe, "auth", "print-access-token"], capture_output=True, text=True, timeout=20
    )
    token = out.stdout.strip()
    if out.returncode or not token:
        raise NoToken("gcloud has no signed-in account (run `gcloud auth login`)")
    return token, GCLOUD_TTL_S


class Tokens:
    """A cached access token, renewed before it expires; safe to share between threads."""

    def __init__(self, sources=None, clock=time.time) -> None:
        self.sources = (_metadata, _gcloud) if sources is None else sources
        self.clock = clock
        self._token = ""
        self._until = 0.0
        self._lock = threading.Lock()

    def get(self) -> str:
        """A token valid for at least EARLY_S more seconds. Raises NoToken."""
        fixed = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
        if fixed:
            return fixed
        with self._lock:
            if self._token and self.clock() < self._until:
                return self._token
            why = []
            for source in self.sources:
                try:
                    token, ttl = source()
                except Exception as e:  # each source fails in its own way; the next is asked
                    why.append(f"{source.__name__.strip('_')}: {e}")
                    continue
                self._token, self._until = token, self.clock() + max(0.0, ttl - EARLY_S)
                return token
            raise NoToken("no Google Cloud token (" + "; ".join(why) + ")")


TOKENS = Tokens()
