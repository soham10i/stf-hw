# Dashboard: Copilot

Dashboard group: Operate. Page id: `copilot`.

Ask about the cell in plain words, by typing or by voice. A language model answers by calling the twin's own tools and states only what they return, with citations; the server checks every number before you see it. Conversations are kept in your history, and the facts each one establishes are kept with it.

## In brief

Ask about the cell in plain words, by typing or by voice.  A language model answers by calling the twin's own tools and states only what they return, with citations; the server checks every number before you see it.

## How to read it

1. Pick a tab: Chat (type, a language model answers) or Voice (speak, hear the answer).
2. If the first model is at its limit or not running, the next ready one answers with the same context - the chip on the answer says it handed over.
3. Answers take the form the question needs: a figure, a table for comparisons, numbered steps for an alarm, a status card for 'now'.
4. Copy any question or answer; 🔊 reads an answer aloud.
5. History is on the left; the Context panel on the right lists what the conversation has established.

## Sections

### History

Your earlier conversations; open one to continue it, × to delete it.

### Chat / Voice

How you ask; the first ready model answers, and the next takes over when it cannot.

### Context

The models that answered, the tools used and the facts found - what any model answering next is given.

## Where the numbers come from

The server's tools (services/api/tools.py), the model and its tool calls (chat.py), sessions and their context (sessions.py, store.py), speech (tts.py); scored on tests/copilot_eval.json.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Health index (HI)**: 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.
- **RUL**: Remaining useful life: how many shifts (or orders) a part has left before it fails.
- **OEE**: Overall equipment effectiveness = availability × performance × quality. 100 % means making only good parts, as fast as possible, with no stops.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
