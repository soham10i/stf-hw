"""The repo's .env parsing, in one importable place.

Every backend service builds its settings from ``{**dotenv(), **os.environ}`` so a local run
picks up the git-ignored .env while a deployment's real environment variables win. Living in
its own module (not chat.py) keeps it importable from modules chat imports - vectors.py needs
it for the vector backend's Supabase settings - without a circular import.

Only whitelisted prefixes are read: the file may hold unrelated or sensitive lines that no
service should ingest wholesale.
"""

from __future__ import annotations

import os

PREFIXES = (
    "GEMINI_",
    "OLLAMA_",
    "GROQ_",
    "GROK_",
    "XAI_",
    "TTS_",
    "ELEVENLABS_",
    "STF_",
    "SUPABASE_",
    "UPB_",
    "WEB_",
)


def dotenv(path: str | None = None) -> dict[str, str]:
    """Parse .env lines of the repo (git-ignored) for local runs; the environment wins."""
    path = path or os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    out: dict[str, str] = {}
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, sep, v = line.partition("=")
            if sep and k.strip().startswith(PREFIXES):
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out
