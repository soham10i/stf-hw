# Dashboard: Copilot

Dashboard group: Operate. Page id: `copilot`.

Ask about the cell in plain words. A language model (Gemini, or a local model through Ollama) answers by calling the twin's own tools - health, alarms, the month, OEE, energy, carbon, the scheduler, vision, security, the documents, this page's guide and the running twin - and states only what they return, with citations. Without a model, the same tools answer directly (rules). The Ask button on every page does the same for that page.

## How to read it

1. Type a question or pick one on the right. Ask several things at once if you like: the model calls as many tools as it needs.
2. Each answer names its sources, the tools it used, and links to the page with the detail.
3. Questions about what the cell is doing now need the 3D twin open in another tab.
4. Health questions use the machine age and PM setting on the right.

## Sections

### Try

Example questions, one per tool.

### Health questions use

The machine age and maintenance setting the health answers are computed for.

## Where the numbers come from

The server's tools (services/api/tools.py) over the twin's exports and documents; the model and its tool calls in chat.py; scored on tests/copilot_eval.json. Offline (no server): copilot.ts in the browser.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Health index (HI)**: 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.
- **RUL**: Remaining useful life: how many shifts (or orders) a part has left before it fails.
- **OEE**: Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
