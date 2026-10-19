// The generators number their design steps (Upgrade 1 ... 18, or U1 ... U18). On screen the
// machine is one machine: every such reference is shown by what that step built instead.
// Blueprint sheet ids (U2-02) and long unspaced strings (ids, URLs, encoded weights) are kept.

export const FEATURE: Record<number, string> = {
  1: "stiffened structure", 2: "machine safety", 3: "remote I/O", 4: "PLC program", 5: "commissioning",
  6: "condition monitoring", 7: "lifecycle design", 8: "AI maintenance", 9: "microgrid", 10: "throughput program",
  11: "OT security", 12: "hardened machine", 13: "live PLC", 14: "connectivity", 15: "vision QC",
  16: "scheduler", 17: "copilot", 18: "carbon model",
};

const REF = String.raw`(?:Upgrades?\s|U|up)`;
const name = (n: string) => FEATURE[+n] ?? `step ${n}`;
const RULES: [RegExp, string | ((...m: string[]) => string)][] = [
  // phrasings the generic rules would make clumsy
  [/so Upgrade 1 leaves it alone/g, "so it stays as it is"],
  [/Upgrade 12 interlock/g, "interlock"],
  [/U10's slowest run (still )?beats U7's fastest/g, (_m, s = "") => `the new program's slowest run ${s}beats the old one's fastest`],
  // "(Upgrade 2)", "(U5)", "(U11-U12)", "(U6-U10, U15-U18)": a bare reference in brackets is dropped
  [new RegExp(String.raw`\s*\(${REF}\d{1,2}(?:\s*[-–,]\s*(?:and\s+)?U?\d{1,2})*\)`, "g"), ""],
  // "(U5 accuracy)", "(Upgrade 1: sag check)": keep what follows the reference
  [new RegExp(String.raw`\(${REF}\d{1,2}[:\s]\s*`, "g"), "("],
  // "Upgrade 1 - central air", "Upgrade 2: valve ...": a leading reference is dropped
  [new RegExp(String.raw`^${REF}\d{1,2}\s*[-–:]\s+`, "g"), ""],
  // "Upgrade 1's buffer" -> "the buffer"
  [/\bUpgrade \d{1,2}'s /g, "the "],
  // "Upgrades 5 and 7"
  [/\bUpgrades (\d{1,2}) and (\d{1,2})\b/g, (_m, a, b) => `${name(a)} and ${name(b)}`],
  // anything else: the feature's name
  [/(?<![-\w.])(?:Upgrade |U|up)(\d{1,2})(?![-\d])/gi, (_m, n) => name(n)],
];

/** One string with its design-step references replaced by feature names. */
export function clean(s: string): string {
  // the variant tag inside identifiers (order code STF-U12, MQTT node cell-u12, topic paths)
  s = s.replace(/\b(cell|Cell|CELL|stf|STF)-([Uu])12\b/g, (_m, w) => `${w}-01`);
  if (s.length > 64 && !/\s/.test(s)) return s;              // ids, URLs, base64
  if (!/Upgrade|\bU\d/.test(s)) return s;
  let out = s;
  for (const [re, to] of RULES) out = out.replace(re, to as never);
  out = out.replace(/\s{2,}/g, " ").replace(/\s+([,.;:)])/g, "$1");
  return out.charAt(0) !== s.charAt(0) && /^[a-z]/.test(out) && /^[A-Z]/.test(s) ? out[0].toUpperCase() + out.slice(1) : out;
}

/** Every string value in a parsed JSON document, cleaned; keys are left as they are. */
export function cleanDeep<T>(v: T): T {
  if (typeof v === "string") return clean(v) as T;
  if (Array.isArray(v)) return v.map(cleanDeep) as T;
  if (v && typeof v === "object") {
    const o: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v)) o[k] = cleanDeep(x);
    return o as T;
  }
  return v;
}
