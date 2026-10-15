"""
Upgrade 14, step 1 - Asset Administration Shells (IEC 63278) for the cell, its parts and its AI models.

    python3 -m aas.build          (from stf-cad/hbw; about ten seconds)

SHELLS    12, all generated from the model's own data:
            the cell (Upgrade 12)          Nameplate, TechnicalData, HierarchicalStructures (bill of
                                           material), HandoverDocumentation, CarbonFootprint, TimeSeries,
                                           Models3D
            9 fischertechnik part types    Nameplate, TechnicalData, HandoverDocumentation, Models3D
            2 AI models (U8, U15)          AIModelNameplate
SUBMODELS each instantiated from the official IDTA template (aas/idta, CC BY 4.0) by aas/smt.py, so
          every element, idShort and semanticId is the template's.
IDS       IRIs under the project's own GitHub Pages address. The part shells are compiled by this
          project from fischertechnik's public datasheets and booklet; they are not issued by
          fischertechnik and say so. No address is invented: the datasheets publish none, so the
          nameplate's AddressInformation is present and empty.
PROOFS    (1) the environment passes aas-core3.0's verification of the AAS v3 metamodel (every
              constraint AASd-*), with no error;
          (2) every submodel conforms to its template (aas/smt.conformance, which walks the
              instance and the template independently of the instantiation);
          (3) every reference resolves: each HasPart points to an entity in its submodel, each
              part entity's globalAssetId is a shell in the environment, each file URL is a file in
              the repository;
          (4) the AASX package written by Eclipse BaSyx reads back with the same shells,
              submodels and element counts;
          (5) the checks can fail: five mutants (MUTANTS) are each rejected.
FOUND     Four of the eight published IDTA templates fail the AAS v3 metamodel verification
          themselves (Technical Data 32 violations, Handover Documentation 15, Digital Nameplate
          13, Bills of Material 12: duplicate languages such as "Klassenname" tagged en, idShorts
          on list items, repeated qualifier types, malformed references). smt.py cleans what an
          instance inherits from them.
Output: web/public/aas/stf.aas.json, stf.aasx and index.json (for the twin's AAS viewer).
"""
import datetime as dt
import json
import os

import aas_core3.jsonization as jsz
import aas_core3.verification as ver

from aas import smt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PUBLIC = os.path.join(ROOT, "web", "public")
OUT = os.path.join(PUBLIC, "aas")
PAGES = "https://soham10i.github.io/stf-hw/"
REPO = "https://github.com/soham10i/stf-hw/blob/main/"
PROJECT = "STF digital twin project"
TODAY = dt.date.today().isoformat()
NOW = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
SOURCE_NOTE = ("Compiled by the STF digital twin project from fischertechnik's public datasheet or booklet; "
               "not issued by fischertechnik.")

T = {k: json.load(open(os.path.join(HERE, "idta", f"{k}.json"))) for k in (
    "Digital_nameplate", "Technical_Data", "Hierarchical_Structures_enabling_Bills_of_Material",
    "Handover_Documentation", "Carbon_Footprint", "Time_Series_Data", "Provision_of_3D_Models",
    "Artificial_Intelligence_Model_Nameplate")}


def jload(rel):
    return json.load(open(os.path.join(PUBLIC, rel)))


def aas_id(slug):
    return f"{PAGES}aas/{slug}"


def asset_id(slug):
    return f"{PAGES}asset/{slug}"


def sm_id(slug, name):
    return f"{PAGES}aas/{slug}/sm/{name}"


def site(rel):
    """A file the twin serves (web/public), by its public URL."""
    return {"value": PAGES + rel, "_local": os.path.join(PUBLIC, rel)}


def repo(rel):
    """A file in the repository, by its GitHub URL."""
    return {"value": REPO + rel.replace(" ", "%20"), "_local": os.path.join(ROOT, rel)}


FILES = []          # every file URL used, with the local path it must resolve to


def f(x):
    FILES.append(x)
    return {"value": x["value"], "contentType": smt.content_type(x["value"])}


def ext_ref(url):
    return {"type": "ExternalReference", "keys": [{"type": "GlobalReference", "value": url}]}


