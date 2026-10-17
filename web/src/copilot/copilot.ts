// Upgrade 17: the operator copilot. No language model: a question is routed to a TOOL that
// computes the answer from the twin's own data (health, alarms, the month, energy, carbon,
// the scheduler, the vision models), or, failing that, answered with the best-matching
// passage of the project's documents (BM25). Every answer says where it comes from, and a
// question nothing covers is answered "I don't know" rather than guessed.
// Pure functions over a data context, so the browser and the check script run the same code.
import { compAt } from "../shared/health";
import type { CadDoc, HealthComp } from "../shared/model";

export type Passage = { id: number; doc: string; path: string[]; text: string };
export type Answer = {
  tool: string;                         // which tool answered, or "documents" / "none"
  text: string;
  facts?: [string, string][];
  link?: { page: string; label: string };
  sources: string[];
  passages?: { p: Passage; score: number; cover?: number }[];
};
/** The data a question may need, loaded on demand by the caller (fetch in the browser). */
export type Ctx = {
  age: number; pm: boolean;
  get: <T>(key: DataKey) => Promise<T>;
};
export type DataKey = "cad" | "month" | "carbon" | "sched" | "ai" | "vision" | "adapt" | "grid" | "security" | "kb";
export const DATA: Record<DataKey, string> = {
  cad: "hbw_parts_up12.json", month: "month/month.json", carbon: "carbon/carbon.json", sched: "sched/rl.json",
  ai: "ml/results.json", vision: "vision/results.json", adapt: "vision/adapt.json", grid: "grid/grid.json",
  security: "security/security.json", kb: "copilot/kb.json",
};

// ------------------------------------------------------------------ text search (BM25)
const STOP = new Set("a an the of to in on at for and or is are was were be been it its this that what which who how why when where do does did can could should would will i we you my our your there their than then with from by as into about any much many".split(" "));
export function tokens(s: string) {
  return s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9äöüß ]+/g, " ").split(/\s+/)
    .filter((w) => w.length > 1 && !STOP.has(w)).map((w) => w.replace(/(ies)$/, "y").replace(/(?<=[a-z]{3})(s|ed|ing)$/, ""));
}
export class Bm25 {
  private df = new Map<string, number>();
  private docs: { tf: Map<string, number>; len: number }[] = [];
  private avg = 1;
  constructor(public passages: Passage[], private k1 = 1.4, private b = 0.75) {
    for (const p of passages) {
      const tf = new Map<string, number>();
      for (const t of tokens(`${p.path.join(" ")} ${p.path.join(" ")} ${p.text}`)) tf.set(t, (tf.get(t) ?? 0) + 1);
      for (const t of tf.keys()) this.df.set(t, (this.df.get(t) ?? 0) + 1);
      this.docs.push({ tf, len: [...tf.values()].reduce((a, b) => a + b, 0) });
    }
    this.avg = this.docs.reduce((a, d) => a + d.len, 0) / Math.max(1, this.docs.length);
  }
  search(q: string, k = 3) {
    const qt = [...new Set(tokens(q))], N = this.docs.length;
    return this.docs.map((d, i) => {
      let s = 0;
      for (const t of qt) {
        const f = d.tf.get(t);
        if (!f) continue;
        const n = this.df.get(t)!, idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
        s += idf * (f * (this.k1 + 1)) / (f + this.k1 * (1 - this.b + this.b * d.len / this.avg));
      }
      return { p: this.passages[i], score: s, cover: qt.filter((t) => d.tf.has(t)).length / Math.max(1, qt.length) };
    }).filter((x) => x.score > 0).sort((a, b) => b.score - a.score).slice(0, k);
  }
}

