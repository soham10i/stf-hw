# OPC UA companion NodeSets

Unchanged from the OPC Foundation's repository <https://github.com/OPCFoundation/UA-Nodeset>, release tag
`UA-1.05.06-2025-11-08`, under the OPC Foundation MIT License 1.00 (in each file's header).

| File | Model | Version |
|---|---|---|
| Opc.Ua.Di.NodeSet2.xml | OPC 10000-100 Devices (DI) | 1.04.0 |
| Opc.Ua.IA.NodeSet2.xml | OPC 10000-200 Industrial Automation (IA) | 1.01.4 |
| Opc.Ua.Machinery.NodeSet2.xml | OPC 40001-1 Machinery | 1.04.0 |

The newest DI (1.05.0) is not used: Machinery 1.04 requires DI 1.04, and asyncua cannot place one of
DI 1.05.0's nodes (`Configuration`, which has no parent in that file).