# ------------------------------------------------------------- shared submodels
def nameplate(slug, uri, maker, designation, order_code, article=None, root=None, family=None, ptype=None,
              serial=None, year=None, software=None, extra=()):
    spec = {
        "URIOfTheProduct": uri,
        "ManufacturerName": maker,
        "ManufacturerProductDesignation": designation,
        "AddressInformation": {},           # the sources publish no address: present, and left empty
        "OrderCodeOfManufacturer": order_code,
        "AssetSpecificProperties": {"ArbitraryProperty": [{"_idShort": k, "_semanticId": f"{PAGES}cd/{k}", "_value": v}
                                                          for k, v in extra]} if extra else None,
    }
    for k, v in (("ProductArticleNumberOfManufacturer", article), ("ManufacturerProductRoot", root),
                 ("ManufacturerProductFamily", family), ("ManufacturerProductType", ptype),
                 ("SerialNumber", serial), ("YearOfConstruction", year), ("SoftwareVersion", software)):
        if v:
            spec[k] = v
    return smt.submodel(T["Digital_nameplate"], {k: v for k, v in spec.items() if v is not None}, sm_id(slug, "Nameplate"))


def technical_data(slug, maker, designation, article, sections, statements=()):
    """sections: {section name: [(idShort, label, value)]}"""
    def prop(k, label, v):
        return {"_idShort": k, "_semanticId": f"{PAGES}cd/{k}", "_description": label, "_value": v}
    spec = {
        "GeneralInformation": {"ManufacturerName": maker, "ManufacturerProductDesignation": designation,
                               "ManufacturerArticleNumber": article, "ManufacturerOrderCode": article},
        "TechnicalPropertyAreas": [{"Section": [{"_idShort": name, "ArbitraryProperty": [prop(*p) for p in props]}
                                                for name, props in sections.items()]}],
        "FurtherInformation": {"TextStatement": [{"_idShort": f"TextStatement{i:02d}", "_value": s}
                                                 for i, s in enumerate(statements, 1)], "ValidDate": TODAY}
        if statements else None,
    }
    return smt.submodel(T["Technical_Data"], {k: v for k, v in spec.items() if v is not None}, sm_id(slug, "TechnicalData"))


def handover(slug, docs):
    """docs: [(identifier, class id, class name, title, description, language, file)]"""
    items = []
    for ident, cid, cname, title, desc, lang, fl in docs:
        items.append({
            "DocumentIds": [{"DocumentDomainId": PROJECT, "DocumentIdentifier": ident, "DocumentIsPrimary": True}],
            "DocumentClassifications": [{"ClassId": cid, "ClassName": cname, "ClassificationSystem": "VDI2770:2020"}],
            "DocumentVersions": [{
                "Language": [lang], "Version": "1", "Title": title, "Description": desc,
                "StatusSetDate": TODAY, "StatusValue": "released",
                "OrganizationShortName": "STF", "OrganizationOfficialName": PROJECT,
                "DigitalFiles": [f(fl)]}],
        })
    return smt.submodel(T["Handover_Documentation"], {"Documents": items}, sm_id(slug, "HandoverDocumentation"))


