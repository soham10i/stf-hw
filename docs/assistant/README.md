# Assistant knowledge base

These documents are the context the dashboard chat uses to answer questions about the digital
twin. One document per section of the app: the 3D twin, each of its side panels, each machine
module, each dashboard page, plus the production cycle, the alarm codes and common questions.

How the chat uses them:

- The knowledge base (`web/public/copilot/kb.json`) splits every document into passages under
  its headings; the chat searches them (BM25) for each question.
- The document for the page the user is on is always sent with the question, so questions
  like "what does this page show?" are answered from the right text.
- Live numbers (health, alarms, energy, the month, the scheduler, the inspection) come from the
  twin's own tools at question time; these documents explain what the numbers mean and where
  they come from. Numbers quoted here are from the model at the time of writing.

Rebuild after editing: `make copilot` (or `make guide` for the generated dashboard pages).

The `dashboard-*.md` files are generated from `web/src/dashboard/guide.ts` by
`web/scripts/guide-md.ts`. Edit the guide, not the files. Everything else here is written by hand.

Everything in the twin is simulated from engineering models; nothing is measured on a physical
machine.
