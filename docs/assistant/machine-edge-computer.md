# Machine: Edge computer

## What it is

A fanless industrial edge PC on its own small plate in the free strip between the oven and the
front of the warehouse, inside the guard and outside the robot's reach. It is the hardware that
runs what the *Connectivity* panel shows:

- the **OPC UA server** (Machinery companion specification), one node per PLC signal;
- the **Sparkplug B edge node** that publishes the cell's data over MQTT;
- the **Unified Namespace bridge**.

## Parts

| Part | What it does |
|---|---|
| Edge PC | x86, 8 GB RAM, 64 GB SSD, 2 x Gigabit Ethernet. Fanless: a finned aluminium lid is its heat sink, so there is no fan to clog with flour dust. |
| Ports | 2 x RJ45, 2 x USB, 24 V DC input, link and activity LEDs. |
| DC UPS | 24 V with supercapacitors: bridges a mains dip and gives the PC the seconds it needs to shut down cleanly. |

## Connections

- **Port 1** to the cabinet's Ethernet switch, through the conduit to cell control. Only the
  messages on the allow-list pass (see *Panel: Safety & security*, OT security).
- **Port 2** to the site network.
- **24 V** from the cabinet's electronic breaker.

Both cables are routed on the table like the I/O nodes' links, and the cable router keeps them
out of the belts' lanes and the cookie's path.

## Checks it passes

Its plate is on the table and clear of every module plate; its parts are clear of every module
part; it is outside the robot's sweep; the guard and safety layout is unchanged; and the robot's
tours are still collision-free.