def models3d(slug, models):
    """models: [(file id, title, file, format name, format version, qualifier, representation, preview url, bbox)]"""
    items = []
    for fid, title, fl, fmt, fver, fq, rep, preview, bbox in models:
        geo = {"Representation": rep, "LengthUnit": "mm"}
        if bbox:
            geo["CartBoundingBox"] = [{"BoundingBoxKind": "Envelope",
                                       "CartBoundingVector": dict(zip("XYZ", (f"{v:g}" for v in bbox), strict=True))}]
        items.append({
            "File": {
                "FileId": [{"FileDomainId": PROJECT, "ValueId": fid, "IsPrimary": [True]}],
                "FileVersion": [{
                    "Title": title, "FileName": fl["value"].rsplit("/", 1)[-1], "FileVersionId": "1",
                    "StatusValue": "Released", "SetDate": TODAY,
                    "PreviewFile": {"value": preview, "contentType": "text/html"},
                    "DigitalFile": f(fl),
                    "FileFormat": {"FormatName": fmt, "FormatVersion": fver, "FormatQualifier": fq},
                    "SourceApplication": {"ApplicationName": "FreeCAD (Open CASCADE) via stf-cad", "ApplicationVersion": "1.1",
                                          "ApplicationQualifier": "generated from the parametric model",
                                          "VendorOrganization": {"OrganizationName": "FreeCAD",
                                                                 "OrganizationOfficialName": "FreeCAD project"}},
                    "ProvidingOrganization": {"OrganizationName": "STF", "OrganizationOfficialName": PROJECT},
                }],
                "FileClassification": [{"ClassId": "02-02", "ClassName": "Drawings, plans", "ClassificationSystem": "VDI2770:2020"}],
            },
            "Capability": {"PosModelPurpose": ["Rendering", "VirtualCommisioning"], "Origin": "DesignEngineering"},
            "Geometry": geo,
        })
    return smt.submodel(T["Provision_of_3D_Models"], {"Model3D": items}, sm_id(slug, "Models3D"))


# ------------------------------------------------------------- the parts
def part_shells():
    comps = jload("components/components.json")["components"]
    shells = []
    for key, c in comps.items():
        slug = f"part-{key.replace('_', '-')}"
        sheet = c["datasheet"].split(" p.")[0]
        is_sheet = c["datasheet"] == sheet and not sheet.startswith("536634")
        designation = {"en": c["name"], "de": c.get("name_de") or c["name"]}
        props = [(f"Fact{i:02d}", x["label"], f"{x['value']} (source: {x['source']})") for i, x in enumerate(c["facts"], 1)]
        dims = [(f"Dim_{x['key']}", x["label"], f"{x['value']:g} mm (source: {x['source']})") for x in c["dims"]
                if isinstance(x.get("value"), (int, float))]
        use = sorted({u["module"] for u in c["used_in"]})
        sms = [
            nameplate(slug, PAGES + f"?view={key}", "fischertechnik GmbH", designation, c["ft"],
                      article=c["ft"] if c["ft"].isdigit() else None, family="fischertechnik Fabrik Simulation 24V (536634)",
                      extra=[("DataSource", f"{SOURCE_NOTE} Source: {c['datasheet']}."),
                             ("UsedInModules", ", ".join(use)), ("CountInCell", str(len(c["used_in"])))]),
            technical_data(slug, "fischertechnik GmbH", designation, c["ft"],
                           {"Facts": props, "Dimensions": dims, "Material": [("Material", "material", c.get("material") or "")]},
                           [SOURCE_NOTE, "A value marked 'photo' or 'assumed' is not from the datasheet."]),
            handover(slug, [(f"ft-{c['ft']}-datasheet", "02-01", {"en": "Technical specification", "de": "Technische Spezifikation"},
                             {"en": f"{c['name']}: {'datasheet' if is_sheet else 'booklet'} ({c['datasheet']})"},
                             {"en": "fischertechnik's own publication, as kept in the repository."},
                             "de" if not is_sheet else "en", repo(f"docs/{sheet}"))]),
            models3d(slug, [(f"{key}-step", {"en": f"{c['name']}, solid model"}, site(f"components/{c['files']['step']}"),
                             "STEP", "AP214", "ISO 10303-21", "SolidBody", PAGES + f"?view={key}", c.get("overall_mm")),
                            (f"{key}-glb", {"en": f"{c['name']}, web mesh"}, site(f"components/{c['files']['glb']}"),
                             "glTF", "2.0", "binary (.glb)", "Mesh", PAGES + f"?view={key}", c.get("overall_mm"))]),
        ]
        shells.append(shell(slug, f"{c['name']} (fischertechnik {c['ft']})", "Type", sms,
                            f"fischertechnik {c['ft']} {c['name']}. {SOURCE_NOTE}"))
    return shells, comps


