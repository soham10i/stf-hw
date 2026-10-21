# User guide

The STF digital twin is a cookie factory you can run: a 3D model of a real Fischertechnik
training factory with its PLC, its camera inspection and its maintenance. This guide takes you
from your first order to reading two months of production.

**The two windows.** The **3D twin** is the machine: you place orders there and watch it bake.
The **dashboard** is the control room: it shows what the twin is doing, live, and what months
of production look like. Open them side by side.

| | Where | What you do there |
|---|---|---|
| 3D twin | `/stf/` | Run the machine: orders, the camera, the PLC, the parts |
| Dashboard | `/stf/dashboard.html` | Watch it live, analyse production, ask the copilot |

**Nothing runs until you start it.** The dashboard does not animate on its own: an order starts the simulation, and the dashboard follows it.


## 1. Your first order (2 minutes)

1. Open the **3D twin**. Wait for "Building the machine" to finish.
2. The **Orders** panel is open on the left. Under **New order**:
   - pick a **flavour** and a **quantity** (1 to 12), then **Place order**, or
   - press **Sample order**: one chocolate, one vanilla, one strawberry - the quickest way to
     see every station work.
3. Watch the cell: the crane takes a mould from the rack, the robot arm carries the dough to
   the oven, the oven bakes it, the turntable and the oven belt pass it to the sorting line,
   the camera photographs it, and the line ejects it into its bin.
4. The **dock** at the bottom shows the current step and the cookie's progress. Speed it up
   with **1× 2× 4× 8×**.

**From the dashboard instead:** on **Overview**, press **Simulate order**. If a twin is open,
the order starts there; if not, the twin opens in a new tab and starts the order by itself.

## 2. Break a cookie on purpose

The inspection is only interesting when something is wrong.

- In the twin, switch on **Broken cookie** in **New order** before you place it: the first
  cookie of the order comes out cracked.
- On the dashboard, the **Broken cookie** button next to **Simulate order** does the same.
- **Quality inspection** (twin, Orders panel) also lets you choose the fault for the next
  cookie: burnt, underbaked or cracked. **QC testing** damages one cookie in every 12 by itself.

What happens: the camera photographs the cookie, the CNN judges it, and the sorting line acts on
the verdict - a rejected cookie is **not** ejected to its bin; it is held at the end of the
line, and the order bakes another one.

## 3. Watch the camera

- **In the twin:** the **Quality inspection** card shows the camera's live view of the sorting
  belt. The frame lights up when a cookie passes under the lens and its photo is taken.
- **On the dashboard:** the **Live cell** card on Overview shows the same view, small;
  **Vision QC** shows it large, with each photo, what the models decided and whether they were
  right.

## 4. The live link

The twin and the dashboard are connected by a WebSocket (`/twin/live` on the API). The twin
publishes its state four times a second while an order runs; every dashboard you have open in
the same browser receives it at once. The link is private to your visitor session: nobody else
sees or steers your twin. The **Live cell** card shows the connection:

| Badge | Meaning |
|---|---|
| **Twin connected** | a twin is open and publishing; nothing is running |
| **Simulating** | an order is running in the twin |
| **No twin open** | no twin publishes; **Simulate order** opens one |

Without the API (the static demo), the link still works between tabs of one browser.

**Keep the twin visible.** The simulation runs in the twin's tab. Browsers pause a hidden tab's 3D loop, so put the twin and the dashboard in two windows side by side, not two tabs of one window.

## 5. The Overview, live

**Live cell** is the twin seen as a control room sees it:

- **The cookie's way:** rack → belt → robot arm → oven → turntable → sorting → camera → bin.
  The current station is lit in the cookie's colour, with its progress.
- **Every unit's state machine:** the eight units the PLC drives - crane, belt, arm, door,
  sauger (suction gripper), turntable, oven belt, sorting line - each with its states:

  | State | Meaning |
  |---|---|
  | IDLE | no order |
  | READY | an order runs; the unit waits its turn |
  | RUN | the unit is moving (its step is shown beside it) |
  | HELD | the unit holds a part while another works (the crane holding a mould, the arm a cookie) |

