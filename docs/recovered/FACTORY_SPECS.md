# Factory Simulation 24V - Key Specifications

## System Requirements
- **Power Supply**: 24V / 4.8A
- **Digital Inputs**: 26 total
  - Reference switches: 15
  - Light barriers: 9
  - Trail sensor: 1 (2 digital inputs)
- **Counter Inputs**: 10 (5 encoders with 10 counter inputs)
- **Analog Inputs**: 1 (color sensor)
- **Outputs**: 35 total
  - Unidirectional motors: 3
  - Bidirectional motors: 10 (20 outputs)
  - Lamps: 1
  - Compressors: 3
  - 3/2-way solenoid valves: 8

## High-Bay Warehouse (HBW) Components
From occupancy plan and PDF:
- **Q1/Q2**: Conveyor belt motor (bidirectional)
- **Q3/Q4 + B1/B2**: Horizontal axis motor with encoder
- **Q5/Q6 + B3/B4**: Vertical axis motor with encoder
- **Q7/Q8**: Cantilever (telescopic) motor
- **A1+A2**: Color sensor
- **I2**: Reference switch (horizontal)
- **I4**: Reference switch (vertical)
- **I5**: Light barriers (multiple)

## Vacuum Gripper Robot (VGR) Components
- **Q1 (M1)**: Motor vertical up
- **Q2 (M1)**: Motor vertical down
- **Q3 (M2)**: Motor horizontal backward
- **Q4 (M2)**: Motor horizontal forward
- **Q5 (M3)**: Motor rotate clockwise
- **Q6 (M3)**: Motor rotate counterclockwise
- **Q7**: Compressor
- **Q8**: Vacuum valve
- **I1**: Reference switch vertical
- **I2**: Reference switch horizontal
- **I3**: Reference switch rotate
- **B1-B6**: Encoder inputs (vertical, horizontal, rotate)

## Sorting Station Components
- **Q1 (M1)**: Motor conveyor forward
- **Q2 (M1)**: Motor conveyor backward
- **Q3**: Compressor
- **Q4**: Valve first ejector (white)
- **Q5**: Valve second ejector (red)
- **Q6**: Valve third ejector (blue)
- **I1-I4**: Light barriers
- **A1**: Color sensor

## Physical Dimensions (HBW)
- 3x3 storage grid (9 slots)
- X-axis: Horizontal movement
- Y-axis: Vertical movement
- Z-axis: Telescopic arm (cantilever)