# ------------------------------------------------------------- the AI models
def ai_shells():
    ml, vis = jload("ml/results.json"), jload("vision/results.json")
    out = []
    specs = [
        ("ai-predictive-maintenance", "Predictive-maintenance network (Upgrade 8)", site("ml/stf_pm_tcn.onnx"), {
            "KindOfLearning": "semi-supervised: masked-reconstruction pre-training, supervised fine-tuning, Mean Teacher",
            "Inputs": {"KindOfInput": "time series",
                       "DimensionN": [{"_idShort": "Window", "Size": str(ml["model"]["window_orders"]), "Information": "orders"},
                                      {"_idShort": "Channels", "Size": str(len(ml["model"]["inputs"])),
                                       "Information": ", ".join(ml["model"]["inputs"])}]},
            "Outputs": {"DimensionN": [{"_idShort": "RemainingLife", "Size": "1", "Result": "remaining useful life, orders"},
                                       {"_idShort": "HealthClass", "Size": "3", "Result": "healthy / degrading / critical"}]},
            "TrainingResults": {"ExampleResult": f"tested on {ml['data']['test']} unseen simulated machines; "
                                                 f"see {PAGES}ml/results.json"},
            "Type": "causal temporal convolutional network",
            "params": ml["model"]["params"]}),
        ("ai-vision-inspection", "Vision inspection network (Upgrade 15)", site("vision/stf_vision_cnn.onnx"), {
            "KindOfLearning": "supervised, on rendered images only (domain randomisation)",
            "Inputs": {"KindOfInput": "image",
                       "DimensionN": [{"_idShort": "Image", "Size": f"3x{vis['data']['size_px']}x{vis['data']['size_px']}",
                                       "Information": f"RGB, 0..1, {vis['data']['fov_mm']:g} mm field of view, grey reference in the corner"}]},
            "Outputs": {"DimensionN": [{"_idShort": "Flavour", "Size": "3", "Result": "chocolate / strawberry / vanilla"},
                                       {"_idShort": "Condition", "Size": "5", "Result": "ok / underbaked / burnt / cracked / chipped"}]},
            "TrainingResults": {"ExampleResult": f"unseen conditions: {vis['results']['shifted']['false_reject']:.0%} false rejects, "
                                                 f"{vis['results']['shifted']['escape_rate']:.1%} escapes; see {PAGES}vision/results.json"},
            "Type": "convolutional neural network",
            "params": vis["model"]["params"]}),
    ]
    for slug, name, fl, s in specs:
        FILES.append(fl)
        spec = {
            "URIOfTheProduct": PAGES + f"?panel={'ai' if 'maint' in slug else 'vision'}",
            "Version": "1.0",
            "ContactInformation": ext_ref(REPO.replace("/blob/main/", "")),
            "Storage": fl["value"],
            "KindOfLearning": s["KindOfLearning"],
            "Inputs": s["Inputs"], "Outputs": s["Outputs"], "TrainingResults": s["TrainingResults"],
            "Details": {"FileExtension": ".onnx", "AIFramework": "PyTorch 2, exported to ONNX", "ProgramLanguage": "Python"},
            "AITypeSpecificInformation": {"Hyperparameter": {"_new": [prop_new("Parameters", str(s["params"]))]},
                                          "Type": s["Type"]},
        }
        sm = smt.submodel(T["Artificial_Intelligence_Model_Nameplate"], spec, sm_id(slug, "AIModelNameplate"))
        out.append(shell(slug, name, "Type", [sm], f"{name}. Trained and tested on simulated data only."))
    return out


def prop_new(k, v, label=None):
    p = {"idShort": k, "modelType": "Property", "valueType": "xs:string", "value": v,
         "semanticId": ext_ref(f"{PAGES}cd/{k}")}
    if label:
        p["description"] = [{"language": "en", "text": label}]
    return p


