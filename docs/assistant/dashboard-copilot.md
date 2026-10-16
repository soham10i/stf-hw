# Dashboard: Copilot

Dashboard group: Operate. Page id: `copilot`.

Ask about the cell in plain words. The twin computes the facts; with a Gemini key on the server, Gemini writes the answer from them, with citations. The Ask button on every page does the same for that page.

## How to read it

1. Type a question or pick one on the right.
2. Each answer names the tool or document it came from and links to the page with the detail.
3. Health questions use the machine age and PM setting on the right.

## Sections

### Try

Example questions, one per tool.

### Health questions use

The machine age and maintenance setting the health answers are computed for.

## Where the numbers come from

copilot.ts (tools over the twin's exports, BM25 over the documents) and, with a key, Gemini on the server (chat.py).

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Health index (HI)**: 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.
- **RUL**: Remaining useful life: how many shifts (or orders) a part has left before it fails.
- **OEE**: Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
