"""
The service's logging: one setup, done on the first `get_logger`, for every module.

    log call ──> root ──> stdout handler (text or JSON), on the calling thread
                     └──> queue handler ──> listener thread ──> slow sinks (add_sink),
                                                               e.g. the Supabase shipper

Both handlers stamp each record with the request id and drop repeated warnings. A sink that
writes to a database or the network sits behind the queue, so it never stalls a request or the
30 Hz simulation broadcast; stdout stays synchronous, since a pipe write is cheap and keeps a
line next to the event that caused it.

  STF_LOG_LEVEL / LOG_LEVEL   DEBUG, INFO (default), WARNING, ERROR
  STF_LOG_FORMAT              text (default) or json; json by default on Cloud Run (K_SERVICE),
                              whose log viewer reads `severity`, `message` and `time` from it
  STF_LOG_REPEAT_S            a WARNING-or-worse message identical to one logged less than this
                              many seconds ago is dropped; the next one that passes says how many
                              were (default 60; 0 keeps every record)
"""

from __future__ import annotations

import atexit
import copy
import json
import logging
import os
import queue
import sys
import threading
import time
from logging.handlers import QueueHandler, QueueListener

from services.api.core.request_context import request_id

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
QUIET_LIBRARIES = ("asyncio", "httpcore", "httpx", "multipart", "urllib3", "websockets")
REPEAT_CACHE_MAX = 1024

_lock = threading.Lock()
_listener: QueueListener | None = None
_configured = False
MARK = "_stf_handler"  # on the root handlers this module installs (see configure_logging)


class TextFormatter(logging.Formatter):
    """`2026-11-09 14:02:11 [INFO] [services.api.app] [5f0c9a1e2b7d4c38]: message`."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s [%(levelname)s] [%(name)s]%(rid)s: %(message)s", DATE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        rid = getattr(record, "request_id", None)
        record.rid = f" [{rid}]" if rid else ""
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, in the field names Google Cloud Logging reads."""

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = getattr(record, "request_id", None)
        if rid:
            out["request_id"] = rid
        if record.exc_text:
            out["exception"] = record.exc_text
        elif record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


class RequestIdFilter(logging.Filter):
    """Stamps each record with the id of the request it was logged in (request_context.py).
    Runs on the logging thread itself, where the request's context is visible."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id()
        return True


class RepeatFilter(logging.Filter):
    """Drops a WARNING-or-worse record whose logger, level and text equal one passed less than
    `window_s` ago: a provider failing on every poll or a scan of bad requests then costs one
    line a minute, not thousands. INFO and DEBUG always pass."""

    def __init__(self, window_s: float) -> None:
        super().__init__()
        self.window_s = window_s
        self._seen: dict[tuple, list] = {}  # key -> [last passed at, dropped since]
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        if self.window_s <= 0 or record.levelno < logging.WARNING:
            return True
        key = (record.name, record.levelno, record.getMessage())
        now = record.created
        with self._lock:
            seen = self._seen.get(key)
            if seen and now - seen[0] < self.window_s:
                seen[1] += 1
                return False
            dropped = seen[1] if seen else 0
            if len(self._seen) >= REPEAT_CACHE_MAX:
                self._seen = {k: v for k, v in self._seen.items() if now - v[0] < self.window_s}
            self._seen[key] = [now, 0]
        if dropped:
            record.msg = f"{record.getMessage()} (repeated {dropped}x, not logged)"
            record.args = None
        return True


class _StdoutHandler(logging.StreamHandler):
    """A StreamHandler on whatever sys.stdout is now (a test runner swaps it per test)."""

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


class _EnqueueHandler(QueueHandler):
    """Puts a picklable, fully rendered copy of each record on the queue: the message with its
    arguments filled in and the traceback as text, so the sinks never touch live objects."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record = copy.copy(record)
        record.msg = record.getMessage()
        record.args = None
        if record.exc_info:
            record.exc_text = record.exc_text or logging.Formatter().formatException(
                record.exc_info
            )
            record.exc_info = None
        return record


def _level(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    name = value or os.environ.get("STF_LOG_LEVEL") or os.environ.get("LOG_LEVEL") or "INFO"
    return getattr(logging, name.upper(), logging.INFO)


def _formatter() -> logging.Formatter:
    default = "json" if os.environ.get("K_SERVICE") else "text"
    wanted = os.environ.get("STF_LOG_FORMAT", default).strip().lower()
    return JsonFormatter() if wanted == "json" else TextFormatter()


def _stamped(handler: logging.Handler) -> logging.Handler:
    handler.addFilter(RequestIdFilter())
    handler.addFilter(RepeatFilter(float(os.environ.get("STF_LOG_REPEAT_S", "60"))))
    setattr(handler, MARK, True)
    return handler


def configure_logging(level: str | int | None = None) -> None:
    """Install the stdout handler on the root logger. Runs once per process: the package's
    old flat module paths can load this file twice, so the root's handlers are checked too."""
    global _configured
    with _lock:
        root = logging.getLogger()
        if _configured or any(getattr(h, MARK, False) for h in root.handlers):
            _configured = True
            return
        resolved = _level(level)
        stdout = _StdoutHandler()
        stdout.setFormatter(_formatter())
        root.setLevel(resolved)
        root.addHandler(_stamped(stdout))
        for name in QUIET_LIBRARIES:
            logging.getLogger(name).setLevel(max(resolved, logging.WARNING))
        _configured = True


def add_sink(handler: logging.Handler) -> None:
    """Send the records to one more handler, on the listener's thread (started on first use)."""
    global _listener
    configure_logging()
    with _lock:
        if _listener is None:
            records: queue.SimpleQueue = queue.SimpleQueue()
            logging.getLogger().addHandler(_stamped(_EnqueueHandler(records)))
            _listener = QueueListener(records, handler, respect_handler_level=True)
            _listener.start()
            atexit.register(shutdown_logging)
        else:
            _listener.handlers = (*_listener.handlers, handler)


def shutdown_logging() -> None:
    """Hand what is queued to the sinks, then close them (at exit)."""
    global _listener
    with _lock:
        listener, _listener = _listener, None
    if listener is None:
        return
    root = logging.getLogger()
    for h in [h for h in root.handlers if isinstance(h, _EnqueueHandler)]:
        root.removeHandler(h)
    listener.stop()
    for handler in listener.handlers:
        handler.close()


def get_logger(name: str) -> logging.Logger:
    """The logger of a module (pass `__name__`), with the setup in place."""
    if not _configured:
        configure_logging()
    return logging.getLogger(name)