# ------------------------------------------------------------- the cell
def cell_shell(parts, comps):
    slug = "stf-cell-u12"
    sil = jload("sil/sil.json")
    month, grid = jload("month/month.json"), jload("grid/grid.json")
    k = month["kpi"]
    sms = []
    sms.append(nameplate(slug, PAGES, PROJECT, {"en": "Smart Tabletop Factory, Upgrade 12 (a digital twin of fischertechnik 536634)"},
                         "STF-U12", root="Smart Tabletop Factory", family="proof-gated digital twin",
                         ptype="cell, Upgrade 12", serial="VIRTUAL-0001", year="2026", software=f"PLC program {sil['wasm_sha']}",
                         extra=[("Basis", "fischertechnik Fabrik Simulation 24V (536634), rebuilt as a model with Upgrades 1-12"),
                                ("Note", "a virtual instance: there is no physical cell")]))
    sms.append(technical_data(slug, PROJECT, {"en": "Smart Tabletop Factory, Upgrade 12"}, "STF-U12", {
        "Production": [("CookiesPerHour", "cookies per hour, simulated month", f"{k['cookies_per_h']}"),
                       ("OEE", "overall equipment effectiveness, simulated month", f"{k['oee']}"),
                       ("OrderTime", "one 12-cookie order on the compiled PLC program (Upgrade 13)", f"{sil['order_s']} s")],
        "Control": [("PlcProgram", "IEC 61131-3 Structured Text, generated", f"{sil['st_lines']} lines"),
                    ("PlcCompiler", "compiler", sil["compiler"]), ("PlcTask", "task interval", f"{sil['scan_ms']} ms")],
        "Energy": [("EnergyMonth", "electricity, simulated month", f"{grid['scenarios']['pv+battery']['load_kwh']} kWh"),
                   ("PV", "rooftop PV share, simulated month", f"{grid['scenarios']['pv+battery']['pv_kwh']} kWh")],
    }, ["Every value is from the simulated cell; see the twin for how each is proven."]))
    # bill of material: cell -> modules -> part types
    modules = {"hbw": "High-bay warehouse", "vgr": "Vacuum gripper robot", "oven": "Oven and turntable", "sorting": "Sorting line"}
    entry_ref = [{"type": "Submodel", "value": sm_id(slug, "HierarchicalStructures")}, {"type": "Entity", "value": "EntryNode"}]
    nodes = []
    for m, label in modules.items():
        kids = []
        for key, c in comps.items():
            n = sum(1 for u in c["used_in"] if u["module"] == m)
            if n:
                kids.append({"_idShort": f"{key}", "_entityType": "SelfManagedEntity",
                             "_globalAssetId": asset_id(f"part-{key.replace('_', '-')}"), "BulkCount": str(n)})
        mref = entry_ref + [{"type": "Entity", "value": m}]
        nodes.append({"_idShort": m, "_entityType": "CoManagedEntity", "_description": label, "Node": kids,
                      "HasPart": [{"_idShort": f"HasPart_{x['_idShort']}",
                                   "first": {"type": "ModelReference", "keys": mref},
                                   "second": {"type": "ModelReference", "keys": mref + [{"type": "Entity", "value": x["_idShort"]}]}}
                                  for x in kids]})
    bom = {"EntryNode": {"_entityType": "SelfManagedEntity", "_globalAssetId": asset_id(slug), "Node": nodes,
                         "HasPart": [{"_idShort": f"HasPart_{m}", "first": {"type": "ModelReference", "keys": entry_ref},
                                      "second": {"type": "ModelReference", "keys": entry_ref + [{"type": "Entity", "value": m}]}}
                                     for m in modules]},
           "ArcheType": "Full"}
    sms.append(smt.submodel(T["Hierarchical_Structures_enabling_Bills_of_Material"], bom, sm_id(slug, "HierarchicalStructures")))
    sms.append(handover(slug, [
        ("stf-upgrade-plan", "02-01", {"en": "Technical specification"}, {"en": "Upgrade plan, as built (Upgrades 1-15)"},
         {"en": "What each upgrade changed and how it is proven."}, "en", repo("docs/UPGRADE_PLAN.md")),
        ("stf-validation", "02-01", {"en": "Technical specification"}, {"en": "Validation report"},
         {"en": "Every variant re-proved, mutation tests, robustness."}, "en", repo("docs/VALIDATION.md")),
        ("stf-security", "02-01", {"en": "Technical specification"}, {"en": "Security review"},
         {"en": "Findings S1-S13 and their fixes."}, "en", repo("docs/SECURITY.md")),
        ("stf-plc-program", "02-01", {"en": "Technical specification"}, {"en": "PLC program (IEC 61131-3)"},
         {"en": "The generated Structured Text, as compiled by MatIEC."}, "en", site("sil/stf_plc.st")),
        ("ft-536634-booklet", "02-01", {"en": "Technical specification"}, {"en": "Fabrik Simulation 24V, fischertechnik booklet"},
         {"en": "fischertechnik's publication: the base the model is built from."}, "de", repo("docs/536634-Fabrik_Simulation_24V.pdf")),
        ("ft-536634-assignment", "02-02", {"en": "Drawings, plans"}, {"en": "Assignment plan (Belegungsplan)"},
         {"en": "fischertechnik's I/O assignment of the 24 V factory."}, "de",
         repo("docs/536634-Fabrik_Simulation_24V-Belegungsplan.pdf")),
    ]))
    # carbon footprint: the use phase only, from the microgrid's simulated month
    g = grid["scenarios"]["pv+battery"]
    per = g["co2_kg"] * 1000 / k["baked"]
    sms.append(smt.submodel(T["Carbon_Footprint"], {"ProductCarbonFootprints": [{
        "PcfCalculationMethods": ["GHG Protocol"],
        "PcfCO2eq": {"value": f"{per:.4f}", "valueType": "xs:decimal"},
        "ReferenceImpactUnitForCalculation": "piece",
        "QuantityOfMeasureForCalculation": "1",
        "LifeCyclePhases": ["B6 - usage phase / operational energy use"],
        "PublicationDate": NOW,
    }]}, sm_id(slug, "CarbonFootprint")))
    # time series: the simulated month's CSVs
    def seg(name, desc, rel, n, start, end, interval_s):
        return {"_idShort": name, "Name": desc, "RecordCount": str(n), "StartTime": start, "EndTime": end,
                "SamplingInterval": str(interval_s), "State": "completed", "File": f(site(rel))}
    start = month["meta"]["start"]
    end = (dt.datetime.fromisoformat(start) + dt.timedelta(days=month["meta"]["days"])).isoformat()
    lines = lambda rel: sum(1 for _ in open(os.path.join(PUBLIC, rel))) - 1   # noqa: E731
    sms.append(smt.submodel(T["Time_Series_Data"], {
        "Metadata": {"Name": "One simulated month of production", "Description": "Upgrades 6, 8 and 9: health, orders and energy",
                     "Record": {"Time": [{"_value": "0"}], "_new": [prop_new(x, "", x) for x in
                                ("component", "observed", "ewma_r", "health_index", "rul_shifts", "load_w", "co2_g_kwh")]}},
        "Segments": {"ExternalSegment": [
            seg("Sensors", "health signals per component and order", "month/sensors.csv", lines("month/sensors.csv"), start, end, 0),
            seg("Orders", "one row per order", "month/orders.csv", lines("month/orders.csv"), start, end, 0),
            seg("Energy", "the microgrid every 15 minutes", "grid/grid_15min.csv", lines("grid/grid_15min.csv"), start, end, 900)]},
    }, sm_id(slug, "TimeSeries")))
    sms.append(models3d(slug, [("cell-glb", {"en": "The cell, precise model"}, site("precise_up7.glb"), "glTF", "2.0",
                                "binary (.glb)", "Mesh", PAGES, None)]))
    return shell(slug, "Smart Tabletop Factory, Upgrade 12", "Instance", sms,
                 "The cell as the twin shows it: a virtual instance generated from the proven model.")


