// Chart colours on the theme. The pages name their series in hex values that were tuned for the
// old dark themes; on the Zero theme's light surface the pale ones (sky blue, cream, white) all but
// vanish. Every chart passes its colours through chartColor(), which maps those values onto the
// theme's tokens (shared/zero.css: --series-*, --chart-neutral, --flavour-*), so one series keeps
// one hue in both appearances and still reads on either surface. Values not listed pass through.
//
// Two shades per hue where a page draws a pair (the "-soft" companion): darker than the main
// shade in light, lighter in dark, so the pair stays apart in both.
const MAP: Record<string, string> = {
  // blue: the default series
  "#4f8fd6": "var(--series-1)", "#5b8cff": "var(--series-1)", "#3b78c2": "var(--series-1)", "#1f78c8": "var(--series-1)",
  "#9fd0ff": "var(--series-1-soft)", "#8fb8ff": "var(--series-1-soft)", "#7cc3f5": "var(--series-1-soft)",
  "#4fb3d6": "var(--series-1-soft)", "#7fb0e6": "var(--series-1-soft)", "#e6f0ff": "var(--ink)",
  // orange-red: losses and the "against" side of a comparison
  "#e0503a": "var(--series-2)", "#e07a5a": "var(--series-2)", "#f08a4b": "var(--series-2)", "#f87171": "var(--series-2)",
  // green: the result a page argues for
  "#22c55e": "var(--series-3)", "#34d399": "var(--series-3)", "#2f9e8f": "var(--series-3)", "#86efac": "var(--series-3-soft)",
  // amber: sun, oven heat, rule-based baselines
  "#e0a02a": "var(--series-4)", "#f2a33a": "var(--series-4)", "#f2c230": "var(--series-4)", "#e8c25a": "var(--series-4)",
  "#f0c05a": "var(--series-4)", "#d68a2a": "var(--series-4)", "#c7851c": "var(--series-4)", "#c9b458": "var(--series-4-soft)",
  // violet-pink: estimates and the oracle
  "#b07ad6": "var(--series-5)", "#c06bd6": "var(--series-5)",
  // neutral: "before", grid only, the reference
  "#6c7884": "var(--chart-neutral)", "#8b95a3": "var(--chart-neutral)", "#9aa7b4": "var(--chart-neutral)", "#3a4a5c": "var(--chart-grid)",
  // the cookies themselves: vanilla and white need an edge on a light surface
  "#f2efe6": "var(--flavour-vanilla)", "#efe6cf": "var(--flavour-vanilla)", "#fff": "var(--ink)", "#ffffff": "var(--ink)",
};

/** A chart colour on the current theme: a known hex value as its token, anything else unchanged. */
export const chartColor = (c: string | undefined): string => (c ? MAP[c.toLowerCase()] ?? c : "var(--chart-neutral)");
