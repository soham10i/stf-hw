// The STF operations dashboard: a page of its own, separate from the 3D twin.
// It reads the newest upgrade export (up7, else up6) - the PLC's run (U4), the
// commissioning results (U5), the condition-monitoring model (U6) and the
// lifecycle checks (U7). Nothing here is typed in.
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useCadDoc } from "../shared/model";
import { fmtT, makespan } from "../shared/hmi";
import { maxShifts } from "../shared/health";
import { HealthPage } from "./Health";
import { MaintenancePage } from "./Maintenance";
import { MonthPage } from "./Month";
import { AiPage } from "./Ai";
import { GridPage } from "./Grid";
import { ThroughputPage } from "./Throughput";
import { SecurityPage } from "./Security";
import { HardeningPage, ValidationPage } from "./Assurance";
import { VisionPage } from "./Vision";
import { CarbonPage } from "./Carbon";
import { SchedulerPage } from "./Scheduler";
import { CopilotPage } from "./Copilot";
import { Chat } from "./Chat";
import { Icon, ThemeToggle } from "../shared/icons";
import { useTheme } from "../shared/theme";
import { cardHelp } from "./guide";


// the docs pages carry KaTeX: loaded when opened
const DegradationPage = lazy(() => import("./Degradation").then((m) => ({ default: m.DegradationPage })));

const BASE = import.meta.env.BASE_URL;
const PAGES = [
  ["overview", "Overview", "home", "Operate"], ["production", "Production", "factory", "Operate"],
  ["quality", "Quality & trace", "check", "Operate"], ["vision", "Vision QC", "eye", "Operate"], ["alarms", "Alarms", "bell", "Operate"], ["copilot", "Copilot", "info", "Operate"],
  ["health", "Health", "heart", "Maintain"], ["maintenance", "Maintenance", "wrench", "Maintain"],
  ["ai", "AI maintenance", "brain", "Maintain"],
  ["month", "Month", "calendar", "Analyse"], ["throughput", "Throughput", "gauge", "Analyse"], ["scheduler", "Learned scheduler", "cpu", "Analyse"],
  ["energy", "Energy & grid", "bolt", "Analyse"], ["carbon", "Carbon per cookie", "sun", "Analyse"], ["security", "OT security", "shield", "Analyse"],
  ["hardening", "Defence in depth", "layers", "Analyse"],
  ["engineering", "Engineering", "cog", "Engineer"], ["validation", "Validation", "check", "Engineer"], ["data", "Data", "database", "Engineer"],
  ["docs-degradation", "Hardware degradation", "activity", "Docs"],
] as const;
const CLOCK_PAGES = ["overview", "production", "quality"];
const AGE_PAGES = ["overview", "health", "maintenance"];
type Page = (typeof PAGES)[number][0];

function useDoc() {
  const { doc, err } = useCadDoc();
  return { doc: doc && doc.control && doc.vc && doc.health ? doc : null, src: "up12", err };
}

// --------------------------------------------------------------- shared
import { PageCtx, GuideBox } from "./ui";
import { Overview, Production, Quality, Alarms } from "./Operate";
import { Engineering, Data } from "./Engineer";

