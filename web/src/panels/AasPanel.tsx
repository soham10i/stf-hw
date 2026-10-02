// Upgrade 14: the Asset Administration Shells (IEC 63278) of the cell, its parts and its AI
// models - generated from the model by stf-cad/hbw/aas, each submodel from its IDTA template.
import { useMemo, useState } from "react";
import { useJson } from "../shared/data";
import { Empty, Stat } from "./kit";

const BASE = import.meta.env.BASE_URL;

/* eslint-disable @typescript-eslint/no-explicit-any */
type El = any;
type Env = { assetAdministrationShells: El[]; submodels: El[] };
type Index = {
  shells: { id: string; name: string; kind: string; submodels: string[] }[];
  counts: { shells: number; submodels: number; elements: number };
  extensions: string[]; fails: string[]; files: number; mutants: { id: string; caught: boolean }[];
  templates: Record<string, string>;
};

const kids = (e: El): El[] => e.statements ?? (Array.isArray(e.value) && e.modelType !== "MultiLanguageProperty" ? e.value : []) ?? [];
const sem = (e: El) => e.semanticId?.keys?.[0]?.value ?? "";
const text = (v: { language: string; text: string }[] | undefined) => v?.find((x) => x.language.startsWith("en"))?.text ?? v?.[0]?.text ?? "";
const short = (t: string) => ({ SubmodelElementCollection: "SMC", SubmodelElementList: "SML", MultiLanguageProperty: "MLP",
  RelationshipElement: "Rel", ReferenceElement: "Ref" } as Record<string, string>)[t] ?? t;

function Value({ e, onAsset }: { e: El; onAsset: (id: string) => void }) {
  switch (e.modelType) {
    case "Property": return <span className="aas-v">{e.value}</span>;
    case "MultiLanguageProperty": return <span className="aas-v">{text(e.value)}</span>;
    case "File": return e.value ? <a className="aas-v" href={e.value} target="_blank" rel="noopener noreferrer">{e.value.split("/").pop()}</a> : null;
    case "ReferenceElement": return <span className="aas-v">{e.value?.keys?.at(-1)?.value}</span>;
    case "RelationshipElement": return <span className="aas-v">{e.first?.keys?.at(-1)?.value} → {e.second?.keys?.at(-1)?.value}</span>;
    case "Entity": return e.globalAssetId
      ? <button className="aas-link" onClick={() => onAsset(e.globalAssetId)}>{e.entityType === "SelfManagedEntity" ? "shell" : ""} ↗</button>
      : <span className="aas-v muted">{e.entityType}</span>;
    default: return null;
  }
}

function Node({ e, i, depth, onAsset }: { e: El; i?: number; depth: number; onAsset: (id: string) => void }) {
  const ch = kids(e);
  const label = e.idShort ?? `[${i}]`;
  const head = (
    <>
      <b title={sem(e)}>{label}</b><em>{short(e.modelType)}</em>
      {e.modelType === "Entity" && e.statements?.find((s: El) => s.idShort === "BulkCount") &&
        <span className="aas-v">× {e.statements.find((s: El) => s.idShort === "BulkCount").value}</span>}
      <Value e={e} onAsset={onAsset} />
    </>
  );
  if (!ch.length) return <div className="aas-row">{head}</div>;
  return (
    <details className="aas-node" open={depth < 1}>
      <summary className="aas-row">{head}<i>{ch.length}</i></summary>
      <div className="aas-kids">{ch.map((c, k) => <Node key={k} e={c} i={k} depth={depth + 1} onAsset={onAsset} />)}</div>
    </details>
  );
}

export function AasPanel() {
  const { data: ix, error } = useJson<Index>("aas/index.json");
  const { data: env } = useJson<Env>("aas/stf.aas.json");
  const [shellId, setShellId] = useState<string | null>(null);
  const [smName, setSm] = useState("Nameplate");
  const byAsset = useMemo(() => Object.fromEntries((env?.assetAdministrationShells ?? []).map((s) => [s.assetInformation.globalAssetId, s.id])), [env]);
  if (error) return <Empty text="No shells: run aas/build.py." />;
  if (!ix || !env) return <Empty text="loading…" />;
  const sid = shellId ?? ix.shells[0].id;
  const shell = env.assetAdministrationShells.find((s) => s.id === sid)!;
  const sms = shell.submodels.map((r: El) => env.submodels.find((s) => s.id === r.keys[0].value)).filter(Boolean);
  const sm = sms.find((s: El) => s.idShort === smName) ?? sms[0];
  const caught = ix.mutants.filter((m) => m.caught).length;
  const groups: [string, (k: string) => boolean][] = [["Cell", (k) => k === "Instance"], ["Parts and models", (k) => k === "Type"]];
  const goAsset = (a: string) => { if (byAsset[a]) { setShellId(byAsset[a]); setSm("Nameplate"); } };

  return (
    <div className="np aas">
      <div className="np-head">
        <div><b>Asset Administration Shells</b><span>IEC 63278, every submodel from its IDTA template</span></div>
        <a className="ui-btn" href={`${BASE}aas/stf.aasx`} download>AASX</a>
      </div>
      <div className="np-stats">
        <Stat label="Shells" value={`${ix.counts.shells}`} sub={`${ix.counts.submodels} submodels · ${ix.counts.elements} elements`} />
        <Stat label="AAS v3 violations" value={`${ix.fails.length}`} sub="aas-core3.0 verification" tone={ix.fails.length ? "bad" : "ok"} />
        <Stat label="IDTA templates" value={`${Object.keys(ix.templates).length}`} sub="every element conforms" tone="ok" />
        <Stat label="Mutants caught" value={`${caught}/${ix.mutants.length}`} sub="the checks can fail" tone={caught === ix.mutants.length ? "ok" : "bad"} />
      </div>

      <select className="ui-select" value={sid} onChange={(e) => { setShellId(e.target.value); setSm("Nameplate"); }} aria-label="Shell">
        {groups.map(([g, f]) => (
          <optgroup key={g} label={g}>{ix.shells.filter((s) => f(s.kind)).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>
        ))}
      </select>
      <p className="aas-desc">{text(shell.description)}</p>
      <div className="aas-ids"><span>AAS</span><code>{shell.id}</code><span>asset</span><code>{shell.assetInformation.globalAssetId}</code></div>

      <div className="plc-speed aas-tabs" role="tablist">
        {sms.map((s: El) => <button key={s.id} className={s === sm ? "on" : ""} onClick={() => setSm(s.idShort)}>{s.idShort}</button>)}
      </div>
      {sm && (
        <div className="aas-tree">
          <div className="aas-sem" title="semanticId: the template this submodel instantiates">{sem(sm)}</div>
          {sm.submodelElements.map((e: El, k: number) => <Node key={k} e={e} depth={0} onAsset={goAsset} />)}
        </div>
      )}
      <p className="np-foot">Hover a name for its semanticId; ↗ opens a part's own shell. The part shells are compiled by this project
        from fischertechnik's public datasheets and booklet, not issued by fischertechnik. Four of the eight published templates fail the
        metamodel's own checks; the generator cleans what an instance would inherit. <a href={`${BASE}aas/stf.aas.json`} download>JSON</a></p>
    </div>
  );
}
