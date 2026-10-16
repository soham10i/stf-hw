# Dashboard: Vision QC

Dashboard group: Operate. Page id: `vision`.

The inspection camera's live feed: every cookie photographed, judged by the CNN and the autoencoder, and checked against the truth the simulation knows.

## In brief

The inspection camera's live feed: every cookie photographed, judged by the CNN and the autoencoder, and checked against the truth the simulation knows.

## How to read it

1. Watch the live camera: the image, the CNN's answer and decision, and the autoencoder's error map (hot = not as a good cookie looks).
2. The KPIs and the confusion matrix say how right the CNN is over the last 50 cookies; escapes are defects it let through.
3. Change the conditions (ageing light, a warmer lamp, a worn belt) and watch the drift chart rise before the CNN's answers go wrong.
4. With the 3D twin open in another tab, the feed photographs the twin's own cookies.

## Sections

### Live camera

The latest cookie: camera image, autoencoder error map, truth, the CNN's answer and the line's decision, and a strip of recent cookies.

### The line

Run or pause, the conditions, the defect rate the simulation injects and the line's speed.

### Confusion (last 50)

Truth against the CNN's answer for each condition: everything off the diagonal is a mistake.

### Drift

The autoencoder's error on normal-looking cookies against its training baseline; above ×2 the line no longer looks like training.

### The camera

Where it is mounted in the colour hood, its lens and trigger, and the mount's checks against the model.

### The models, tested offline

The CNN and the autoencoder on held-out images like training and on unseen conditions.

### When the drift alarm rings

Every adaptation method on the changed line: right, good cookies rejected, defects passed, and whether the old line still works.

### The pass threshold

Each threshold as a point: defects passed against good cookies thrown out. Set it live with 'Pass threshold'.

### How many labels are worth it

Defects passed after tuning the final layers on a few labelled frames, against doing nothing and retraining.

### The safeguard

Once the alarm rings, what the autoencoder finds unusual goes to a person: fewer defects passed, more cookies checked by hand.

### Experiment: label-free adaptation

The same cookies classified twice, with and without online AdaBN. Switch it on under unseen conditions to watch it fail.

## Where the numbers come from

The camera mount (vision/mount.py), the CNN (vision/train.py) and the autoencoder (vision/autoencoder.py), run in the browser on images drawn by the renderer port.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Simulated**: Every number on this dashboard comes from the twin's models, not from a real machine. Values the models only assume are marked 'assumed'.
- **Drift**: The line's conditions moving away from what the models were trained on (light, lamp colour, belt wear). The autoencoder's error rises before the classifier's answers go wrong.
- **Autoencoder**: A network trained to rebuild images of good cookies only. What it rebuilds badly is unusual - it needs no defect labels.
- **Escape**: A defective cookie the inspection passed as good - the costly mistake.
- **False reject**: A good cookie the inspection threw out - wasted product.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