def shell(slug, name, kind, submodels, desc):
    return {"aas": {"id": aas_id(slug), "idShort": slug.replace("-", "_"), "modelType": "AssetAdministrationShell",
                    "description": [{"language": "en", "text": desc}], "displayName": [{"language": "en", "text": name}],
                    "administration": {"version": "1", "revision": "0", "creator": ext_ref(PAGES)},
                    "assetInformation": {"assetKind": kind, "globalAssetId": asset_id(slug)},
                    "submodels": [{"type": "ModelReference", "keys": [{"type": "Submodel", "value": s["id"]}]} for s in submodels]},
            "submodels": submodels}


# ------------------------------------------------------------- proofs
def concept_descriptions(env):
    """One concept description per project-defined semanticId (cd/...), so each is explained."""
    seen = {}

    def walk(e):
        if isinstance(e, dict):
            k = ((e.get("semanticId") or {}).get("keys") or [{}])[0].get("value", "")
            if k.startswith(PAGES + "cd/") and k not in seen:
                d = (e.get("description") or [{"text": e.get("idShort", "")}])[0]["text"]
                seen[k] = {"id": k, "idShort": k.rsplit("/", 1)[-1], "modelType": "ConceptDescription",
                           "description": [{"language": "en", "text": d}]}
            for v in e.values():
                walk(v)
        elif isinstance(e, list):
            for v in e:
                walk(v)
    walk(env["submodels"])
    return list(seen.values())