// ------------------------------------------------------------------ tools
const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)} %`;
const short = (s: string) => s.replace(/ \(.*\)$/, "");
const PART_WORDS: [RegExp, string][] = [
  [/suction|cup|vacuum seal|gripper/, "cup"], [/oven door|door cyl/, "door"], [/lower|sauger/, "lower"], [/pusher|auswerfer|eject/, "pusher"],
  [/hbw belt|conveyor belt|\bbelt\b/, "belt"], [/rfid|read head/, "rfid"], [/spindle|nut|travel/, "spindle"], [/gearbox|swivel/, "gearbox"],
  [/air|leak|compressor/, "air"], [/colou?r sensor|a4|led/, "colour"],
];
function partIn(q: string) { return PART_WORDS.find(([r]) => r.test(q))?.[1]; }
function ageIn(q: string) { const m = /(\d+(?:\.\d+)?)\s*(?:shifts?|sh)\b/.exec(q); return m ? Number(m[1]) : null; }

type Tool = { id: string; score: (q: string) => number; run: (q: string, c: Ctx) => Promise<Answer> };
const has = (q: string, ...r: RegExp[]) => r.filter((x) => x.test(q)).length;

const TOOLS: Tool[] = [
  {
    id: "service-next",
    score: (q) => has(q, /service|maintain|maintenance|replace|renew|work order/, /next|first|soon|today|which part|what part|due/) * 2,
    run: async (q, c) => {
      const d = await c.get<CadDoc>("cad"), age = ageIn(q) ?? c.age;
      const st = d.health!.components.map((x) => compAt(x, age, c.pm)).sort((a, b) => (a.status === "ok" ? 1 : 0) - (b.status === "ok" ? 1 : 0)
        || ((a.c.warn ?? 1e12) - a.n) / a.c.per_shift - ((b.c.warn ?? 1e12) - b.n) / b.c.per_shift);
      const due = st.filter((s) => s.status !== "ok");
      const next = st.filter((s) => s.status === "ok")[0];
      const warnIn = next ? ((next.c.warn ?? 0) - next.n) / next.c.per_shift : 0;
      return {
        tool: "service-next",
        text: due.length ? `${due.map((s) => short(s.c.name)).join(", ")} ${due.length > 1 ? "need" : "needs"} service now (${due.map((s) => s.status === "fail" ? "failed" : "warned").join(", ")}).`
          : `Nothing is due. Next: ${short(next.c.name)} warns in ${warnIn.toFixed(1)} shifts.`,
        facts: st.slice(0, 5).map((s) => [short(s.c.name), s.status === "ok" ? `health ${Math.round(s.hi)} · warns in ${(((s.c.warn ?? 0) - s.n) / s.c.per_shift).toFixed(1)} sh` : s.status === "fail" ? "FAILED" : `warned · fails in ${(s.rulShifts ?? 0).toFixed(1)} sh`]),
        link: { page: "maintenance", label: "Maintenance" }, sources: [`health model at a machine age of ${age} shifts, PM ${c.pm ? "on" : "off"}`],
      };
    },
  },
  {
    id: "part-life",
    score: (q) => (partIn(q) ? 2 : 0) + has(q, /fail|life|last|health|worn|wear|rul|how long|when/) * 2,
    run: async (q, c) => {
      const d = await c.get<CadDoc>("cad"), id = partIn(q) ?? "cup", age = ageIn(q) ?? c.age;
      const comp = d.health!.components.find((x) => x.id === id) as HealthComp, s = compAt(comp, age, c.pm);
      return {
        tool: "part-life",
        text: s.status === "fail" ? `${comp.name} has failed: replace it.` : s.status === "warn"
          ? `${comp.name} is warned: about ${(s.rulShifts ?? 0).toFixed(1)} shifts until it fails.`
          : `${comp.name} is healthy (health index ${Math.round(s.hi)}); it warns in ${(((comp.warn ?? 0) - s.n) / comp.per_shift).toFixed(1)} shifts and would fail in ${(s.rulShifts ?? 0).toFixed(1)}.`,
        facts: [["measured by", comp.metric], ["warning comes", `${comp.lead_shifts} shifts before failure`], ["uses this life", Math.round(s.n).toLocaleString()],
                ["false warnings", `${comp.false_warnings} in ${comp.healthy_cycles.toLocaleString()} healthy uses`]],
        link: { page: "health", label: "Health" }, sources: [`health model, ${comp.name}, at ${age} shifts`],
      };
    },
  },
  {
    id: "alarm-code",
    score: (q) => (/[a-z]{3}-[a-z]\d\d/i.test(q) ? 6 : 0) + has(q, /alarm|code/) ,
    run: async (q, c) => {
      const d = await c.get<CadDoc>("cad"), code = /([a-z]{3}-[a-z]\d\d)/i.exec(q)?.[1]?.toUpperCase();
      const a = d.control!.alarms.find((x) => x.code === code);
      if (!a) return { tool: "alarm-code", text: `There is no alarm ${code ?? "with that code"}. Alarm codes look like HBW-C01.`, sources: ["the PLC's alarm list"], link: { page: "alarms", label: "Alarms" } };
      return { tool: "alarm-code", text: `${a.code}: ${a.text}.`, facts: [["likely cause", a.cause], ["what the machine does", a.reaction], ["to recover", a.recovery], ["watchdog", `${a.limit} s`]],
               link: { page: "alarms", label: "Alarms" }, sources: [`the PLC's alarm list, ${a.code}`] };
    },
  },
  {
    id: "why-stop",
    score: (q) => has(q, /why|what|cause|reason/, /stop|stopp|down|halt|fault|downtime|lost/) * 2 + has(q, /month|worst|most|biggest/),
    run: async (_q, c) => {
      const m = await c.get<{ events: { t: number; kind: string; what: string; code?: string; lost_s?: number; down_h?: number }[]; pareto: { cause: string; hours: number }[]; kpi: { unplanned_h: number; failures: number; faults: number } }>("month");
      const faults = m.events.filter((e) => e.kind === "fault" || e.kind === "failure");
      const by = new Map<string, { n: number; s: number }>();
      for (const e of faults) { const k = e.code ?? e.what; const v = by.get(k) ?? { n: 0, s: 0 }; v.n++; v.s += e.lost_s ?? (e.down_h ?? 0) * 3600; by.set(k, v); }
      const top = [...by.entries()].sort((a, b) => b[1].s - a[1].s);
      const last = faults[faults.length - 1];
      return {
        tool: "why-stop",
        text: `This month the line stopped ${faults.length} times (${m.kpi.unplanned_h} h unplanned). The biggest cause: ${top[0][0]}, ${top[0][1].n} stops, ${(top[0][1].s / 60).toFixed(0)} min lost. The last stop: day ${(last.t / 24 + 1).toFixed(1)}, ${last.what}.`,
        facts: top.slice(0, 4).map(([k, v]) => [k, `${v.n}× · ${(v.s / 60).toFixed(1)} min`]),
        link: { page: "month", label: "Month" }, sources: ["the simulated month's event log (month.py)"],
      };
    },
  },
  {
    id: "oee",
    score: (q) => has(q, /\boee\b|throughput|cookies per hour|per hour|output|availability|performance|bottleneck|order time|makespan/) * 3,
    run: async (_q, c) => {
      const d = await c.get<CadDoc>("cad"), p = d.vc!.performance;
      const loss = [["availability", p.availability], ["performance", p.performance], ["quality", p.quality]].sort((a, b) => (a[1] as number) - (b[1] as number))[0];
      return { tool: "oee", text: `OEE ${pct(p.oee)}: the biggest loss is ${loss[0]} (${pct(loss[1] as number)}). A 12-cookie order takes ${p.makespan} s; the bottleneck is the ${p.bottleneck}.`,
               facts: [["availability", pct(p.availability)], ["performance", pct(p.performance)], ["quality", pct(p.quality)], ["order time", `${p.makespan} s`]],
               link: { page: "overview", label: "Overview" }, sources: ["virtual commissioning"] };
    },
  },
  {
    id: "carbon",
    score: (q) => has(q, /co2|carbon|emission|footprint|climate|gram/) * 3,
    run: async (_q, c) => {
      const d = await c.get<{ levers: Record<string, { g_per_cookie: number }>; standing_share: number; meta: { cookies_per_order: number } }>("carbon");
      const b = d.levers["as built: PV + battery"], keys = Object.keys(d.levers), best = d.levers[keys[keys.length - 1]];
      return { tool: "carbon", text: `${b.g_per_cookie.toFixed(2)} g CO₂e per good cookie (${(b.g_per_cookie * d.meta.cookies_per_order).toFixed(1)} g per order). ${pct(d.standing_share)} of it is the cell standing idle; with every lever it falls to ${best.g_per_cookie.toFixed(2)} g.`,
               facts: keys.map((k) => [k, `${d.levers[k].g_per_cookie.toFixed(3)} g`]), link: { page: "carbon", label: "Carbon per cookie" }, sources: ["carbon.py over the microgrid month"] };
    },
  },
  {
    id: "energy",
    score: (q) => has(q, /energy|electric|power bill|kwh|solar|\bpv\b|battery|grid|cost/) * 3 - has(q, /co2|carbon/) * 4,
    run: async (_q, c) => {
      const g = await c.get<{ scenarios: Record<string, { load_kwh: number; total_eur: number; self_sufficiency: number; import_kwh: number }> }>("grid");
      const b = g.scenarios["pv+battery"], o = g.scenarios.grid;
      return { tool: "energy", text: `The cell used ${b.load_kwh} kWh this month; PV and the battery covered ${pct(b.self_sufficiency)} of it, for €${b.total_eur} instead of €${o.total_eur} from the grid alone.`,
               facts: [["imported", `${b.import_kwh} kWh`], ["self-sufficiency", pct(b.self_sufficiency)], ["cost", `€${b.total_eur}`]], link: { page: "energy", label: "Energy & grid" }, sources: ["the microgrid month (grid.py)"] };
    },
  },
  {
    id: "scheduler",
    score: (q) => has(q, /schedul|dispatch|deadlock|reinforcement|\brl\b|faster order|priority/) * 3,
    run: async (_q, c) => {
      const d = await c.get<{ eval: Record<string, { nominal: number; mean: number }>; paired: { wins: number; runs: number; mean_diff_s: number }; unshielded: { deadlocks: number; episodes: number }; meta: { fallback: string } }>("sched");
      const r = d.eval["rollout, no learning"], p = d.eval[d.meta.fallback];
      return { tool: "scheduler", text: `The shielded scheduler finishes an order in ${r.nominal} s against the PLC's ${p.nominal} s, faster in ${d.paired.wins} of ${d.paired.runs} runs on identical timings; it never deadlocked, where the same agent without its shield deadlocked in ${d.unshielded.deadlocks} of ${d.unshielded.episodes} orders.`,
               facts: [["scheduler, mean", `${r.mean} s`], ["PLC, mean", `${p.mean} s`], ["per order", `${d.paired.mean_diff_s} s`]], link: { page: "scheduler", label: "Learned scheduler" }, sources: ["sched_rl.py"] };
    },
  },
  {
    id: "vision",
    score: (q) => has(q, /vision|camera|inspection|cnn|defect|escape|false reject|chipped|cracked|burnt|drift/) * 3,
    run: async (_q, c) => {
      const v = await c.get<{ results: Record<"in_domain" | "shifted", { condition_acc: number; escape_rate: number; false_reject: number }> }>("vision");
      const i = v.results.in_domain, s = v.results.shifted;
      return { tool: "vision", text: `Under the conditions it was trained for, the inspection is right ${pct(i.condition_acc, 1)} of the time; under unseen light it drops to ${pct(s.condition_acc, 1)} and rejects ${pct(s.false_reject)} of good cookies. The drift alarm catches that; retraining with images of the new conditions fixes it.`,
               facts: [["trained conditions: escapes", pct(i.escape_rate, 1)], ["unseen: false rejects", pct(s.false_reject, 1)], ["unseen: escapes", pct(s.escape_rate, 1)]],
               link: { page: "vision", label: "Vision QC" }, sources: ["vision/train.py and vision/adapt.py"] };
    },
  },
  {
    id: "ai",
    score: (q) => has(q, /neural|network|predict|machine learning|\bml\b|\bai\b|tcn/) * 3 - has(q, /vision|camera|cnn/) * 4,
    run: async (_q, c) => {
      const r = await c.get<{ results: { name: string; warned_1shift: number; failures: number; missed: number }[] }>("ai");
      const rule = r.results[0], semi = r.results.find((x) => x.name.startsWith("semi"))!;
      return { tool: "ai", text: `On machines it never saw, the network warned ${semi.warned_1shift} of ${semi.failures} failures a shift ahead (rules: ${rule.warned_1shift}). It runs as an advisory estimate beside the rules.`,
               link: { page: "ai", label: "Maintenance · AI predictions" }, sources: ["ml/train.py"] };
    },
  },
  {
    id: "security",
    score: (q) => has(q, /secur|attack|hack|cyber|firewall|malware|spoof/) * 3,
    run: async (_q, c) => {
      const d = await c.get<{ attacks: { id: string; name: string; blocked: boolean }[] }>("security");
      return { tool: "security", text: `${d.attacks.filter((a) => a.blocked).length} of ${d.attacks.length} attacks replayed on the twin are contained.`,
               facts: d.attacks.map((a) => [`${a.id} ${a.name}`, a.blocked ? "contained" : "open"]), link: { page: "security", label: "OT security" }, sources: ["security.py"] };
    },
  },
];

