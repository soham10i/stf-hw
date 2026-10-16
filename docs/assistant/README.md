# Assistant knowledge base

These documents are the context the dashboard chat uses to answer questions about the digital
twin. One document per section of the app: the 3D twin, each of its side panels, each machine
module, each dashboard page, plus the production cycle, the alarm codes and common questions.

How the chat uses them:

- The chat runs on the server. The language model (Gemini, or a local model through Ollama)
  calls the twin's tools (`services/api/tools.py`): machine health, alarm lookup, the month,
  OEE, energy, carbon, the scheduler, vision, security, the running twin's live state, this
  page's guide, and `search_docs`, a BM25 search over the passages of these documents
  (`web/public/copilot/kb.json`).
- `page_guide` returns the `dashboard-<page>.md` of the page the user is on.
- Live numbers come from the tools at question time; these documents explain what the numbers
  mean and where they come from. Numbers quoted here are from the model at the time of writing.
- The evaluation set (`tests/copilot_eval.json`) checks that questions reach the right tools
  and that answers state only numbers the tools returned.

Rebuild after editing: `make copilot` (or `make guide` for the generated dashboard pages).

The `dashboard-*.md` files are generated from `web/src/dashboard/guide.ts` by
`web/scripts/guide-md.ts`. Edit the guide, not the files. Everything else here is written by hand.

Everything in the twin is simulated from engineering models; nothing is measured on a physical
machine.