def check(env):
    fails = []
    # (1) the metamodel
    obj = jsz.environment_from_jsonable(env)
    for err in ver.verify(obj):
        fails.append(f"AAS v3: {err.path}: {err.cause}")
    # (2) the templates
    by_sem = {smt._sem(t["submodels"][0]): (k, t["submodels"][0]) for k, t in T.items()}
    ext = []
    for sm in env["submodels"]:
        name, tpl = by_sem[smt._sem(sm)]
        e, x = smt.conformance(sm, tpl)
        fails += [f"{sm['id']}: {m}" for m in e]
        ext += [f"{name}: {m}" for m in x]
    # (3) references and files
    shells = {s["assetInformation"]["globalAssetId"] for s in env["assetAdministrationShells"]}
    sms = {s["id"]: s for s in env["submodels"]}

    def resolve(keys):
        sm = sms.get(keys[0]["value"])
        cur = [sm] if sm else []
        for k in keys[1:]:
            cur = [c for p in cur for c in smt.children(p) if c.get("idShort") == k["value"]]
        return bool(cur)

    def walk(e):
        if isinstance(e, dict):
            if e.get("modelType") == "RelationshipElement":
                for side in ("first", "second"):
                    if not resolve(e[side]["keys"]):
                        fails.append(f"reference does not resolve: {e[side]['keys'][-1]['value']}")
            if e.get("modelType") == "Entity" and e.get("entityType") == "SelfManagedEntity" and e["globalAssetId"] not in shells:
                fails.append(f"BoM entity {e.get('idShort')}: no shell for {e['globalAssetId']}")
            for v in e.values():
                walk(v)
        elif isinstance(e, list):
            for v in e:
                walk(v)
    walk(env["submodels"])
    for x in FILES:
        if not os.path.exists(x["_local"]):
            fails.append(f"file not in the repository: {x['value']}")
    return fails, ext


def write_aasx(env_path, aasx_path):
    """(4) Eclipse BaSyx writes the package and reads it back."""
    from basyx.aas.adapter import aasx
    from basyx.aas.adapter.json import read_aas_json_file
    with open(env_path) as fh:
        store = read_aas_json_file(fh)
    files = aasx.DictSupplementaryFileContainer()
    with aasx.AASXWriter(aasx_path) as w:
        w.write_aas([s.id for s in store if s.__class__.__name__ == "AssetAdministrationShell"], store, files)
    from basyx.aas.model import DictIdentifiableStore
    back = DictIdentifiableStore()
    with aasx.AASXReader(aasx_path) as r:
        r.read_into(back, aasx.DictSupplementaryFileContainer())

    def count(st):
        n = {"shells": 0, "submodels": 0, "elements": 0}
        for o in st:
            t = o.__class__.__name__
            if t == "AssetAdministrationShell":
                n["shells"] += 1
            elif t == "Submodel":
                n["submodels"] += 1
                stack = list(o.submodel_element)
                while stack:
                    e = stack.pop()
                    n["elements"] += 1
                    for attr in ("value", "statement"):
                        v = getattr(e, attr, None)
                        if v is not None and not isinstance(v, (str, bytes)) and hasattr(v, "__iter__") and \
                                e.__class__.__name__ in ("SubmodelElementCollection", "SubmodelElementList", "Entity"):
                            stack.extend(v)
        return n
    return count(store), count(back)


