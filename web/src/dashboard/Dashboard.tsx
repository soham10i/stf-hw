// The STF operations dashboard: a page of its own, separate from the 3D twin.
// It reads the newest upgrade export (up7, else up6) - the PLC's run (U4), the
// commissioning results (U5), the condition-monitoring model (U6) and the
// lifecycle checks (U7). Nothing here is typed in.
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { motion, MotionConfig } from "motion/react";
import { useCadDoc } from "../shared/model";
import { fmtT, makespan } from "../shared/hmi";
import { maxShifts } from "../shared/health";
import { HealthPage } from "./Health";
import { MaintenancePage } from "./Maintenance";
import { MonthPage } from "./Month";
import { AiPage } from "./Ai";
import { PdmPage } from "./Pdm";
import { GridPage } from "./Grid";
import { ThroughputPage } from "./Throughput";
import { SecurityPage } from "./Security";
import { HardeningPage, ValidationPage } from "./Assurance";
import { VisionPage } from "./Vision";
import { CarbonPage } from "./Carbon";
import { ProcessPage } from "./Process";
import { SchedulerPage } from "./Scheduler";
import { CopilotPage } from "./Copilot";
import { Chat } from "./Chat";
import { CopilotMark, Icon, ThemeMenu } from "../shared/icons";
import { StfLogo, StfMark } from "../shared/Logo";
import { useScrollMemory } from "../shared/scrollMemory";
import { useTheme } from "../shared/theme";
import { track } from "../shared/track";
import { ConsentBanner } from "./Consent";
import { NotifyMenu } from "./NotifyMenu";
import { cardHelp } from "./guide";
import { DocsPage, type DocTarget } from "./docs/DocsPage";


// the docs pages carry KaTeX: loaded when opened
const DegradationPage = lazy(() => import("./Degradation").then((m) => ({ default: m.DegradationPage })));

const BASE = import.meta.env.BASE_URL;
const PAGES = [
  ["overview", "Overview", "overview", "Operate"], ["production", "Production", "factory", "Operate"],
  ["quality", "Quality & trace", "seal", "Operate"], ["vision", "Vision QC", "viewfinder", "Operate"], ["alarms", "Alarms", "bell", "Operate"], ["copilot", "Copilot", "copilot", "Operate"],
  ["health", "Health", "pulse", "Maintain"], ["maintenance", "Maintenance", "wrench", "Maintain"],
  ["month", "Two months", "calendar", "Analyse"], ["throughput", "Throughput", "gauge", "Analyse"], ["process", "Oven process", "zap", "Analyse"], ["scheduler", "Learned scheduler", "shuffle", "Analyse"],
  ["energy", "Energy & grid", "bolt", "Analyse"], ["carbon", "Carbon per cookie", "leaf", "Analyse"], ["security", "OT security", "shieldlock", "Analyse"],
  ["hardening", "Defence in depth", "layers", "Analyse"],
  ["engineering", "Engineering", "cog", "Engineer"], ["validation", "Validation", "checklist", "Engineer"], ["data", "Data", "database", "Engineer"],
  ["docs", "Documentation", "book", "Docs"], ["docs-degradation", "Hardware degradation", "pulse", "Docs"],
] as const;
// the Overview shows the live twin instead of a replay: its header has no clock or age slider
const CLOCK_PAGES = ["production", "quality"];
const AGE_PAGES = ["health", "maintenance"];
type Page = (typeof PAGES)[number][0];
/** what is on screen: a page, or the Maintenance page's AI tab (its own guide, copilot context
    and link, ?p=ai, as when it was a page) */
type View = Page | "ai" | "pdm";

function useDoc() {
  const { doc, err } = useCadDoc();
  return { doc: doc && doc.control && doc.vc && doc.health ? doc : null, src: "up12", err };
}

// --------------------------------------------------------------- shared
import { PageCtx, GuideBox, HelpTips, helpDot } from "./ui";
import { Overview, Production, Quality, Alarms } from "./Operate";
import { Engineering, Data } from "./Engineer";

// the sliding "you are here" highlight of the nav and the copilot's tabs: one shared spring
const PILL = { type: "spring", stiffness: 500, damping: 40 } as const;

