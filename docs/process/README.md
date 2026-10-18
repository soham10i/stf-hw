# The bake as a process (Upgrade 19)

Until Upgrade 19 the oven waited a fixed time and every cookie came out right. A real bake is
heat and water: the elements heat the chamber, every door opening cools it, the cookie's surface
dries and browns while its centre is still heating, and how a cookie turns out depends on the
oven's state when it went in, on the dough, and on when the bake is ended. This chapter is the
model of that process, built from the oven's own parts and the order's real door openings, and
what it says about quality, capacity and energy. Everything is simulated; every material value
is assumed and listed below, and two constants are calibrated so a nominal cookie bakes as
cookies of its size do. Replace them with one measured bake before trusting the numbers.

## What it found

- With a real bake the oven is the cell's bottleneck by far: the 12-cookie order takes 98 min instead of 7.1 min, 5.5 cookies an hour instead of 76.1. The rest of the cell could feed 14 ovens like this one.
- A fixed timer leaves 20.4 % of cookies wrong, most of them underbaked dough from the fridge (73.9 % right). Ending the bake on the PLC's model of the cookie gets 88.9 %; correcting its colour target from the camera after every cookie gets 97.1 %: the camera sees a lot's colour after its first cookie, but not the water left in a thick cookie's centre. Measuring each piece of dough before it goes in - its temperature (an infrared thermometer) and its height (a laser distance sensor) over the presented tray - gets 99.1 %: the hardware this upgrade asks for.
- Each cookie costs about 51 Wh of heat; the oven holds 180 C on 266 W and preheats in 4.9 min (87 Wh). Two shifts a day come to about 138 kWh a month, 3.0 times the rest of the cell's 46 kWh.
- The cell's microgrid was sized for a 5 W lamp: its 600 W inverter cannot run the 1300 W of elements. The oven needs its own 230 V supply, or the microgrid resizing.
- After every door opening the air overshoots to at most 199 C, 51 K below the over-temperature cutout.

## The oven

Three thermal nodes - the grill element ($T_t$), the bottom elements ($T_b$), the liner and
walls ($T_w$) - the tray ($T_p$), and the chamber air ($T_a$), which holds 9 J/K and settles in
under a second, so it is solved as a balance at every step. From `oven_model.py`: a
7.8 l chamber, an 800 W grill hairpin and two 250 W bottom hairpins,
a 1.5 mm stainless liner over 10 mm of ceramic fibre, a K-type thermocouple, a convection fan,
the door and the steam vent.

$$C_t \frac{dT_t}{dt} = u\,P_t - \varepsilon\sigma A_t\left(T_t^4 - T_w^4\right) - h A_t (T_t - T_a) - \dot Q_{t\to c}$$

$$C_w \frac{dT_w}{dt} = \dot Q_{rad} - h A_w (T_w - T_a) - UA_{ins} (T_w - T_\infty)$$

$$\sum_k h A_k (T_k - T_a) = \left(G_{door} + G_{vent}\right)(T_a - T_\infty)$$

| Quantity | Value |
|---|---|
| Element capacities $C_t$, $C_b$ | 56.7 J/K, 101.2 J/K |
| Liner and walls $C_w$ | 1412 J/K |
| Insulation $UA_{ins}$ | 0.925 W/K |
| Shut door, steam vent at 180 C | 0.137 W/K, 0.616 W/K |
| Open mouth at 180 C (buoyant exchange) | 3.28 W/K |
| The cookie's view of the grill element $F$ | 0.079 |

With the door open the convection fan stops and the mouth exchanges air both ways, driven by the
temperature difference (doorway flow):

$$\dot V = \frac{C_d}{3}\, W \sqrt{g H^3 \frac{T_a - T_\infty}{\bar T}}$$

A PI controller on the thermocouple (first-order lag, $\tau = 10$ s)
drives the solid-state relay Q9. While the door is open its integral holds and the heat is
capped at 40%; even so the elements, hot from the open-door
minutes, push the air to at most 199 C once the door shuts, against the
250 C cutout. *Source: `stf-cad/hbw/bake.py:249`.*

| Heat-up from 21 C | |
|---|---|
| To 180 C | 296 s (oven_model.py: about 6 min) |
| Elements' peak | 731 C (sheath limit 800 C) |
| Air overshoot | 180.2 C |
| Holding 180 C | 266 W |
| Preheat energy | 87 Wh |

## The cookie

A 14.6 g disc of dough, 45 mm across and 8 mm thick, in 16
layers through its thickness. The top takes radiation from the grill element and the liner and
convection from the air; the bottom sits on the tray:

