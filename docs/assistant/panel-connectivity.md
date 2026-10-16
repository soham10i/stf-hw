# Panel: Connectivity

How the cell's data reaches other systems, three ways. They run on the edge computer between the
oven and the warehouse (see *Machine: Edge computer*). Each sub-tab starts with a *Verified* line:
what its checks proved, including how many planted mutants they caught (a check that cannot fail
proves nothing).

## Asset shells (IEC 63278)

Asset Administration Shells for the cell, its parts and its AI models, each submodel built from
its IDTA template and verified against the AAS v3 metamodel. Pick a shell, then a submodel
(Nameplate, TechnicalData, HierarchicalStructures, HandoverDocumentation, CarbonFootprint,
TimeSeries, Models3D). Hover a name for its semanticId; the arrow opens a part's own shell.
*AASX* downloads the package. The part shells are compiled from fischertechnik's public
datasheets, not issued by fischertechnik.

## OPC UA (IEC 62541)

An OPC UA server model using the Machinery companion specification on DI and IA: one node per
PLC signal, values from the PLC running in the browser. Search the address space by name, signal
or type. Folded: the five connection attempts that must fail (no security, anonymous, wrong
password, untrusted certificate, writing a variable) and the error each gets. *NodeSet2* downloads
the model.

## Sparkplug · UNS (MQTT Sparkplug B 3.0)

Edge node (the cell) -> Mosquitto broker (TLS 1.3, access list) -> primary host -> a Unified
Namespace of retained JSON topics in ISA-95 levels (enterprise / site / area / line / cell /
module / signal). Tabs: the namespace, Sparkplug births and data messages, the traffic on the
wire, the specification's testable requirements, death and rebirth, and security.
