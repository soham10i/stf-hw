# The 3D view

## Layout

The machine fills the window. The controls float over it:

- **Top bar**: the view switcher (searchable, Cmd/Ctrl+K), the connection status, *New order*,
  the link to the dashboard and the light/dark theme.
- **Dock** on the left: one icon per side panel (Orders, Telemetry, PLC, Safety & security,
  Remote I/O, Connectivity, Commissioning, Geometry, Analysis).
- **Panel**: opens next to the dock. Unpinned it floats over the 3D view as frosted glass;
  pinned it takes its own column and the view moves aside. Drag the grip on its edge to resize it
  (300-640 px); click the grip to fold the panel away.
- **Control bar** at the bottom: the run state and current step, *Place an order* when the cell is
  idle, and the view toggles.

## View toggles

| Toggle | What it does |
|---|---|
| Enclosure | Shows or hides the guard: frame, polycarbonate panels, doors, and the E-stops, door switches and their cables mounted on it. Hide it to watch the machine. |
| Hazard zones | Shows the swept envelope of each moving machine, coloured by its required performance level (PLr). |
| Wiring | Opens the legend of cable colours: 24 V, 0 V, PE, mains, digital in/out, encoder, analogue, air, safety, bus, IO-Link. |

Opening *Safety & security > OT security* replaces the hazard zones with the network zones: blue
boxes for cell control (the I/O nodes and the PLC), red for the hardwired E-stops and reset.

## Keyboard shortcuts

| Key | Action |
|---|---|
| 1-9 | Open panel 1-9 (in dock order) |
| [ | Show or hide the panel |
| P | Pin or unpin the panel |
| C | Show or hide the enclosure |
| Cmd/Ctrl+K | Search and switch views |
| Esc | Close the floating panel or the view switcher |

Shortcuts are ignored while typing in a field.

## Camera

Drag to orbit, scroll to zoom, right-drag to pan. Labels in the scene: the rack's state above the
warehouse ("Rack: raw dough only", or how many are baked), and in OT security view the name and
IP address of each I/O node, the PLC cabinet, the E-stops and the reset button.

## What moves

Every axis is driven by one shared timeline. While an order runs: the crane fetches a mould, the
belt carries it to the robot, the robot moves the cookie into the oven, the elements glow and
the chamber heats, the oven's own gripper moves it to the turntable, the saw and the pusher work
it onto the outlet belt, the sorting line reads its colour and ejects it into its bay, and the
robot brings it back to the warehouse. Light barriers flash red while a cookie cuts their beam.
