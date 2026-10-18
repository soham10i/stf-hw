# Dashboard: Vision QC

Dashboard group: Operate. Page id: `vision`.

The inspection camera on the process: its live view, and every cookie the 3D twin bakes, photographed, judged by the CNN and the autoencoder, and checked against the truth the simulation knows.

## In brief

The inspection camera on the process: its live view, and every cookie the 3D twin bakes, photographed, judged by the CNN and the autoencoder, and checked against the truth the simulation knows.

## How to read it

1. Open the 3D twin in a window beside this page: its camera in the colour hood streams here live (never recorded), and the photo it takes of each cookie is judged here (and stored by the server).
2. For each cookie: the photo, what the models see, the autoencoder's error map (hot = not as a good cookie looks), the truth and the decision.
3. One cookie in every 12 is damaged on purpose (QC testing, the Orders panel): each rack tests the inspection.
4. The KPIs and the confusion matrix count the cookies inspected since the page opened; escapes are damaged cookies let through.

## Sections

### Inspection camera

The twin camera's live view (not recorded); the latest cookie's photo, what the models see, its autoencoder error map, truth, the CNN's answer and the decision; and a strip of recent cookies.

### The decision

The pass threshold, and what pass, reject and 'to a person' mean for the cookie.

### Confusion

Truth against the CNN's answer for each condition: everything off the diagonal is a mistake.

### Ten photos from the process

Ten cookies the camera photographed while the twin baked an order, the QC test's damaged one among them, with what the CNN decided.

### Drift

The autoencoder's error on normal-looking cookies against its training baseline; above ×2 the line no longer looks like what the models learnt.

### The camera

Where it is mounted in the colour hood, its lens and trigger, and the mount's checks against the model.

### Photos stored by the server

Each cookie your own twin photographed, as the server keeps it.

## Where the numbers come from

The camera mount (vision/mount.py), and the CNN and autoencoder run in the browser on the 3D twin's own photos.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.
- **Drift**: The line's conditions moving away from what the models were trained on (light, lamp colour, belt wear). The autoencoder's error rises before the classifier's answers go wrong.
- **Autoencoder**: A network trained to rebuild images of good cookies only. What it rebuilds badly is unusual - it needs no defect labels.
- **Escape**: A defective cookie the inspection passed as good - the costly mistake.
- **False reject**: A good cookie the inspection threw out - wasted product.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
