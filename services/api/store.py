"""
A small document store for the copilot's sessions: JSON documents in collections, addressed by
an owner and an id - the shape of a NoSQL store (MongoDB, Firestore, DynamoDB), so one of those
can replace JsonStore without the chat noticing: it only uses get / put / delete / list.

JsonStore keeps one file per document - <root>/<collection>/<owner>/<id>.json - so a session is
read and written alone however many there are, written atomically (temp file + rename), and a
listing reads only the small summary each document carries.

  STF_DATA_DIR   where the documents live (default: <repo>/.data). On a host with an ephemeral
                 disk (Render's free tier) sessions last until the next deploy.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from typing import Any, Protocol

ROOT = os.environ.get("STF_DATA_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".data")
)
ID = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


class DocStore(Protocol):
    def get(self, col: str, owner: str, id: str) -> dict | None: ...
    def put(self, col: str, owner: str, id: str, doc: dict) -> None: ...
    def delete(self, col: str, owner: str, id: str) -> bool: ...
    def list(
        self, col: str, owner: str, fields: tuple[str, ...], limit: int = 100
    ) -> list[dict]: ...


class JsonStore:
    def __init__(self, root: str = ROOT) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _path(self, col: str, owner: str, id: str | None = None) -> str:
        for part in (col, owner, *([id] if id else [])):
            if not ID.match(part):
                raise ValueError("bad id")
        d = os.path.join(self.root, col, owner)
        return os.path.join(d, f"{id}.json") if id else d

    def get(self, col: str, owner: str, id: str) -> dict | None:
        try:
            with open(self._path(col, owner, id), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def put(self, col: str, owner: str, id: str, doc: dict) -> None:
        path = self._path(col, owner, id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._lock:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            os.replace(tmp, path)

    def delete(self, col: str, owner: str, id: str) -> bool:
        try:
            os.remove(self._path(col, owner, id))
            return True
        except OSError:
            return False

    def list(self, col: str, owner: str, fields: tuple[str, ...], limit: int = 100) -> list[dict]:
        """The owner's documents, newest first, as their summary fields only."""
        try:
            d = self._path(col, owner)
            names = [n for n in os.listdir(d) if n.endswith(".json")]
        except (OSError, ValueError):
            return []
        names.sort(key=lambda n: os.path.getmtime(os.path.join(d, n)), reverse=True)
        out = []
        for n in names[:limit]:
            doc = self.get(col, owner, n[:-5])
            if doc:
                out.append({"id": n[:-5], **{k: doc.get(k) for k in fields}})
        return out


def default_store() -> Any:
    return JsonStore()
