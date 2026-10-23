// The copilot's answer settings: who is asking (a profile that sets the defaults below), how
// deep an answer goes, and which web sources it may use - plus what the providers cost. The
// profile is the quick way; each setting can then be changed on its own. Kept in this browser.
import { motion } from "motion/react";
import * as api from "./api";
import { Icon } from "../../shared/icons";

export const PROFILES: [api.Audience, string, string, string][] = [
  ["operator", "wrench", "Operator", "Short, plain answers: what to do and what to check"],
  ["engineer", "ruler", "Engineer", "Precise terms, units and equations, with the standard or datasheet behind each value"],
  ["researcher", "book", "Researcher", "Researched reports from standards and peer-reviewed papers only, evidence rated"],
];
export const DEPTHS: [api.Depth, string, string][] = [
  ["auto", "Auto", "Set by the question: a status is brief, a deep research thorough"],
  ["brief", "Brief", "A few sentences · one search · ~1.5k tokens at most"],
  ["standard", "Standard", "A complete answer · up to 3 searches · ~3k tokens"],
  ["thorough", "Thorough", "A researched report · up to 5 searches + peer-reviewed papers · ~6k tokens"],
];
export const LEVELS: [api.SourceLevel, string, string][] = [
  ["vetted", "Vetted", "Forums and social media are never used; other sites are shown, marked unvetted"],
  ["strict", "Authoritative only", "Only standards, public agencies, universities, peer-reviewed papers, manufacturers and curated references"],
];
const PILL = { type: "spring", stiffness: 500, damping: 40 } as const;

/** One row of mutually exclusive options, with a sliding highlight. */
function Seg<T extends string>({ id, value, options, onChange, label }: {
  id: string; value: T; options: [T, string, string][]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="cx-seg" role="radiogroup" aria-label={label}>
      {options.map(([v, text, tip]) => (
        <button key={v} role="radio" aria-checked={value === v} className={value === v ? "on" : ""} title={tip} onClick={() => onChange(v)}>
          {value === v && <motion.span layoutId={`cx-seg-${id}`} className="cx-pill" transition={PILL} />}
          {text}
        </button>
      ))}
    </div>
  );
}

/** The compact strip above the composer: the profile, depth and sources at a glance; a tap
    opens the full settings. */
export function SettingsChip({ prefs, onOpen, open }: { prefs: api.Prefs; onOpen: () => void; open: boolean }) {
  const p = PROFILES.find(([a]) => a === prefs.audience)!;
  const d = DEPTHS.find(([x]) => x === prefs.depth)!;
  return (
    <button className={`cx-prefs-chip ${open ? "on" : ""}`} onClick={onOpen} aria-expanded={open} title="Answer settings">
      <Icon name={p[1]} size={13} /><b>{p[2]}</b>
      <span>·</span>{d[1]}
      <span>·</span>{prefs.sources === "strict" ? <><Icon name="seal" size={12} />Authoritative</> : "Vetted"}
      <Icon name="cog" size={13} />
    </button>
  );
}

export function AnswerSettings({ prefs, set, status, spent }: {
  prefs: api.Prefs; set: (p: api.Prefs) => void; status: api.Status; spent: number;
}) {
  const budget = status.search?.budget;
  return (
    <div className="cx-settings">
      <section>
        <h4>Who is asking</h4>
        <div className="cx-profiles">
          {PROFILES.map(([a, icon, label, tip]) => (
            <button key={a} className={prefs.audience === a ? "on" : ""} aria-pressed={prefs.audience === a}
              onClick={() => set(api.PROFILE_DEFAULTS[a])}>
              <Icon name={icon} size={16} /><b>{label}</b><span>{tip}</span>
            </button>
          ))}
        </div>
        <p className="cx-muted">A profile sets the two settings below; change either afterwards.</p>
      </section>
      <section>
        <h4>Depth</h4>
        <Seg id="depth" label="Depth" value={prefs.depth} options={DEPTHS} onChange={(depth) => set({ ...prefs, depth })} />
        <p className="cx-muted">{DEPTHS.find(([x]) => x === prefs.depth)![2]}</p>
      </section>
      <section>
        <h4>Web sources</h4>
        <Seg id="src" label="Web sources" value={prefs.sources} options={LEVELS} onChange={(sources) => set({ ...prefs, sources })} />
        <p className="cx-muted">{LEVELS.find(([x]) => x === prefs.sources)![2]}</p>
      </section>
      <section>
        <h4>Cost</h4>
        <ul className="cx-billing">
          {(status.billing ?? []).map((b) => (
            <li key={b.provider}><span>{b.provider}</span><i className={/free/.test(b.plan) ? "free" : "paid"}>{b.plan}</i></li>
          ))}
          {!status.billing?.length && <li><span>No provider reported</span></li>}
        </ul>
        {budget && (
          <div className="cx-budget" title="The server's own Gemini limit, set below Google's quota">
            <span>Gemini today</span>
            <div><i style={{ width: `${Math.min(100, (100 * budget.tokens_day.used) / Math.max(1, budget.tokens_day.limit))}%` }} /></div>
            <em>{api.kTokens(budget.tokens_day.used)} / {api.kTokens(budget.tokens_day.limit)}</em>
          </div>
        )}
        <p className="cx-muted">This conversation: {api.kTokens(spent)} tokens. The plans are the operator's labels; each provider's console is the authority.</p>
      </section>
    </div>
  );
}
