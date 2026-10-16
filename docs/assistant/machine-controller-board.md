# Machine: Controller board and PLC I/O

## In brief

The *Controller board · PLC I/O* view (view switcher) shows the 24 V adapter PCB of each module and its interface to the PLC, pin by pin.


The *Controller board · PLC I/O* view (view switcher) shows the 24 V adapter PCB of each module and
its interface to the PLC, pin by pin.

- One tab per module: warehouse, robot, oven, sorting line.
- The board: connectors ST1 (20-pin), ST2 (14-pin) and ST3 (17 x 2, to the PLC), the relays R1-R8
  that switch the motors (each pair drives one motor both ways), and the 30-terminal strip:
  +24 V, 0 V, inputs, encoder inputs and outputs, colour-coded by signal type.
- Circuit diagrams for each kind of connection, and the board's data from the documentation,
  including the discrepancies found between the documents.

In the factory the boards are connected to remote I/O nodes; see *Panel: Remote I/O*.
