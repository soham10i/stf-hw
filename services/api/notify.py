"""Owner notifications (notify.py).

The owner gets an email (and/or a webhook post) when a visitor uses the site -
at most one notice per guest per STF_NOTIFY_EVERY_HOURS, never per page beacon,
so a browsing session cannot fill a mailbox. Off unless configured:

  STF_NOTIFY_EMAIL=you@gmail.com        who receives the note (empty/unset = off)
  STF_SMTP_HOST=smtp.gmail.com          the mailbox that sends it
  STF_SMTP_PORT=465
  STF_SMTP_USER=you@gmail.com
  STF_SMTP_PASS=xxxx xxxx xxxx xxxx     Gmail: an app password, never the login one
  STF_NOTIFY_WEBHOOK=https://...        extra channel, a POST with the note as text
                                        (a Discord/Slack webhook, or https://ntfy.sh/<topic>)
  STF_NOTIFY_EVERY_HOURS=12             per-guest throttle, default 12

The send is synchronous with short timeouts: Cloud Run allocates CPU only
while a request is being processed, so a fire-and-forget thread could be
throttled before it finished. One note per session costs the first beacon of
that session a bounded fraction of a second - later beacons are throttled to
a dict lookup. A failure is logged, never raised into the beacon.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import threading
import time
import urllib.request
from email.message import EmailMessage

from .logging_config import get_logger

logger = get_logger(__name__)

CONNECT_S = 5  # SMTP connect / webhook timeout - one notice must not stall a beacon


class Notifier:
    """One email per guest per window. Everything degrades to a log line."""

    def __init__(self, env: dict, geo: object | None = None, now=time.time):
        self.email_to = (env.get("STF_NOTIFY_EMAIL") or "").strip()
        self.smtp_host = (env.get("STF_SMTP_HOST") or "").strip()
        self.smtp_port = int(env.get("STF_SMTP_PORT") or "465")
        self.smtp_user = (env.get("STF_SMTP_USER") or "").strip()
        raw_pass = (env.get("STF_SMTP_PASS") or "").strip()
        # Gmail app passwords are displayed in 4-character groups ("xxxx xxxx xxxx xxxx");
        # SMTP wants them concatenated. Only gmail.com is treated this way.
        is_gmail = "gmail.com" in self.smtp_host.lower()
        self.smtp_pass = raw_pass.replace(" ", "") if is_gmail else raw_pass
        self.webhook = (env.get("STF_NOTIFY_WEBHOOK") or "").strip()
        self.every_s = float(env.get("STF_NOTIFY_EVERY_HOURS") or "12") * 3600.0
        # service-wide: a new guest is free to make (no cookie = a new guest), so the per-guest
        # throttle alone would let a script send one email per request
        self.max_per_hour = int(env.get("STF_NOTIFY_MAX_PER_HOUR") or "10")
        self._sent: list[float] = []
        self.geo = geo
        self._now = now
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def on(self) -> bool:
        email_ok = bool(self.email_to and self.smtp_host and self.smtp_user and self.smtp_pass)
        return email_ok or bool(self.webhook)

    def _fresh(self, guest: str) -> bool:
        now = self._now()
        with self._lock:
            last = self._last.get(guest)
            if last is not None and now - last < self.every_s:
                return False
            self._sent = [t for t in self._sent if now - t < 3600.0]
            if len(self._sent) >= self.max_per_hour:
                return False
            self._sent.append(now)
            self._last[guest] = now
            if len(self._last) > 4096:
                for g, _t in [g for g, t in self._last.items() if now - t > 7 * 86400]:
                    self._last.pop(g, None)
        return True

    def visit(
        self,
        guest: str | None,
        page: str,
        ip: str | None,
        ua: str | None,
    ) -> bool:
        """Called after a beacon was stored. True means a notice went out."""
        if not self.on or not guest or not self._fresh(guest):
            return False
        place = self.geo.place(ip) if (self.geo and ip) else None
        where = ", ".join(p for p in (place[2], place[1], place[0]) if p) if place else ""
        text = self._text(guest, page, where, ua)
        return self._send(text)

    @staticmethod
    def _text(guest: str, page: str, where: str, ua: str | None) -> str:
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        page, where, ua = _plain(page, 80), _plain(where, 120), _plain(ua, 120) if ua else ua
        lines = [
            "A visitor is on stf-live right now.",
            "",
            f"  session {guest}",
            f"  page    {page}",
            f"  where   {where or 'unknown'}",
            f"  when    {when}",
        ]
        if ua:
            lines.append(f"  browser {ua[:120]}")
        return "\n".join(lines)

    def test(self) -> bool:
        """A self-test notice to the owner, from the dashboard button. Bypasses the per-guest
        throttle (it is not about a guest); the endpoint still rate-limits per client."""
        if not self.on:
            return False
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        text = (
            "This is a test of the stf-live visitor notification.\n\n"
            " If this email arrives, the SMTP/Webhook configuration is correct and the owner\n"
            " will be emailed when a new visitor accepts the consent banner.\n\n"
            f"  when    {when}\n"
            f"  to      {self.email_to or '(webhook only)'}\n"
            f"  via     {' + '.join(self.channels)}"
        )
        return self._send(text, subject="stf-live: notification test")

    @property
    def channels(self) -> list[str]:
        ch = []
        if self.email_to and self.smtp_host and self.smtp_user and self.smtp_pass:
            ch.append(f"email ({self.smtp_host})")
        if self.webhook:
            ch.append("webhook")
        return ch

    def _send(self, text: str, subject: str | None = None) -> bool:
        ok = False
        if self.email_to and self.smtp_host and self.smtp_user and self.smtp_pass:
            ok = self._mail(text, subject) or ok
        if self.webhook:
            ok = self._post(text) or ok
        return ok

    def _mail(self, text: str, subject: str | None = None) -> bool:
        msg = EmailMessage()
        if subject is None:
            where = next(
                (ln.split(None, 1)[1] for ln in text.splitlines() if ln.startswith("  where")), ""
            )
            place = where.strip()
            place = _plain(place, 80)
            session = next(
                (ln.split(None, 1)[1] for ln in text.splitlines() if ln.startswith("  session")), ""
            ).strip()
            sess_tag = f" [session: {session[:8]}]" if session else ""
            subject = f"stf-live: visitor from {place}{sess_tag}" if place else f"stf-live: visitor{sess_tag}"
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = self.email_to
        msg.set_content(text)
        try:
            ctx = ssl.create_default_context()
            smtp = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=CONNECT_S, context=ctx)
            with smtp as s:
                s.login(self.smtp_user, self.smtp_pass)
                s.send_message(msg)
            return True
        except (OSError, smtplib.SMTPException) as e:
            logger.warning("Visitor notice email failed: %s", e)
            return False

    def _post(self, text: str) -> bool:
        body = json.dumps({"text": text, "content": text}).encode()
        req = urllib.request.Request(
            self.webhook,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=CONNECT_S) as r:  # noqa: S310 - the configured URL
                r.read()
            return True
        except Exception as e:  # any webhook failure is a log line, not a beacon failure
            logger.warning("Visitor notice webhook failed: %s", e)
            return False


def _plain(s: str, n: int) -> str:
    """Visitor-supplied text, made safe for an email: one line, printable, bounded."""
    return "".join(c if c.isprintable() else " " for c in s)[:n]


def notifier_from_env(env: dict | None = None, geo: object | None = None) -> Notifier:
    return Notifier({**os.environ, **(env or {})}, geo=geo)
