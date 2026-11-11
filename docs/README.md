# Documentation

Four kinds of document live here, each in its own folder, so a reader - and the copilot, which
retrieves from one of them only - can tell what a document is from where it is.

| Folder | What it holds | Retrieved by the copilot |
|---|---|---|
| [`reference/`](reference/README.md) | What the twin is and how it works: the factory, its machines, the PLC, the dashboard pages, maintenance, vision, the bake, the copilot, operations, architecture | yes, all of it |
| [`plans/`](plans/) | Roadmaps, blueprints, feasibility reports and plans for work not yet done | no |
| [`history/`](history/) | Dated reviews, validation reports, hand-overs, eval baselines and measurements | no |
| [`internal/`](internal/) | Notes for contributors: [code conventions](internal/code-conventions.md) | no |

Beside them: `assets/` and `images/` (the pictures the documents show), `gen/` (the generators of
reference chapters), `vendor/` (the makers' documents; the PDFs stay untracked, see
[its README](vendor/README.md)), the four `occupancyPlan*.ods` I/O plans that
`stf-cad/hbw/electrical.py` parses, and `openapi.json` (the API's schema, written by the tests).

## A reference document

Every file under `reference/` starts with front matter:

```
---
title: "Machine: Oven (multi-processing station with kiln, ft 536632)"
scope: "One sentence: what the document covers."
module: oven
last_verified: 2026-10-17
---
```

- `title` is the document's H1, and the name the copilot cites it by.
- `scope` is one sentence on what it covers; the Docs page shows it.
- `module` is one of: factory, warehouse, gripper-robot, oven, sorting-line, machine, plc, twin,
  dashboard, guide, maintenance, vision, process, copilot, operations, architecture.
- `last_verified` is the date the text was last checked against the code. It started as each
  file's last commit date (2026-11-09 reorganisation); bump it when you check a document. A
  generated chapter carries the date it was generated, and `generated_by` names its generator -
  edit the generator, not the file.
- `index: false` keeps a file out of the index (the full dashboard guide, which repeats the
  per-page documents).

Headings: one H1, the title; no skipped levels. The indexer splits a document at every heading
into passages of at most 140 words and labels each with its heading path ("Machine: Oven >
Temperatures"), so a heading should name what its section is about, and a long section reads
better split under sub-headings than as one wall.

`tests/test_docs_corpus.py` checks all of this, that every relative link in the documentation
resolves, and that the copilot's index (`web/public/copilot/kb.json`) holds exactly the indexed
reference files.

## Where a new document goes

- It describes the twin as it is: `reference/<area>/`, with front matter. Rebuild the index with
  `make copilot` (and `make db-seed-kb` for a deployed vector store).
- It describes work not yet done: `plans/`.
- It records what was found or measured on a date: `history/YYYY-MM-DD-<subject>.md`.
- File names are lowercase-with-hyphens; a folder's overview is its `README.md`.