// ----------------------------------------------------------------- shell
export function Dashboard() {
  const { doc, src, err } = useDoc();
  const [page, setPage] = useState<Page>(() => (new URLSearchParams(location.search).get("p") as Page) || "overview");
  const [t, setT] = useState(0);
  const [play, setPlay] = useState(true);
  const [age, setAge] = useState(0);
  const [pm, setPm] = useState(true);
  const [theme, toggleTheme] = useTheme();
  // the guide is open on the first visit and remembered after that
  const [guide, setGuide] = useState(() => { try { return localStorage.getItem("stf.db.guide") !== "0"; } catch { return true; } });
  const showGuide = (v: boolean) => { setGuide(v); try { localStorage.setItem("stf.db.guide", v ? "1" : "0"); } catch { /* private mode */ } };
  const [navOpen, setNavOpen] = useState(() => window.innerWidth > 900);
  const [askOpen, setAskOpen] = useState(false);
  const T = doc?.control ? makespan(doc.control) : 1;
  useEffect(() => {
    if (!play || !doc) return;
    const id = window.setInterval(() => setT((x) => (x + 2 >= T ? 0 : x + 2)), 100);
    return () => window.clearInterval(id);
  }, [play, T, doc]);
  useEffect(() => { history.replaceState(null, "", `?p=${page}`); }, [page]);
  // the pages that build their own sections (Month, AI, Energy, Throughput, Security, Assurance)
  // get the same i-hint on each section title as Card gives, as their data loads
  useEffect(() => {
    const root = document.querySelector(".db-main");
    if (!root) return;
    const hint = () => {
      root.querySelectorAll<HTMLElement>(".db-card > h3").forEach((h) => {
        if (h.querySelector(".db-help")) return;
        const help = cardHelp(page, h.textContent ?? "");
        if (!help) return;
        const i = document.createElement("i");
        i.className = "db-help"; i.title = help; i.setAttribute("aria-label", help); i.textContent = "i";
        h.appendChild(i);
      });
    };
    hint();
    const mo = new MutationObserver(hint);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [page, doc]);
  const ageMax = useMemo(() => (doc?.health ? maxShifts(doc.health.components) : 1), [doc]);
  if (err) return <div className="db-err">{err}</div>;
  if (!doc) return <div className="db-err">loading the twin's export…</div>;
  const cur = PAGES.find((p) => p[0] === page)!;
  const groups = Array.from(new Set(PAGES.map((p) => p[3])));
  // long notes and findings open on click instead of filling the page
  const expand = (e: React.MouseEvent) => {
    const el = (e.target as HTMLElement).closest(".db-note, .mo-insights > div");
    if (el) el.classList.toggle("open");
  };
  return (
    <div className={`db ${navOpen ? "" : "nav-min"}`}>
      <nav className="db-nav">
        <div className="db-brand">
          <span className="brand-mark">STF</span><div><b>Operations</b><span>{src} · live twin data</span></div>
        </div>
        {groups.map((g) => (
          <div key={g} className="db-group">
            <div className="db-group-h">{g}</div>
            {PAGES.filter((p) => p[3] === g).map(([id, label, icon]) => (
              <button key={id} className={id === page ? "on" : ""} onClick={() => setPage(id)} title={label}>
                <Icon name={icon} size={17} /><span>{label}</span>
              </button>
            ))}
          </div>
        ))}
        <div className="db-nav-foot">
          <div className="db-src" title={doc.fingerprint}>{doc.fingerprint}</div>
        </div>
      </nav>
      <main className="db-main" onClick={expand}>
        <div className="db-top">
          <button className="ui-btn icon ghost" onClick={() => setNavOpen(!navOpen)} aria-label="Toggle navigation"><Icon name="menu" size={18} /></button>
          <div className="db-title"><span>{cur[3]}</span><h1>{cur[1]}</h1></div>
          {CLOCK_PAGES.includes(page) && (
            <div className="db-ctl">
              <button className="ui-btn icon" onClick={() => setPlay(!play)} aria-label={play ? "Pause" : "Play"}><Icon name={play ? "pause" : "play"} size={14} /></button>
              <input type="range" min={0} max={T} step={0.5} value={t} onChange={(e) => { setPlay(false); setT(+e.target.value); }} aria-label="Order time" />
              <span className="mono">{fmtT(t)}</span>
            </div>
          )}
          {AGE_PAGES.includes(page) && (
            <div className="db-ctl">
              <span>Machine age</span>
              <input type="range" min={0} max={ageMax} step={1} value={age} onChange={(e) => setAge(+e.target.value)} aria-label="Machine age" />
              <span className="mono">{age} sh</span>
              <div className="ui-seg"><button className={pm ? "on" : ""} onClick={() => setPm(true)}>PM on</button><button className={!pm ? "on" : ""} onClick={() => setPm(false)}>off</button></div>
            </div>
          )}
          {/* the way back to the machine sits in the header, not at the sidebar's bottom edge (sidebars.md) */}
          <a className="ui-btn" href={BASE} title="Open the 3D twin"><Icon name="cube" size={15} /><span className="hide-sm">3D twin</span></a>
          <button className={`ui-btn db-guide-btn ${guide ? "on" : ""}`} onClick={() => showGuide(!guide)} aria-pressed={guide}
            title="What this page shows and how to read it"><Icon name="info" size={15} /> Guide</button>
          <ThemeToggle theme={theme} toggle={toggleTheme} />
        </div>
        {guide && <GuideBox page={page} onClose={() => showGuide(false)} />}
        <PageCtx.Provider value={page}>
        <div className="db-page" key={page}>
          {page === "month" && <MonthPage />}
          {page === "vision" && <VisionPage />}
          {page === "ai" && <AiPage />}
          {page === "energy" && <GridPage />}
          {page === "carbon" && <CarbonPage />}
          {page === "scheduler" && <SchedulerPage />}
          {page === "copilot" && <CopilotPage go={(p) => setPage(p as Page)} />}
          {page === "throughput" && <ThroughputPage />}
          {page === "security" && <SecurityPage />}
          {page === "hardening" && <HardeningPage />}
          {page === "validation" && <ValidationPage />}
          {page === "overview" && <Overview doc={doc} t={t} age={age} pm={pm} go={(p) => setPage(p as Page)} />}
          {page === "production" && <Production doc={doc} t={t} />}
          {page === "health" && <HealthPage h={doc.health!} age={age} pm={pm} go={(p) => setPage(p as Page)} />}
          {page === "docs-degradation" && <Suspense fallback={<div className="db-err">loading…</div>}><DegradationPage h={doc.health!} /></Suspense>}
          {page === "maintenance" && <MaintenancePage h={doc.health!} lc={doc.lifecycle} age={age} pm={pm} />}
          {page === "quality" && <Quality doc={doc} t={t} />}
          {page === "alarms" && <Alarms doc={doc} />}
          {page === "engineering" && <Engineering doc={doc} />}
          {page === "data" && <Data doc={doc} src={src} />}
        </div>
        </PageCtx.Provider>
        {page !== "copilot" && (
          <>
            <button className={`ch-fab ${askOpen ? "on" : ""}`} onClick={() => setAskOpen(!askOpen)} aria-expanded={askOpen} title="Ask about this page">
              <Icon name={askOpen ? "chevron" : "info"} size={16} /> {askOpen ? "Close" : "Ask"}</button>
            {askOpen && (
              <aside className="ch-dock" aria-label="Ask about this page">
                <div className="ch-dock-h"><b>Ask · {cur[1]}</b><button className="ui-btn ghost" onClick={() => setPage("copilot")}>full page</button></div>
                <Chat key={page} page={page} go={(p) => { setPage(p as Page); }} age={age} pm={pm} compact />
              </aside>
            )}
          </>
        )}
        <p className="db-foot">Simulated from the twin's models; values marked assumed are listed on the blueprint sheets. Click any note to expand it.</p>
      </main>
    </div>
  );
}