$$\rho c_p \frac{\partial T}{\partial t} = \frac{\partial}{\partial z}\left(k(X)\,\frac{\partial T}{\partial z}\right) - \rho_d \lambda \frac{\partial X}{\partial t}$$

Each layer gives up its water at a rate that follows water's vapour pressure (Clausius-Clapeyron,
the same 40 kJ/mol as boiling), faster near the surface where the vapour can leave:

$$\frac{dX_i}{dt} = -k_d\, \frac{p_{sat}(T_i)}{p_{sat}(100\,^\circ\mathrm{C})}\, e^{-z_i/\delta}\,(X_i - X_e)$$

Each kilogram takes its latent heat with it, so the centre holds near 100 C while the dough is
wet (18-94 C in the nominal bake) - the plateau a probe in
real dough shows. The evaporation is solved implicitly in each layer: it cools the layer, which
slows it. Once the surface is below 10 % water it browns (Maillard), first order with an
Arrhenius rate:

$$\frac{dB}{dt} = k_B\, e^{-\frac{E_a}{R}\left(\frac{1}{T_s} - \frac{1}{T_{ref}}\right)} (1 - B)$$

*Source: `stf-cad/hbw/bake.py:219`, `stf-cad/hbw/bake.py:336`.*

**Quality.** A cookie is *done* when its centre has reached 95 C
and it holds at most 6 % water (wet basis); its colour is right when the browning index lies
between 0.35 and 0.65. Not done, or too pale: *underbaked*; too dark: *burnt* - the classes the
camera (Upgrade 15) reports. The nominal cookie is done at 520 s and reaches the
colour target 0.5 at 596 s.

## Ending the bake: three policies on the same shifts

20 shifts per policy, each four lots of 12 cookies, back to back, with the
order's real door openings between bakes and the same disturbances for every policy: the hall's
daily temperature, elements aged to 88-100 % of their power, the robot's waits, and dough lots
that differ in thickness and water and come from the bench or, three in ten, from the fridge.

- **Fixed timer**: 600 s, the nominal cookie's bake - what the lamp dwell did.
- **Soft sensor**: the PLC runs its own model of the oven and an 8-layer model of a nominal
  cookie, fed the duty it commanded and corrected by the thermocouple. The correction also
  learns the elements' ageing. The bake ends when the modelled cookie is done and brown enough.
- **Soft sensor + camera**: after every cookie the camera's colour reading (σ = 0.03) moves the
  next cookie's colour target against the error. This is run-to-run control: it learns a lot that
  bakes differently within a few cookies.
- **+ dough sensors**: the same, and two sensors over the presented tray read each piece of
  dough before it goes in: an infrared thermometer (σ = 0.5 C) and a laser distance sensor for
  its height (σ = 0.05 mm). The PLC's model cookie then starts at the dough's real temperature
  and thickness. This is new hardware: two sensors, two analogue inputs.

The colour correction starts again at every new lot: what the camera learnt was about the last
one.

| Policy | Right | Underbaked | Burnt | Right, fridge dough | Bake time | Heat per cookie |
|---|---|---|---|---|---|---|
| fixed timer | 79.6 % | 194 | 2 | 73.9 % | 600 ± 0 s (600-600) | 49 Wh |
| soft sensor | 88.9 % | 83 | 24 | 83.7 % | 621 ± 6 s (579-628) | 51 Wh |
| soft sensor + camera | 97.1 % | 26 | 2 | 94.3 % | 622 ± 21 s (550-688) | 51 Wh |
| + dough sensors | 99.1 % | 9 | 0 | 98.5 % | 623 ± 24 s (554-704) | 51 Wh |

The soft sensor follows the oven but not the dough: it cannot see that a lot came from the
fridge, or that it was rolled thicker. The camera sees the colour, after the first cookie of the
lot, but not the water left in a thick cookie's centre. The dough sensors see both before the
first cookie goes in. This is the physical-AI loop in its
plainest form: the camera sees, the model decides, the oven does it, and the next cookie is
better for it.

## What it means for capacity

| Case | Bake | 12-cookie order | Cookies an hour |
|---|---|---|---|
| demo bake (lamp, 2 s) | 2.0 s | 7.1 min | 76.1 |
| real bake | 622.9 s | 97.9 min | 5.5 |

One cookie occupies the oven for 650 s: the bake plus 27 s
of door, slider and handover. That caps the oven at 5.5 cookies an hour, whatever the
rest of the cell does. The rest of the cell needs 47 s per cookie, so it
could feed 14 ovens like this one. A real line bakes many cookies at once, in a tunnel
oven - the STF-2 redesign.

## What it means for energy

