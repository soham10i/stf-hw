"""
Upgrade 14 - instantiate IDTA submodel templates.

A submodel template (aas/idta/*.json, IDTA, CC BY 4.0) lists every element a
submodel may have: its idShort, type, semanticId and cardinality (One,
ZeroToOne, ZeroToMany, OneToMany). instantiate() copies the template and fills
it from a plain Python spec that mirrors the idShorts:

  Property            "value"                      (or {"value": ..., "valueType": ...})
  MultiLanguageProperty  "text" (en) or {"en": ..., "de": ...}
  File                "url" or {"value": url, "contentType": ...}
  SubmodelElementCollection / Entity   {child idShort: spec, ...}
  SubmodelElementList  [item spec, ...]            (items are copies of the template's item)
  a repeatable element  [spec, ...]                (each may rename itself with "_idShort")
  ReferenceElement / RelationshipElement / Range   the metamodel's own fields

Every element in the result comes from the template, with its semanticId, so
the submodel conforms by construction: a mandatory element left out is an
error, an optional one left out is dropped, an unknown key is an error. Where
a template is open by design (Arbitrary* elements, the Record of a time
series), "_new" adds an element the template does not list; conformance()
reports those as extensions.
"""
import copy

MANDATORY = ("One", "OneToMany")
MANY = ("ZeroToMany", "OneToMany")
META = ("SMT/Cardinality", "Cardinality", "Multiplicity", "SMT/AllowedIdShort", "SMT/EitherOr",
        "SMT/RequiredLang", "SMT/AllowedValue", "SMT/DefaultValue", "SMT/ExampleValue", "SMT/AccessMode",
        "SMT/FormChoices", "SMT/FormTitle", "SMT/FormInfo", "SMT/FormUrl")


class TemplateError(ValueError):
    pass


def cardinality(e):
    for q in e.get("qualifiers") or []:
        t = q.get("type", "")
        if t.endswith("Cardinality") or t == "Multiplicity":
            return q.get("value", "One")
    return "One"


def children(e):
    t = e.get("modelType")
    if t == "Entity":
        return e.get("statements") or []
    if t in ("SubmodelElementCollection", "SubmodelElementList"):
        return e.get("value") or []
    if t == "Submodel":
        return e.get("submodelElements") or []
    return []


def _set_children(e, kids):
    t = e["modelType"]
    key = {"Entity": "statements", "Submodel": "submodelElements"}.get(t, "value")
    if kids:
        e[key] = kids
    else:
        e.pop(key, None)


def _one_per_language(texts):
    """Several published templates tag two texts with one language (e.g. "Klassenname" as en),
    which the metamodel forbids: keep the first text of each language."""
    seen, out = set(), []
    for t in texts:
        if t.get("language") not in seen:
            seen.add(t.get("language"))
            out.append(t)
    return out


def _strip(e):
    """A template element made an instance: no template qualifiers, no example values, and
    no duplicate languages in its texts."""
    e = copy.deepcopy(e)
    for k in ("description", "displayName"):
        if e.get(k):
            e[k] = _one_per_language(e[k])
    q = [x for x in e.get("qualifiers") or [] if x.get("kind") != "TemplateQualifier"
         and not any(x.get("type", "").startswith(m) for m in META)]
    if q:
        e["qualifiers"] = q
    else:
        e.pop("qualifiers", None)
    if e["modelType"] in ("Property", "MultiLanguageProperty", "File", "Blob", "ReferenceElement", "Range"):
        for k in ("value", "min", "max", "valueId"):
            e.pop(k, None)
    return e


def _leaf(e, spec, path):
    t = e["modelType"]
    if isinstance(spec, dict) and "_value" in spec:
        spec = spec["_value"]
    if t == "Property":
        if isinstance(spec, dict):
            e["value"] = str(spec["value"])
            if "valueType" in spec:
                e["valueType"] = spec["valueType"]
        else:
            e["value"] = str(spec).lower() if isinstance(spec, bool) else str(spec)
    elif t == "MultiLanguageProperty":
        d = spec if isinstance(spec, dict) else {"en": spec}
        e["value"] = [{"language": k, "text": str(v)} for k, v in d.items()]
    elif t == "File":
        d = spec if isinstance(spec, dict) else {"value": spec}
        e["value"] = d["value"]
        e["contentType"] = d.get("contentType") or content_type(d["value"])
    elif t == "ReferenceElement":
        e["value"] = spec
    elif t == "RelationshipElement":
        e["first"], e["second"] = spec["first"], spec["second"]
    elif t == "Range":
        e["min"], e["max"] = str(spec["min"]), str(spec["max"])
    else:
        raise TemplateError(f"{path}: no leaf filling for {t}")
    return e


def content_type(url):
    ext = url.rsplit(".", 1)[-1].lower()
    return {"pdf": "application/pdf", "png": "image/png", "json": "application/json", "csv": "text/csv",
            "glb": "model/gltf-binary", "step": "model/step", "stp": "model/step", "onnx": "application/octet-stream",
            "md": "text/markdown", "st": "text/plain", "wasm": "application/wasm", "aasx": "application/asset-administration-shell-package"
            }.get(ext, "application/octet-stream")


