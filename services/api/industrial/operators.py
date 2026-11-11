"""
Who may approve a guarded action (docs/plans/guarded-action-plan.md): named operators,
each with a key, exchanged for a short-lived signed cookie.

STF_OPERATORS   "name:role:sha256(key)" entries, separated by commas or new lines. A role is
                `operator` (may approve and reject) or `viewer` (may look at proposals). Only
                the key's hash is configured, so the secret store never holds a key that works.
                A new entry: python -m services.api.operators NAME [ROLE]

The cookie (stf_operator) carries the name, the role, the first characters of the key's hash
and an expiry, signed with a key derived from STF_AUDIT_SECRET: HttpOnly, SameSite=Strict,
Secure over HTTPS, 30 minutes (STF_OPERATOR_SESSION_S). It is read against the configuration on
every request, so removing an operator, changing their role or rotating their key ends their
sessions at once. A guest is never an operator: the guest cookie and this one are unrelated.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sys
import time
from dataclasses import dataclass

COOKIE = "stf_operator"
ROLES = ("viewer", "operator")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
KEY_ID_LEN = 12  # how much of the key's hash the cookie names


@dataclass(frozen=True)
class Operator:
    """A signed-in operator: who, in which role, with which key, until when."""

    name: str
    role: str
    key_id: str
    expires_at: float

    @property
    def may_approve(self) -> bool:
        return self.role == "operator"


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse(spec: str) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """STF_OPERATORS -> {name: (role, key hash)} and what was wrong with the entries it
    skipped (never the entries themselves)."""
    out: dict[str, tuple[str, str]] = {}
    problems: list[str] = []
    for i, entry in enumerate(e.strip() for e in re.split(r"[,\n]", spec or "")):
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3:
            problems.append(f"entry {i + 1}: expected name:role:sha256")
            continue
        name, role, h = parts[0].strip().lower(), parts[1].strip().lower(), parts[2].strip().lower()
        if not NAME_RE.match(name):
            problems.append(f"entry {i + 1}: a name is 1-32 of a-z 0-9 . _ -")
        elif role not in ROLES:
            problems.append(f"entry {i + 1}: role must be one of {', '.join(ROLES)}")
        elif not HASH_RE.match(h):
            problems.append(f"entry {i + 1}: the key must be given as its sha256 (64 hex)")
        elif name in out:
            problems.append(f"entry {i + 1}: {name} appears twice")
        else:
            out[name] = (role, h)
    return out, problems


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Operators:
    """The configured operators, the key check and the session cookie."""

    def __init__(self, env: dict, secret: bytes, now=time.time) -> None:
        self.by_name, self.problems = parse(env.get("STF_OPERATORS", ""))
        self.ttl = float(env.get("STF_OPERATOR_SESSION_S") or 1800)
        self._key = secret
        self._now = now

    @property
    def configured(self) -> bool:
        return bool(self.by_name)

    def check_key(self, key: str) -> Operator | None:
        """The operator this key belongs to, or None. Every entry is compared, in constant
        time, so the answer's timing does not say how close a guess came."""
        if not key or len(key) > 512:
            return None
        h, found = key_hash(key), None
        for name, (role, want) in self.by_name.items():
            if hmac.compare_digest(h, want):
                found = (name, role)
        if found is None:
            return None
        return Operator(found[0], found[1], h[:KEY_ID_LEN], self._now() + self.ttl)

    def _sig(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())

    def issue(self, op: Operator) -> str:
        payload = _b64(json.dumps(
            {"n": op.name, "r": op.role, "k": op.key_id, "e": round(op.expires_at, 3)},
            separators=(",", ":"),
        ).encode())
        return f"{payload}.{self._sig(payload)}"

    def read(self, value: str | None) -> Operator | None:
        """The operator a cookie names, if its signature holds, it has not expired, and the
        configuration still has that operator, role and key."""
        if not value or value.count(".") != 1 or len(value) > 1024:
            return None
        payload, sig = value.split(".")
        if not hmac.compare_digest(sig, self._sig(payload)):
            return None
        try:
            d = json.loads(_unb64(payload))
            name, role, kid, exp = str(d["n"]), str(d["r"]), str(d["k"]), float(d["e"])
        except (ValueError, KeyError, TypeError):
            return None
        if exp <= self._now():
            return None
        role_now, h = self.by_name.get(name, ("", ""))
        if role_now != role or not hmac.compare_digest(h[:KEY_ID_LEN], kid):
            return None
        return Operator(name, role, kid, exp)

    def cookie(self, op: Operator, secure: bool) -> str:
        age = max(0, int(op.expires_at - self._now()))
        return (
            f"{COOKIE}={self.issue(op)}; Path=/; Max-Age={age}; HttpOnly; SameSite=Strict"
            + ("; Secure" if secure else "")
        )

    @staticmethod
    def clear_cookie(secure: bool) -> str:
        return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict" + (
            "; Secure" if secure else ""
        )


def main(argv: list[str]) -> int:
    """Print a new key and its STF_OPERATORS entry. The key is shown once; keep it in a
    password manager. Only the entry goes into the secret store."""
    if not argv or len(argv) > 2:
        print("usage: python -m services.api.operators NAME [operator|viewer]", file=sys.stderr)
        return 2
    name, role = argv[0].lower(), (argv[1] if len(argv) == 2 else "operator").lower()
    if not NAME_RE.match(name) or role not in ROLES:
        print("a name is 1-32 of a-z 0-9 . _ -; the role operator or viewer", file=sys.stderr)
        return 2
    key = secrets.token_urlsafe(32)
    print(f"key (give it to {name}, once):  {key}")
    print(f"STF_OPERATORS entry:            {name}:{role}:{key_hash(key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