- **The oven** temperature, and **passed / rejected** cookies with the last verdicts.

The rest of Overview is the machine's planned schedule (**Production timeline**), its OEE, the
next maintenance and the downtime by fault.

## 6. Two months of production

**Two months** (Analyse) is September and October 2026 on this machine, simulated from its
models: 4,085 orders, 36,764 good cookies, OEE 73.9 %. Its story is preventive maintenance
catching two failures before they happen:

| Part | Health warning | Renewed | Would have failed |
|---|---|---|---|
| HBW travel spindle + nut | Thu 10 Sep 15:12 | the same night, 22:00 | Wed 16 Sep, 6.5 h down |
| VGR swivel gearbox | Mon 12 Oct 20:46 | the same night, 22:00 | Fri 16 Oct, 4 h down |

Both were renewed in the night gap, so no production was lost. **Without the two saves** shows
the same two months had they been missed: 2 failures, 13.5 h of unplanned stop, 42 fewer orders.

- **Health** shows every part's health index; move **Machine age** to see it wear, and switch
  **PM** off to run it until it fails.
- **Maintenance** turns the warnings into a service plan, with the AI's predictions beside it.

## 7. The pages, in one line each

| Page | Answers |
|---|---|
| Overview | What is the cell doing now, and how healthy is it? |
| Production | How does the PLC schedule a 12-cookie order? (press play to replay it) |
| Quality & trace | Where is every cookie of the order? |
| Vision QC | Is the camera inspection right, and how will its models age? |
| Alarms | What went wrong, and what to do |
| Copilot | Ask anything about the machine, in words or by voice |
| Health / Maintenance | Which part wears out next, and when to service it |
| Two months | Production, faults and maintenance over September and October |
| Throughput | Why the new PLC program is faster |
| Oven process | How the bake works, step by step |
| Learned scheduler | A learned dispatcher against the PLC's rules |
| Energy & grid | The microgrid: PV, battery, peak cap, outages |
| Carbon per cookie | Grams of CO₂ per cookie, and what cuts it |
| OT security / Defence in depth | The network, the threats and the controls |
| Engineering / Validation / Data | How the twin is built and checked |

Every page has a **Guide** button (what it shows and the terms it uses) and an **Ask** button
(the copilot, about that page). Captions show one line; click one to read it all.

## 8. The copilot

**Copilot** answers from the twin's own data and these documents. Type a question, or use the
**Voice** tab to ask aloud; answers can be read back, equations included. With a twin open, it
can also answer "what is the cell doing right now?".

## 9. Inside the twin

The rail on the left of the twin opens its panels:

| Panel | Use it to |
|---|---|
| Orders | place orders, break cookies, watch the camera, deliver and reset the rack |
| Telemetry | see the machine's live signals |
| PLC | read the PLC program and its state machines |
| Safety & security | the guards, the hazard zones and the network |
| Remote I/O, Connectivity | the wiring and the OPC UA / MQTT interfaces |
| Commissioning | the virtual commissioning results |
| Geometry, Analysis | measurements and studies of the layout |

The **focus menu** (top of the view) flies the camera to a module. Drag to turn, scroll to
zoom, right-drag to move. **Enclosure** and **Hazard zones** in the dock show the guarding.

## 10. When something does not work

| You see | Do this |
|---|---|
| Live cell says **No twin open** | Open the twin, or press **Simulate order** |
| Units stay **IDLE** after Simulate | Bring the twin's window to the front: hidden tabs pause |
| "The rack has too little dough" | In the twin, **Deliver** the baked cookies (the moulds are refilled) or **Reset rack** |
| Camera says **camera off** | It streams only while a twin is open; it starts within two seconds |
| A dashboard in another browser shows nothing | The link is per visitor: use the same browser for the twin and the dashboard |
