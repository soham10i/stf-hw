# Common questions


## In brief

No.  Everything is simulated from engineering models of the fischertechnik factory.

## Is this a real machine?

No. Everything is simulated from engineering models of the fischertechnik factory. "Live" in the
top bar means the physics API is connected; "Simulation" means everything runs in the browser.

## How do I start production?

Click *New order* (top bar) or *Place an order* (bottom bar), choose a flavour and 1-12 cookies,
and place it. The 3D view starts moving. Only raw cookies can be ordered; deliver baked ones to
refill their moulds with dough.

## Why does nothing move?

No order is queued ("Waiting for an order"), or every raw cookie is already baked. Place an
order, or deliver the baked cookies first.

## How do I see inside the machine?

Hide the enclosure (the *Enclosure* button or C) and the hazard zones. The oven's window door
shows the elements and the cookie while it bakes.

## Why only three flavours, and why these?

The colour sensor measures brightness, not colour. Chocolate, strawberry and vanilla read far
apart (about 340, 950 and 1660 mV), so they cannot be confused.

## What does PLr d mean?

A required performance level from ISO 13849-1, from a (lowest) to e. The crane and the robot arm
need d; their safety functions are category 3 with two channels and cross-monitoring.

## How can the cell never deadlock?

Every transfer takes all its locks at once, in one fixed order, and never starts unless its
destination has room. The orchestration model is checked over every possible completion order.

## Where do health and remaining life come from?

A condition-monitoring model per wear part: each sensor reading is smoothed (EWMA), compared with a
soft limit and trended to estimate remaining life. See *Dashboard: Hardware health* and the
*Hardware degradation* docs page.

## Can I ask about the numbers on a page?

Yes. The chat answers from the twin's own data and these documents, and cites where each number
comes from. It does not invent values; if something is not in the data, it says so.
