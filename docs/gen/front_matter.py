"""
The front matter every document under docs/reference/ starts with (docs/README.md): a generator
writes it too, so a regenerated chapter keeps its title, scope and module, and carries the date it
was generated as its last_verified.
"""

from __future__ import annotations

import datetime as dt
import re


def quoted(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def front(text: str, scope: str, module: str, generated_by: str, index: bool = True) -> str:
    """`text` (a Markdown document whose first heading is its title) with its front matter."""
    title = re.search(r"^#\s+(.+)$", text, re.M)
    lines = [
        "---",
        f"title: {quoted(re.sub(r'[*_`]', '', title.group(1)).strip() if title else '')}",
        f"scope: {quoted(scope)}",
        f"module: {module}",
        f"last_verified: {dt.date.today().isoformat()}",
        f"generated_by: {generated_by}",
    ]
    if not index:
        lines.append("index: false")
    return "\n".join([*lines, "---", "", text.lstrip("\n")])
