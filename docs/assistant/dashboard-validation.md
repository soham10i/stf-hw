# Dashboard: Validation

Dashboard group: Engineer. Page id: `validation`.

How the project checks itself: every variant re-built, the plant varied, and defects planted to prove the checks can fail.

## How to read it

1. Regression: every upgrade's machine is re-exported and must give the same result.
2. Mutation tests: each planted defect must be caught; one that survives would be a gap in the proofs.

## Sections

### Regression: every variant re-exported

Each upgrade's export rebuilt and compared with its recorded fingerprint.

### Robustness: ±20 % on every plant step

Random plants with every step time varied; no false alarms allowed.

### Data products

Checks on the published data: the network's ONNX and browser copies against the original, the month and grid files, the tests and the web build.

### Mutation tests

A defect planted in each proof, and which check caught it.

### Failing checks

Anything currently failing (normally empty).

## Where the numbers come from

validate.py, which re-proves every variant.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Mutation test**: Planting a deliberate defect to check that the proof catches it. A proof that cannot fail proves nothing.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
