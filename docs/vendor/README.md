# The makers' documents

The model is built from these publications. They belong to their makers, so the repository does
not redistribute them: put a copy of each in `docs/` under the file name below (git ignores
`docs/*.pdf`). The code cites them by these names (`stf-cad/hbw/components.py`, `devices.py`,
`controller.py`, `electrical.py`), and the Asset Administration Shells link the makers' own
addresses instead (`stf-cad/hbw/aas/build.py`, `VENDOR`).

| File in `docs/` | What it is | Where the maker publishes it |
|---|---|---|
| `536634-Fabrik_Simulation_24V.pdf` | fischertechnik 536634 Fabrik Simulation 24V, booklet (de) | [fischertechnik.de](https://www.fischertechnik.de/-/media/fischertechnik/fite/service/elearning/simulieren/doku-24v/de/536634-fabrik_simulation_24v.pdf) |
| `536634-Fabrik_Simulation_24V-Belegungsplan.pdf` | the 24 V factory's I/O assignment plan | [fischertechnik technical documents](https://www.fischertechnik.de/en/industry-and-universities/technical-documents) |
| `536634-Factory-simulation-24V-extended-description.pdf` | extended description: adaptor PCBs, connector pins | [fischertechnik technical documents](https://www.fischertechnik.de/en/industry-and-universities/technical-documents) |
| `144643-Encodermotor24V.pdf` | encoder motor 24 V, datasheet | [fischertechnik technical documents](https://www.fischertechnik.de/en/industry-and-universities/technical-documents) |
| `37783-Mini-switch.pdf` | mini switch, datasheet | [fischertechnik technical documents](https://www.fischertechnik.de/en/industry-and-universities/technical-documents) |
| `36134-Photo-transistor.pdf` | phototransistor, datasheet | [fischertechnik technical documents](https://www.fischertechnik.de/en/industry-and-universities/technical-documents) |
| `128599-Color-sensor.pdf` | colour sensor, datasheet | [fischertechnik technical documents](https://www.fischertechnik.de/en/industry-and-universities/technical-documents) |
| `Datenblatt_RevPi_DIO.pdf` | KUNBUS RevPi DIO 100197, datasheet | [revolutionpi.com](https://revolutionpi.com/shop/en/mwdownloads/download/link/id/51) |
| `Datenblatt_RevPi_Cores.pdf` | KUNBUS RevPi Core S 100359, datasheet | [revolutionpi.com](https://revolutionpi.com/fileadmin/downloads/datasheets/Technical_Datasheet_RevPi-Core-all.pdf) |
| `PowerSupply WDR DIN rail.pdf` | Mean Well WDR-120 DIN-rail supply | [meanwell.com](https://www.meanwell.com/Upload/PDF/WDR-120/WDR-120-SPEC.PDF) |
| `Website.pdf` | fischertechnik's product page for 536634, printed | [fischertechnik.de](https://www.fischertechnik.de/en/products/industry-and-universities/training-models/536634-factory-simulation-24v) |

Removing the files from the current tree does not remove them from the repository's history:
older commits still hold them until the history is rewritten (for example with
`git filter-repo --path-glob 'docs/*.pdf' --invert-paths`, followed by a force push).
