# Panel: Orders

The first panel; also opened by *New order* and *Place an order*.


## In brief

The first panel; also opened by *New order* and *Place an order*.

## New order

Pick a flavour (chocolate, strawberry, vanilla) and a quantity of 1 to 12, then *Place order*.
"N raw available" says how many moulds still hold raw dough: an order can only use raw cookies,
and the button is disabled when none are left. Orders queue; the cell works through them in
order.

*Deliver N baked cookies and refill with dough* appears once cookies are baked: it takes the baked
cookies out and refills their moulds with fresh dough, so new orders can run. It waits until the
cell is idle.

## Now

The cookie being made ("Strawberry cookie 2 of 4"), a progress bar in its flavour colour, the
current step in plain words and the time left for this cookie. *Running* or *Idle*.

## Orders

Every order placed this session, with its progress ("3 of 5 completed").

## Warehouse rack

The 12 slots (A1-C4) and what each holds: raw dough, a baked flavour, or empty while its mould is
out in the line. The summary line counts them ("11 raw · 1 in the oven line"). The total is always
12: cookies are never created or lost.