About 51 Wh of heat per cookie and 266 W to hold 180 C; two shifts a
day come to about 138 kWh a month. The rest of the cell uses
45.98 kWh a month. The cell's microgrid was sized for the 5 W lamp; its 600 W
inverter cannot run 1 300 W of elements.

## Checks

all pass. Each check catches the fault it is there for: the steam left off the energy ledger (caught); an 8 s step (caught); browning that slows with heat (caught); doors that lose no heat (caught).

- **Energy:** every shift's ledger closes. The heat from the elements equals the change in
  stored heat, plus the losses through the walls, the shut door, the vent and the open mouth,
  plus the steam and the heat the cookies took.
- **The oven:** the heat-up matches oven_model.py's note; the elements stay below their
  sheath's 800 C; the air stays within 5 K of the setpoint on heat-up and 25 K short of the
  cutout after door openings. The holding power lies within the bounds of its losses.
- **Numerics:** 16 layers at 0.5 s against 32 layers at 0.1 s agree within 2 %; the explicit
  steps are stable (Fourier number ≤ 0.5), and an unstable step is refused before it runs.
- **Physics:** thicker or colder dough bakes longer, a hotter oven shorter, and weaker elements
  heat up more slowly. The wet centre stays near 100 C.
- **Policies:** on the same shifts each policy is at least as good as the one before it, and
  the best gets at least 97 % of cookies right.

## Parameters

| Name | Value | Unit | Source |
|---|---|---|---|
| `volume_l` | 7.776 | l | model |
| `liner_area` | 0.2124 | m2 | model |
| `mouth` | 0.0192 | m2 | model |
| `p_top` | 800 | W | model |
| `p_bot` | 500 | W | model |
| `el_mass_per_m` | 0.17 | kg/m | assumed |
| `el_cp` | 600 | J/(kg K) | assumed |
| `el_eps` | 0.85 |  | assumed |
| `liner_t` | 0.0015 | m | model |
| `steel_rho_cp` | 3.95e+06 | J/(m3 K) | assumed |
| `liner_eps` | 0.4 |  | assumed |
| `ins_t` | 0.01 | m | model |
| `ins_k` | 0.07 | W/(m K) | assumed |
| `ins_rho_cp` | 1.37e+05 | J/(m3 K) | assumed |
| `h_out` | 10 | W/(m2 K) | assumed |
| `h_fan` | 25 | W/(m2 K) | assumed |
| `h_still` | 8 | W/(m2 K) | assumed |
| `cd_mouth` | 0.6 |  | assumed |
| `vent_d` | 0.028 | m | model |
| `tc_tau` | 10 | s | assumed |
| `setpoint` | 180 | C | model |
| `kp` | 0.08 | 1/K | assumed |
| `ti` | 90 | s | assumed |
| `cutout` | 250 | C | model |
| `door_duty` | 0.4 |  | assumed |
| `tray_dims` | [0.05, 0.06, 0.01] | m | model |
| `tray_rho_cp` | 2.43e+06 | J/(m3 K) | assumed |
| `h_contact` | 120 | W/(m2 K) | assumed |
| `h_hall` | 8 | W/(m2 K) | assumed |
| `cookie_d` | 0.045 | m | model |
| `cookie_t` | 0.008 | m | assumed |
| `rho_dough` | 1150 | kg/m3 | assumed |
| `x0` | 0.2 | kg water / kg dry | assumed |
| `x_eq` | 0.015 | kg/kg | assumed |
| `cp_dry` | 1600 | J/(kg K) | assumed |
| `cp_w` | 4180 | J/(kg K) | assumed |
| `latent` | 2.26e+06 | J/kg | assumed |
| `k_dry` | 0.15 | W/(m K) | assumed |
| `k_w` | 1 | W/(m K) | assumed |
| `eps_cookie` | 0.9 |  | assumed |
| `evap_depth` | 0.003 | m | assumed |
| `kd_ref` | 0.01137 | 1/s at 100 C | calibrated |
| `ea_brown` | 9e+04 | J/mol | assumed |
| `kb_ref` | 0.05365 | 1/s at 180 C | calibrated |
| `x_brown` | 0.1 | kg/kg | assumed |
| `core_done` | 95 | C | assumed |
| `x_done` | 0.064 | kg/kg | assumed |
| `b_band` | [0.35, 0.65] |  | assumed |
| `b_target` | 0.5 |  | assumed |
| `n_layers` | 16 |  | numerical |
| `dt` | 0.5 | s | numerical |
| `plc_layers` | 8 |  | numerical |

*Generated by `stf-cad/hbw/bake.py` (`make bake`); edit the model, not this file.*
