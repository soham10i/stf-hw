# Dashboard: AI maintenance

Dashboard group: Maintain. Page id: `ai`.

A neural network that predicts each part's remaining life from its sensor history, tested on machines it never saw, and running here in your browser.

## How to read it

1. Start with the scores: how often it warned in time, and how much part life it threw away.
2. The network advises; the rules of the Health page still decide. Together they warn early and waste less.
3. The showcase compares the network's prediction with the truth on one unseen machine.

## Sections

### What happened to each of the

Every failure on machines the network never saw: warned at least a shift ahead (green), late (amber) or missed (red), per method.

### Verdict

What to do with the network, in three lines.

### The trade-off

Each method as a point: failures warned in time against part life thrown away. Top-left is better; hover a point.

### Choosing the network's alarm threshold

How the share warned in time changes with the alarm threshold; the chosen value is marked.

### Per part

Network (blue) against the rules (amber) for each part: the gap shows where the network is weak.

### Training loss

How the error fell while it learned; 'Model and data' opens the details.

### An unseen machine

Predicted against true remaining life, part by part, with the failure, the alarms and the rule warnings marked.

### Running here

The network applied to the simulated month, live in this page.

### At order

Each part's predicted remaining life at the chosen order, shortest first.

## Where the numbers come from

A TCN trained on a fleet of simulated machines, exported to ONNX and to the browser.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **RUL**: Remaining useful life: how many shifts (or orders) a part has left before it fails.
- **TCN**: Temporal convolutional network: the neural network that reads each part's sensor history and predicts its remaining life.
- **Semi-supervised**: Trained on many simulated machines where failures are known for only some of them.
- **Health index (HI)**: 100 = as new, 0 = it fails now. Computed from how far a part's measured behaviour has drifted toward its failure limit.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