// ----------------------------------------------------------------- shell
export function Dashboard() {
  const { doc, src, err } = useDoc();
  const first = new URLSearchParams(location.search).get("p");
  const [page, setPageOnly] = useState<Page>(() => (first === "ai" || first === "pdm" ? "maintenance" : (first as Page)) || "overview");
  // Maintenance: the service plan from the rules, the pre-failure window (the statistical
  // pipeline), or the neural network's predictions
  const [mtab, setMtab] = useState<"plan" | "pdm" | "ai">(first === "ai" ? "ai" : first === "pdm" ? "pdm" : "plan");
  const setPage = (p: View) => {
    if (p === "ai" || p === "pdm") { setPageOnly("maintenance"); setMtab(p); return; }
    if (p === "maintenance") setMtab("plan");
    setPageOnly(p);
  };
  const view: View = page === "maintenance" && mtab !== "plan" ? mtab : page;
  // usage traction, consent-gated (shared/track.ts): each page the visitor looks at is one beacon
  useEffect(() => { track(view); }, [view]);
  // the Docs page's document, heading or cited line (?p=docs&f=docs/plc/README.md&a=...&l=...);
  // an answer's source opens it from anywhere (the copilot's citations send stf:open-doc)
  const q0 = new URLSearchParams(location.search);
  const [docAt, setDocAt] = useState<DocTarget>(() => ({ file: q0.get("f") || "docs/guide/README.md", anchor: q0.get("a") || undefined,
    line: q0.get("l") ? Number(q0.get("l")) : undefined }));
  const openDoc = (t: DocTarget) => { setDocAt(t); setPageOnly("docs"); };
  useEffect(() => {
    const on = (e: Event) => openDoc((e as CustomEvent<DocTarget>).detail);
    window.addEventListener("stf:open-doc", on);
    return () => window.removeEventListener("stf:open-doc", on);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [t, setT] = useState(0);
  const [play, setPlay] = useState(false);  // nothing runs until the user presses play
  const [age, setAge] = useState(0);
  const [pm, setPm] = useState(true);
  const { theme, setTheme } = useTheme();
  // the page's guide opens on request, as a popover from its button
  const [guide, setGuide] = useState(false);
  const [navOpen, setNavOpen] = useState(() => window.innerWidth > 900);
  // the copilot opens as an inspector beside the page or as a floating chatbot
  const [askOpen, setAskOpen] = useState(() => { try { return localStorage.getItem("stf.db.ask") === "1"; } catch { return false; } });
  const showAsk = (v: boolean) => { setAskOpen(v); try { localStorage.setItem("stf.db.ask", v ? "1" : "0"); } catch { /* private mode */ } };
  const [pinned, setPinned] = useState(() => { try { return localStorage.getItem("stf.db.pinned") === "1"; } catch { return false; } });
  const togglePinned = (v: boolean) => { setPinned(v); try { localStorage.setItem("stf.db.pinned", v ? "1" : "0"); } catch { /* private mode */ } };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && askOpen && !pinned) {
        showAsk(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [askOpen, pinned]);
  const T = doc?.control ? makespan(doc.control) : 1;
  useEffect(() => {
    if (!play || !doc) return;
    const id = window.setInterval(() => setT((x) => (x + 2 >= T ? 0 : x + 2)), 100);
    return () => window.clearInterval(id);
  }, [play, T, doc]);
  // each page opens at the top on its first visit after a load, and where it was left after that
  // (native scrolling: no smooth-scroll loop running every frame)
  useScrollMemory(view === "docs" ? `docs:${docAt.file}` : view);
  useEffect(() => {
    const q = new URLSearchParams({ p: view });
    if (view === "docs") {
      q.set("f", docAt.file);
      if (docAt.anchor) q.set("a", docAt.anchor);
      if (docAt.line) q.set("l", String(docAt.line));
    }
    history.replaceState(null, "", `?${q}`);
  }, [view, docAt]);
  // the pages that build their own sections (Month, AI, Energy, Throughput, Security, Assurance)
  // get the same i-hint on each section title as Card gives, as their data loads
  useEffect(() => {
    const root = document.querySelector(".db-main");
    if (!root) return;
    const hint = () => {
      root.querySelectorAll<HTMLElement>(".db-card > h3").forEach((h) => {
        if (h.querySelector(".db-help")) return;
        const help = cardHelp(view, h.textContent ?? "");
        if (!help) return;
        h.appendChild(helpDot(help, h.textContent ?? ""));
      });
    };
    hint();
    const mo = new MutationObserver(hint);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [view, doc]);
  const ageMax = useMemo(() => (doc?.health ? maxShifts(doc.health.components) : 1), [doc]);
  if (err) return <div className="db-err">{err}</div>;
  if (!doc) return <div className="db-loading" aria-busy="true"><StfLogo className="db-loading-logo" height={64} /><b>Operations</b><span>Reading the twin's export…</span><i /></div>;
  const cur = PAGES.find((p) => p[0] === page)!;
  const groups = Array.from(new Set(PAGES.map((p) => p[3])));
  // long notes and findings open on click instead of filling the page
  const expand = (e: React.MouseEvent) => {
    const el = (e.target as HTMLElement).closest(".db-note, .hl-cap, p.db-muted, .mo-insights > div");
    if (el) el.classList.toggle("open");
  };
  return (
    <MotionConfig reducedMotion="user">
    <div className={`db ${navOpen ? "" : "nav-min"} ${askOpen && pinned && page !== "copilot" ? "ask" : ""}`}>
      <nav className="db-nav">
        <div className="db-brand">
          <StfLogo className="db-brand-logo" height={32} />
          <StfMark className="brand-mark" size={32} />
          <div><b>Operations</b><span>Live twin data</span></div>
        </div>
        <button className="db-nav-toggle" onClick={() => setNavOpen(!navOpen)} aria-expanded={navOpen}
          aria-label={navOpen ? "Collapse navigation" : "Expand navigation"}
          title={navOpen ? "Collapse the navigation" : "Expand the navigation"}>
          <Icon name="menu" size={16} /><span>{navOpen ? "Collapse" : "Expand"}</span>
        </button>
        <div className="db-nav-scroll">
        {groups.map((g) => (
          <div key={g} className="db-group">
            <div className="db-group-h">{g}</div>
            {PAGES.filter((p) => p[3] === g).map(([id, label, icon]) => (
              <button key={id} className={id === page ? "on" : ""} onClick={() => setPage(id)} title={label}>
                {id === page && <motion.span layoutId="db-nav-pill" className="db-nav-pill" transition={PILL} />}
                <Icon name={icon} size={17} /><span>{label}</span>
              </button>
            ))}
          </div>
        ))}
        </div>
      </nav>
      <main className="db-main" onClick={expand}>
        <div className="db-top">
          <div className="db-title"><span>{cur[3]}</span>
            <h1><motion.span key={view} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: "easeOut" }}>{cur[1]}</motion.span></h1></div>
          {/* the way back to the machine sits in the header, not at the sidebar's bottom edge (sidebars.md) */}
          <a className="ui-btn" href={BASE} title="Open the 3D twin"><Icon name="cube" size={15} /><span className="hide-sm">3D twin</span></a>
          <div className="db-guide-anchor">
            <button className={`ui-btn db-guide-btn ${guide ? "on" : ""}`} onClick={() => setGuide(!guide)} aria-expanded={guide}
              title="How to read this page, and the terms it uses"><Icon name="info" size={15} /><span className="hide-sm">Guide</span></button>
            {guide && <GuideBox page={view} onClose={() => setGuide(false)} />}
          </div>
          {page !== "copilot" && (
            <button className={`ui-btn db-ask-btn ${askOpen ? "on" : ""}`} onClick={() => showAsk(!askOpen)} aria-expanded={askOpen}
              title="Ask the copilot about this page"><Icon name="copilot" size={15} />Ask</button>
          )}
          <NotifyMenu />
          <ThemeMenu theme={theme} setTheme={setTheme} />
          {(CLOCK_PAGES.includes(view) || AGE_PAGES.includes(view)) && (
            // the page's own controls: a second row of the header, so the title row never wraps
            <div className="db-tools">
              {CLOCK_PAGES.includes(view) && (
                <div className="db-ctl">
                  <span>Order</span>
                  <button className="ui-btn icon" onClick={() => setPlay(!play)} aria-label={play ? "Pause" : "Play"}><Icon name={play ? "pause" : "play"} size={14} /></button>
                  <input type="range" min={0} max={T} step={0.5} value={t} onChange={(e) => { setPlay(false); setT(+e.target.value); }} aria-label="Order time" />
                  <span className="mono">{fmtT(t)}</span>
                </div>
              )}
              {AGE_PAGES.includes(view) && (
                <div className="db-ctl">
                  <span>Machine age</span>
                  <input type="range" min={0} max={ageMax} step={1} value={age} onChange={(e) => setAge(+e.target.value)} aria-label="Machine age" />
                  <span className="mono">{age} sh</span>
                  <div className="ui-seg" title="Preventive maintenance: parts serviced on schedule, or run until they fail"><button className={pm ? "on" : ""} onClick={() => setPm(true)}>PM on</button><button className={!pm ? "on" : ""} onClick={() => setPm(false)}>off</button></div>
                </div>
              )}
            </div>
          )}
        </div>
        {/* the copilot explains itself in its empty chat: its page gives the room to the conversation */}
        {page === "maintenance" && (
          <div className="ui-seg db-tabs" role="tablist" aria-label="Maintenance">
            <button role="tab" aria-selected={mtab === "plan"} className={mtab === "plan" ? "on" : ""} onClick={() => setMtab("plan")}>Service plan</button>
            <button role="tab" aria-selected={mtab === "pdm"} className={mtab === "pdm" ? "on" : ""} onClick={() => setMtab("pdm")}>Pre-failure window</button>
            <button role="tab" aria-selected={mtab === "ai"} className={mtab === "ai" ? "on" : ""} onClick={() => setMtab("ai")}>AI predictions</button>
          </div>
        )}
        <PageCtx.Provider value={view}>
        <div className="db-page" key={view} data-view={view}>
          {page === "month" && <MonthPage />}
          {page === "vision" && <VisionPage />}
          {view === "ai" && <AiPage />}
          {view === "pdm" && <PdmPage />}
          {page === "energy" && <GridPage />}
          {page === "carbon" && <CarbonPage />}
          {page === "process" && <ProcessPage />}
          {page === "scheduler" && <SchedulerPage />}
          {page === "copilot" && <CopilotPage go={(p) => setPage(p as View)} />}
          {page === "throughput" && <ThroughputPage />}
          {page === "security" && <SecurityPage />}
          {page === "hardening" && <HardeningPage />}
          {page === "validation" && <ValidationPage />}
          {page === "overview" && <Overview doc={doc} t={t} age={age} pm={pm} go={(p) => setPage(p as View)} />}
          {page === "production" && <Production doc={doc} t={t} />}
          {page === "health" && <HealthPage h={doc.health!} age={age} pm={pm} go={(p) => setPage(p as View)} />}
          {page === "docs" && <DocsPage doc={doc} target={docAt} open={openDoc} />}
          {page === "docs-degradation" && <Suspense fallback={<div className="db-err">loading…</div>}><DegradationPage h={doc.health!} /></Suspense>}
          {view === "maintenance" && <MaintenancePage h={doc.health!} lc={doc.lifecycle} age={age} pm={pm} />}
          {page === "quality" && <Quality doc={doc} t={t} />}
          {page === "alarms" && <Alarms doc={doc} />}
          {page === "engineering" && <Engineering doc={doc} />}
          {page === "data" && <Data doc={doc} src={src} />}
        </div>
        </PageCtx.Provider>
      </main>
      {/* Pinned side panel: docks and consumes the 400px column space */}
      {askOpen && pinned && page !== "copilot" && (
        <aside className="db-inspector" aria-label="Ask about this page">
          <div className="db-inspector-h">
            <span className="db-inspector-ico"><CopilotMark size={17} /></span>
            <div><b>Ask Copilot</b><span>about {cur[1]}</span></div>
            <button className="ui-btn icon ghost on" onClick={() => togglePinned(false)} title="Unpin to floating window" aria-label="Unpin to floating window">
              <Icon name="pin" size={15} className="db-pinned-icon" />
            </button>
            <button className="ui-btn ghost" onClick={() => setPage("copilot")} title="Open the copilot's own page, with your history">
              <Icon name="external" size={13} /><span className="hide-sm">Full</span>
            </button>
            <button className="ui-btn icon ghost" onClick={() => showAsk(false)} aria-label="Close" title="Close"><Icon name="close" size={15} /></button>
          </div>
          <Chat key={view} page={view} go={(p) => { setPage(p as View); }} age={age} pm={pm} compact />
        </aside>
      )}

      {/* Floating chatbot window: small draggable/dockable bottom-right card */}
      {askOpen && !pinned && page !== "copilot" && (
        <aside className="db-float-chat" aria-label="Floating Copilot Chat">
          <div className="db-float-chat-h">
            <span className="db-inspector-ico"><CopilotMark size={16} /></span>
            <div><b>Ask Copilot</b><span>about {cur[1]}</span></div>
            <div className="db-float-chat-actions">
              <button className="ui-btn icon ghost" onClick={() => togglePinned(true)} title="Pin to side panel" aria-label="Pin to side panel">
                <Icon name="pin" size={15} />
              </button>
              <button className="ui-btn ghost" onClick={() => setPage("copilot")} title="Open full copilot page">
                <Icon name="external" size={13} /><span className="hide-sm">Full</span>
              </button>
              <button className="ui-btn icon ghost" onClick={() => showAsk(false)} aria-label="Close" title="Close"><Icon name="close" size={15} /></button>
            </div>
          </div>
          <div className="db-float-chat-b">
            <Chat key={view} page={view} go={(p) => { setPage(p as View); }} age={age} pm={pm} compact />
          </div>
        </aside>
      )}

      {/* Bottom right floating chatbot launcher button */}
      {page !== "copilot" && (
        <button
          className={`db-float-trigger ${askOpen ? "active" : ""}`}
          onClick={() => showAsk(!askOpen)}
          aria-expanded={askOpen}
          aria-label={askOpen ? "Close Copilot" : "Open Copilot"}
          title={askOpen ? "Close Copilot" : "Ask Copilot"}
        >
          <span className="db-float-trigger-mark">
            <CopilotMark size={20} />
            <span className="db-float-trigger-dot" aria-hidden="true" />
          </span>
          <span className="db-float-trigger-label">Ask Copilot</span>
        </button>
      )}
      <HelpTips />
      <ConsentBanner page={view} />
    </div>
    </MotionConfig>
  );
}