# ---------------------------------------------------------- mutation tests
def _mut(env, fn):
    env = json.loads(json.dumps(env))
    fn(env)
    return env


def _nameplate(env):
    return next(s for s in env["submodels"] if s["idShort"] == "Nameplate")


MUTANTS = [
    ("AM1", "a mandatory element removed (OrderCodeOfManufacturer)",
     lambda e: _nameplate(e)["submodelElements"].remove(
         next(x for x in _nameplate(e)["submodelElements"] if x["idShort"] == "OrderCodeOfManufacturer"))),
    ("AM2", "a semanticId changed", lambda e: _nameplate(e)["submodelElements"][0]["semanticId"]["keys"][0].update(value="urn:wrong")),
    ("AM3", "two texts in one language", lambda e: _nameplate(e)["submodelElements"][1]["value"].append({"language": "en", "text": "x"})),
    ("AM4", "a bill-of-material entity pointing to no shell",
     lambda e: next(s for s in e["submodels"] if s["idShort"] == "HierarchicalStructures")["submodelElements"][0]
     ["statements"][0]["statements"][0].update(globalAssetId=PAGES + "asset/nothing")),
]


def mutants(env):
    """Each mutant breaks the environment one way; check() must reject every one."""
    files = list(FILES)
    out = []
    for mid, what, fn in MUTANTS:
        bad, _ = check(_mut(env, fn))
        out.append({"id": mid, "what": what, "caught": bool(bad), "by": bad[0] if bad else None})
    FILES.append({"value": PAGES + "nothing.pdf", "_local": os.path.join(PUBLIC, "nothing.pdf")})
    bad, _ = check(env)
    out.append({"id": "AM5", "what": "a file link to a file that is not there", "caught": bool(bad), "by": bad[0] if bad else None})
    FILES[:] = files
    return out


def build():
    FILES.clear()
    parts, comps = part_shells()
    shells = [cell_shell(parts, comps)] + parts + ai_shells()
    env = {"assetAdministrationShells": [s["aas"] for s in shells],
           "submodels": [sm for s in shells for sm in s["submodels"]]}
    env["conceptDescriptions"] = concept_descriptions(env)
    fails, ext = check(env)
    muts = mutants(env)
    fails += [f"mutant {m['id']} survived: {m['what']}" for m in muts if not m["caught"]]
    os.makedirs(OUT, exist_ok=True)
    env_path = os.path.join(OUT, "stf.aas.json")
    with open(env_path, "w") as fh:
        json.dump(env, fh, separators=(",", ":"))
    written, read = write_aasx(env_path, os.path.join(OUT, "stf.aasx"))
    if written != read:
        fails.append(f"AASX read-back differs: wrote {written}, read {read}")
    index = {"shells": [{"id": s["aas"]["id"], "name": s["aas"]["displayName"][0]["text"], "kind": s["aas"]["assetInformation"]["assetKind"],
                         "submodels": [sm["idShort"] for sm in s["submodels"]]} for s in shells],
             "counts": written, "extensions": ext, "fails": fails, "files": len(FILES), "mutants": muts,
             "templates": {k: smt._sem(t["submodels"][0]) for k, t in T.items()}, "built": NOW}
    with open(os.path.join(OUT, "index.json"), "w") as fh:
        json.dump(index, fh, indent=1)
    return index


if __name__ == "__main__":
    ix = build()
    print(f"{ix['counts']['shells']} shells, {ix['counts']['submodels']} submodels, {ix['counts']['elements']} elements, "
          f"{ix['files']} file links; template extensions: {len(ix['extensions'])}")
    for m in ix["mutants"]:
        print(f"  {m['id']} {m['what']}: {'caught - ' + m['by'][:90] if m['caught'] else 'SURVIVED'}")
    for x in ix["fails"]:
        print("  FAIL", x)
    print("AAS OK" if not ix["fails"] else f"AAS FAILED ({len(ix['fails'])})")