const GREETING = /^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening))\b/i;

/** Route a question: the best-scoring tool, else the documents, else "I don't know". */
export async function answer(q0: string, c: Ctx): Promise<Answer> {
  const q = q0.toLowerCase().trim();
  if (GREETING.test(q)) {
    return {
      tool: "greeting",
      text: "Hello! I am the STF Digital Twin Copilot. Ask me about machine health, maintenance schedules, OEE, alarm codes, energy, carbon, or vision inspection.",
      sources: [],
    };
  }
  const ranked = TOOLS.map((t) => ({ t, s: t.score(q) })).sort((a, b) => b.s - a.s);
  if (ranked[0].s >= 3) return ranked[0].t.run(q, c);
  const kb = await c.get<{ passages: Passage[] }>("kb");
  const idx = bm25(kb.passages);
  const hits = idx.search(q0, 3);
  // a passage counts only if it covers more than half of the question's meaningful words
  if (hits.length && hits[0].score >= 4 && hits[0].cover > 0.5) {
    const top = hits[0].p;
    // a passage cut from a longer section may start mid-sentence: start at the next sentence
    let t = top.text;
    if (/^[a-z]/.test(t) && t.indexOf(". ") > 0 && t.indexOf(". ") < 200) t = t.slice(t.indexOf(". ") + 2);
    return { tool: "documents", text: t.length > 420 ? `${t.slice(0, 420)}…` : t, passages: hits,
             sources: hits.map((h) => `${h.p.doc} › ${h.p.path.filter(Boolean).join(" › ")}`) };
  }
  return { tool: "none", text: "I don't know: nothing in the twin's data or documents covers that. Try asking about a part, an alarm code, the month's stops, OEE, energy, carbon, the scheduler or the inspection.", sources: [] };
}

/** Everything the twin knows about a question, for a language model to answer from: the
    copilot's own answer (a tool's result or a passage) and the best document passages. */
export async function ground(q: string, c: Ctx, k = 3) {
  const local = await answer(q, c);
  if (local.tool === "greeting") {
    return { local, passages: [] };
  }
  const kb = await c.get<{ passages: Passage[] }>("kb");
  const passages = bm25(kb.passages).search(q, k).filter((h) => h.score >= 2);
  return { local, passages };
}

let cache: { n: number; idx: Bm25 } | null = null;
function bm25(ps: Passage[]) {
  if (!cache || cache.n !== ps.length) cache = { n: ps.length, idx: new Bm25(ps) };
  return cache.idx;
}

export const EXAMPLES = ["What needs service next?", "When will the HBW belt fail?", "What does alarm VGR-V01 mean?", "Why did the line stop this month?",
  "What is the OEE?", "How much CO2 per cookie?", "Is the learned scheduler faster?", "How good is the vision inspection?", "How does the safety shield work?",
  "What is the ride-through reserve?"];
