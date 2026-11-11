"""The documentation corpus (docs/README.md): front matter on every reference document, headings
that make chunk breadcrumbs, links that resolve, and an index that holds exactly what it should."""

from __future__ import annotations

import json
import os
import re
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REFERENCE = os.path.join(ROOT, "docs", "reference")
KB = os.path.join(ROOT, "web", "public", "copilot", "kb.json")
MODULES = {
    "factory", "warehouse", "gripper-robot", "oven", "sorting-line", "machine", "plc", "twin",
    "dashboard", "guide", "maintenance", "vision", "process", "copilot", "operations",
    "architecture",
}
FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)


def reference_files() -> list[str]:
    out = []
    for root, _, files in os.walk(REFERENCE):
        out += [os.path.join(root, f) for f in files if f.endswith(".md")]
    return sorted(out)


def front_matter(path: str) -> dict[str, str]:
    m = FRONT.match(open(path, encoding="utf-8").read())
    assert m, f"{path}: no front matter"
    kv = {}
    for line in m.group(1).split("\n"):
        k, _, v = line.partition(":")
        v = v.strip()
        kv[k.strip()] = json.loads(v) if v.startswith('"') else v
    return kv


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT)


@pytest.mark.parametrize("path", reference_files(), ids=rel)
def test_every_reference_document_has_its_front_matter(path):
    fm = front_matter(path)
    assert fm.get("title") and fm.get("scope"), fm
    assert fm.get("module") in MODULES, fm.get("module")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fm.get("last_verified", "")), fm
    assert set(fm) <= {"title", "scope", "module", "last_verified", "generated_by", "index"}
    assert len(fm["scope"]) <= 260 and fm["scope"].endswith((".", ")")), fm["scope"]


@pytest.mark.parametrize("path", reference_files(), ids=rel)
def test_headings_are_one_title_and_no_skipped_levels(path):
    text = FRONT.sub("", open(path, encoding="utf-8").read())
    text = re.sub(r"(?ms)^```.*?^```", "", text)
    levels = [len(m.group(1)) for m in re.finditer(r"(?m)^(#{1,6})\s+\S", text)]
    assert levels and levels[0] == 1 and levels.count(1) == 1, levels[:5]
    assert all(b <= a + 1 for a, b in zip(levels, levels[1:], strict=False)), levels
    h1 = re.search(r"(?m)^#\s+(.+)$", text).group(1)
    assert re.sub(r"[*_`]", "", h1).strip() == front_matter(path)["title"]


def test_nothing_outside_reference_is_indexed_and_everything_inside_is():
    kb = json.load(open(KB, encoding="utf-8"))
    indexed = set(kb["files"])
    want = {rel(p) for p in reference_files() if front_matter(p).get("index") != "false"}
    assert all(f.startswith("docs/reference/") for f in indexed)
    # a reference file added or removed without `make copilot` fails here
    assert indexed == want, {"not indexed": sorted(want - indexed), "stale": sorted(indexed - want)}
    assert {p["file"] for p in kb["passages"]} <= indexed
    assert set(kb["documents"]) == indexed
    assert all(p.get("module") in MODULES for p in kb["passages"])


def test_the_index_matches_the_documents_text():
    # a document edited without `make copilot`: its passages no longer start where they say
    kb = json.load(open(KB, encoding="utf-8"))
    docs: dict[str, str] = {}
    stale = []
    for p in kb["passages"]:
        if p["file"] not in docs:
            text = open(os.path.join(ROOT, p["file"]), encoding="utf-8").read().lower()
            docs[p["file"]] = re.sub(r"[^a-z0-9]+", "", text)
        # the passage's first words, letters and digits only (the indexer drops _ and *)
        words = [w for w in re.findall(r"[a-z0-9]+", p["text"][:48].lower()) if w != "figure"][:3]
        if words and not all(w in docs[p["file"]] for w in words):
            stale.append((p["file"], p["text"][:40]))
    assert not stale, stale[:5]


def _markdown_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [f for f in out if f.startswith("docs/") or f == "README.md"]


def test_every_relative_link_in_the_documentation_resolves():
    broken = []
    for f in _markdown_files():
        text = open(os.path.join(ROOT, f), encoding="utf-8").read()
        for m in re.finditer(r"\]\(([^)\s#]+)(#[^)\s]*)?\)", text):
            target = m.group(1)
            if re.match(r"^[a-z]+:", target) or target.startswith("/"):
                continue
            if not os.path.exists(os.path.join(ROOT, os.path.dirname(f), target)):
                broken.append(f"{f} -> {target}")
    assert not broken, broken


def test_dated_documents_live_in_history():
    # a dated duplicate beside its current version (VALIDATION.md and VALIDATION_2026-10-23.md)
    # is what the reorganisation removed
    for f in _markdown_files():
        if re.search(r"\d{4}-\d{2}-\d{2}", os.path.basename(f)):
            assert f.startswith("docs/history/"), f


def _eval_questions() -> list[str]:
    from services.api.eval import eval_retrieval

    qs = [g["q"] for g in eval_retrieval.GOLDEN]
    for name in ("copilot_eval.json", "copilot_routes.json"):
        with open(os.path.join(ROOT, "tests", name), encoding="utf-8") as f:
            qs += [c["q"] for c in json.load(f)["cases"]]
    return qs


def test_no_evaluation_question_is_quoted_in_the_corpus():
    # a document that quotes a test question (a design note's routing example) makes that
    # question retrieve the note: the evaluation then measures the quote, not the retrieval
    kb = json.load(open(KB, encoding="utf-8"))
    corpus = re.sub(r"\s+", " ", " ".join(p["text"] for p in kb["passages"]).lower())
    norm = [re.sub(r"\s+", " ", q.lower()).rstrip("?").strip() for q in _eval_questions()]
    quoted = [q for q in norm if len(q.split()) >= 4 and q in corpus]
    assert not quoted, quoted