def instantiate(tpl, spec, path=""):
    """One template element (or submodel) filled from spec."""
    path = f"{path}/{tpl.get('idShort') or '[]'}"
    e = _strip(tpl)
    t = e["modelType"]
    if isinstance(spec, dict):
        if "_idShort" in spec:
            e["idShort"] = spec["_idShort"]
        if "_semanticId" in spec:
            e["semanticId"] = {"type": "ExternalReference", "keys": [{"type": "GlobalReference", "value": spec["_semanticId"]}]}
        if "_description" in spec:
            e["description"] = [{"language": "en", "text": spec["_description"]}]
        elif (tpl.get("idShort") or "").startswith("Arbitrary") or "_idShort" in spec:
            e.pop("description", None)          # the template's notes about the placeholder, not about this element
        if t == "Entity":
            e["entityType"] = spec.get("_entityType", e.get("entityType", "CoManagedEntity"))
            if spec.get("_globalAssetId"):
                e["globalAssetId"] = spec["_globalAssetId"]
            else:
                e.pop("globalAssetId", None)
            e.pop("specificAssetIds", None)
    if t == "SubmodelElementList":
        proto = (tpl.get("value") or [None])[0]
        if proto is None:
            raise TemplateError(f"{path}: the template list has no item")
        items = spec if isinstance(spec, list) else spec.get("_items", [])
        kids = []
        for i, s in enumerate(items):
            k = instantiate(proto, s, f"{path}[{i}]")
            k.pop("idShort", None)                      # AASd-120: no idShort inside a list
            kids.append(k)
        _set_children(e, kids)
        return e
    if t in ("SubmodelElementCollection", "Entity", "Submodel"):
        spec = spec or {}
        known = {c.get("idShort") for c in children(tpl)}
        for k in spec:
            if not k.startswith("_") and k not in known:
                raise TemplateError(f"{path}: '{k}' is not in the template (use _new for an open template)")
        kids = []
        for c in children(tpl):
            k, card = c.get("idShort"), cardinality(c)
            if k == tpl.get("idShort") and not children(c):
                # a recursive element (a BoM Node inside a Node): the template defines it once
                c = dict(tpl, qualifiers=c.get("qualifiers"))
            s = spec.get(k)
            if s is None:
                if card in MANDATORY:
                    raise TemplateError(f"{path}/{k}: mandatory ({card}) and not filled")
                continue
            if card in MANY and isinstance(s, list) and c["modelType"] != "SubmodelElementList":
                if card == "OneToMany" and not s:
                    raise TemplateError(f"{path}/{k}: needs at least one")
                kids += [instantiate(c, x, path) for x in s]
            else:
                kids.append(instantiate(c, s, path))
        kids += spec.get("_new", [])
        ids = [x.get("idShort") for x in kids]
        dup = {x for x in ids if ids.count(x) > 1}
        if dup:
            raise TemplateError(f"{path}: idShorts not unique {sorted(dup)} (rename with _idShort)")
        _set_children(e, kids)
        return e
    return _leaf(e, spec, path)


def submodel(template_env, spec, sm_id, id_short=None):
    """A whole submodel from a template environment (the IDTA JSON)."""
    tpl = template_env["submodels"][0]
    sm = instantiate(tpl, spec)
    sm["id"] = sm_id
    sm["kind"] = "Instance"
    if id_short:
        sm["idShort"] = id_short
    sm.pop("administration", None)
    return sm


# ------------------------------------------------------------- conformance
def _sem(e):
    k = (e.get("semanticId") or {}).get("keys") or []
    return k[0]["value"] if k else None


def conformance(instance, template):
    """An independent check of an instance against its template: every mandatory element present,
    every element's idShort and semanticId the template's. Returns (errors, extensions)."""
    errs, ext = [], []

    def walk(inst, tpl, path):
        tk = {c.get("idShort"): (dict(tpl, qualifiers=c.get("qualifiers")) if c.get("idShort") == tpl.get("idShort")
                                 and not children(c) else c) for c in children(tpl)}
        proto = children(tpl)[0] if tpl.get("modelType") == "SubmodelElementList" and children(tpl) else None
        ik = children(inst)
        for c in tk.values():
            if tpl.get("modelType") == "SubmodelElementList":
                break
            n = sum(1 for x in ik if x.get("idShort") == c.get("idShort") or _sem(x) == _sem(c))
            if cardinality(c) in MANDATORY and n == 0:
                errs.append(f"{path}/{c.get('idShort')}: mandatory, missing")
        for x in ik:
            if proto is not None:
                t = proto
            else:
                t = tk.get(x.get("idShort")) or next((c for c in tk.values() if _sem(c) == _sem(x) and _sem(x)), None)
            if t is None:
                generic = next((c for c in tk.values() if (c.get("idShort") or "").startswith("Arbitrary")
                                and c["modelType"] == x["modelType"]), None)
                if generic is not None:
                    walk(x, generic, f"{path}/{x.get('idShort')}")
                else:
                    ext.append(f"{path}/{x.get('idShort')}")
                continue
            if t["modelType"] != x["modelType"]:
                errs.append(f"{path}/{x.get('idShort')}: {x['modelType']}, template says {t['modelType']}")
            if _sem(t) and _sem(x) != _sem(t) and not (t.get("idShort") or "").startswith("Arbitrary"):
                errs.append(f"{path}/{x.get('idShort')}: semanticId {_sem(x)}, template says {_sem(t)}")
            walk(x, t, f"{path}/{x.get('idShort') or '[]'}")

    if _sem(instance) != _sem(template):
        errs.append(f"submodel semanticId {_sem(instance)}, template says {_sem(template)}")
    walk(instance, template, instance.get("idShort"))
    return errs, ext
