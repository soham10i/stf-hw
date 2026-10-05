# Sparkplug B schema

`sparkplug_b.proto` is the Sparkplug B payload definition from Eclipse Tahu
(<https://github.com/eclipse-tahu/tahu>, `sparkplug_b/sparkplug_b.proto`), copyright 2015, 2018
Cirrus Link Solutions and others, made available under the Eclipse Public License 2.0
(<https://www.eclipse.org/legal/epl-2.0/>). It is included unchanged.

`sparkplug_b_pb2.py` is generated from it:

    python -m grpc_tools.protoc --proto_path=. --python_out=. sparkplug_b.proto

The requirement IDs the proofs cite (`tck-id-…`) are those of the Eclipse Sparkplug 3.0.0
specification (<https://github.com/eclipse-sparkplug/sparkplug>, EPL-2.0), the basis of
ISO/IEC 20237:2023.
