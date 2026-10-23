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

from .logging_config import get_logger

logger = get_logger(__name__)

ROOT = os.environ.get("STF_DATA_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".data")
)
ID = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


class DocStore(Protocol):
    """Protocol defining the repository contract for document storage."""

    def get(self, col: str, owner: str, id: str) -> dict | None:
        """One document by (collection, owner, id), or None."""
        ...

    def put(self, col: str, owner: str, id: str, doc: dict) -> None:
        """Upsert a document; newer writes win on conflict."""
        ...

    def delete(self, col: str, owner: str, id: str) -> bool:
        """Delete a document; True when one existed."""
        ...
    def list(
        self, col: str, owner: str, fields: tuple[str, ...], limit: int = 100
    ) -> list[dict]:
        """An owner's documents in a collection, newest first, projected to `fields`."""
        ...


class JsonStore:
    """Filesystem-backed atomic JSON document store.

    Stores documents in partitioned directories: `<root>/<collection>/<owner>/<id>.json`.
    Writes are performed atomically via temporary files and renames to prevent partial reads.

    Attributes:
        root: Root directory path for document storage.
    """

    def __init__(self, root: str = ROOT) -> None:
        """Initialize JsonStore with the target storage root directory.

        Args:
            root: Absolute or relative directory path.
        """
        self.root = root
        self._lock = threading.Lock()

    def _path(self, col: str, owner: str, id: str | None = None) -> str:
        """Construct and validate a filesystem path for a collection, owner, and optional doc ID.

        Args:
            col: Collection name.
            owner: Document owner identifier.
            id: Optional document identifier.

        Returns:
            str: Normalized filesystem path.

        Raises:
            ValueError: If collection, owner, or ID fail alphanumeric validation.
        """
        for part in (col, owner, *([id] if id else [])):
            if not ID.match(part):
                raise ValueError("bad id")
        d = os.path.join(self.root, col, owner)
        return os.path.join(d, f"{id}.json") if id else d

    def get(self, col: str, owner: str, id: str) -> dict | None:
        """Retrieve and parse a stored JSON document.

        Args:
            col: Collection name.
            owner: Document owner.
            id: Document ID.

        Returns:
            dict | None: The document data, or None if not found or corrupted.
        """
        try:
            with open(self._path(col, owner, id), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to read document [%s/%s/%s]: %s", col, owner, id, e)
            return None

    def put(self, col: str, owner: str, id: str, doc: dict) -> None:
        """Atomically persist a document to disk.

        Args:
            col: Collection name.
            owner: Document owner.
            id: Document ID.
            doc: Document dictionary to serialize.

        Raises:
            OSError: If directory creation or file writing fails.
        """
        path = self._path(col, owner, id)
        target_dir = os.path.dirname(path)
        os.makedirs(target_dir, exist_ok=True)
        try:
            with self._lock:
                fd, tmp = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(doc, f, ensure_ascii=False)
                os.replace(tmp, path)
            logger.debug("Persisted document [%s/%s/%s]", col, owner, id)
        except OSError as e:
            logger.error("Failed to write document [%s/%s/%s]: %s", col, owner, id, e)
            raise

    def delete(self, col: str, owner: str, id: str) -> bool:
        """Delete a stored document from disk.

        Args:
            col: Collection name.
            owner: Document owner.
            id: Document ID.

        Returns:
            bool: True if deleted, False if document did not exist or failed to remove.
        """
        try:
            os.remove(self._path(col, owner, id))
            logger.debug("Deleted document [%s/%s/%s]", col, owner, id)
            return True
        except FileNotFoundError:
            return False
        except OSError as e:
            logger.warning("Error deleting document [%s/%s/%s]: %s", col, owner, id, e)
            return False

    def list(self, col: str, owner: str, fields: tuple[str, ...], limit: int = 100) -> list[dict]:
        """List documents for an owner, sorted newest first, projecting requested summary fields.

        Args:
            col: Collection name.
            owner: Document owner.
            fields: Tuple of field names to extract from each document.
            limit: Maximum count of documents to return.

        Returns:
            list[dict]: List of document summaries with extracted fields and document IDs.
        """
        try:
            d = self._path(col, owner)
            names = [n for n in os.listdir(d) if n.endswith(".json")]
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            logger.warning("Failed to list documents for [%s/%s]: %s", col, owner, e)
            return []
        names.sort(key=lambda n: os.path.getmtime(os.path.join(d, n)), reverse=True)
        out = []
        for n in names[:limit]:
            doc = self.get(col, owner, n[:-5])
            if doc:
                out.append({"id": n[:-5], **{k: doc.get(k) for k in fields}})
        return out


def default_store() -> Any:
    """Return the default document store implementation.

    Returns:
        DocStore: Initialized JsonStore instance.
    """
    return JsonStore()
