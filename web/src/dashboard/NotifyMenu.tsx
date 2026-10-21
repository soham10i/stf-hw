// The bell menu: owner notifications (services/api/notify.py) at a glance.
// Shows whether the "someone is on the site" email is configured, and sends a
// self-test notice on request. POST /notify/test is operator-guarded like
// /command: on the operator's own machine it just works; on a deployment the
// operator token (STF_API_TOKEN) is asked once and kept in this browser.
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Icon } from "../shared/icons";
import { HAS_API } from "../shared/mode";

const TOKEN_KEY = "stf.op.token";

type Status = { on: boolean; channels: string[]; every_hours: number };
type Phase = "idle" | "sending" | "sent" | "error";

function loadToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}
function saveToken(v: string) {
  try {
    if (v) localStorage.setItem(TOKEN_KEY, v);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* private mode: the token just is not remembered */ }
}

const IS_PROD = import.meta.env.PROD;

export function NotifyMenu() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [token, setToken] = useState(loadToken);
  const [phase, setPhase] = useState<Phase>("idle");
  const [note, setNote] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !HAS_API || IS_PROD) return;
    let stale = false;
    fetch("/notify/status").then((r) => (r.ok ? r.json() : null)).then((s) => { if (!stale && s) setStatus(s); }).catch(() => undefined);
    return () => { stale = true; };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", away);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("pointerdown", away); window.removeEventListener("keydown", esc); };
  }, [open]);

  // Hidden in production so regular users do not see or access owner notifications
  if (!HAS_API || IS_PROD) return null;

  const test = async () => {
    setPhase("sending");
    setNote("");
    try {
      const r = await fetch("/notify/test", {
        method: "POST",
        headers: token ? { "X-STF-Token": token } : undefined,
      });
      if (r.ok) {
        setPhase("sent");
        setNote("Sent - check the owner's inbox.");
      } else {
        const body = await r.json().catch(() => ({}));
        setPhase("error");
        setNote(r.status === 403
          ? "Operator token needed (or use the operator's machine)."
          : (body.detail ?? `failed (${r.status})`));
      }
    } catch {
      setPhase("error");
      setNote("the API is not reachable");
    }
  };

  return (
    <div className="theme-menu notify-menu" ref={box}>
      <button className="ui-btn icon" onClick={() => setOpen(!open)} aria-haspopup="dialog" aria-expanded={open}
        title="Owner notifications" aria-label="Owner notifications">
        <Icon name="bell" size={17} />
        {status?.on && <i className="notify-dot" aria-hidden="true" />}
      </button>
      <AnimatePresence>
      {open && (
        <motion.div className="theme-pop notify-pop" role="dialog" aria-label="Owner notifications"
          initial={{ opacity: 0, y: -6, scale: 0.985 }} animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -4, scale: 0.99 }} transition={{ duration: 0.16, ease: "easeOut" }}>
          <em>Owner notifications</em>
          <div className="notify-body">
            <p className="notify-state">
              {status === null ? "checking…" : status.on
                ? <>on · {status.channels.join(" + ")} · max one per guest per {status.every_hours} h</>
                : <>off — set <code>STF_NOTIFY_EMAIL</code> + <code>STF_SMTP_*</code> on the service</>}
            </p>
            <label className="notify-token">
              <span>Operator token {token ? "(saved in this browser)" : "(only for a deployed site)"}</span>
              <input type="password" value={token} placeholder="STF_API_TOKEN"
                onChange={(e) => { setToken(e.target.value); saveToken(e.target.value); }} autoComplete="off" />
            </label>
            <button className="ui-btn notify-test" onClick={test} disabled={phase === "sending" || (status !== null && !status.on)}>
              <Icon name="bell" size={15} />
              {phase === "sending" ? "Sending…" : "Send a test email"}
            </button>
            {phase === "sent" && <p className="notify-ok"><Icon name="check" size={14} /> {note}</p>}
            {phase === "error" && <p className="notify-bad">{note}</p>}
            <p className="notify-hint">The same guard as machine commands: the operator's machine needs no token; a deployed site asks for it once, here.</p>
          </div>
        </motion.div>
      )}
      </AnimatePresence>
    </div>
  );
}
