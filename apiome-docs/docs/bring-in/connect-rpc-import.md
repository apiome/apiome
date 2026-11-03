---
title: "Import a Connect-RPC service"
description: "Catalog Connect services from their Protobuf contract, with each method's HTTP/JSON route."
sidebar_position: 50
tags: [import, connect, connectrpc, protobuf, buf, grpc, rpc, http, json]
---

The **Connect RPC** importer (`connectrpc`) reads the Protobuf contract a
[Connect](https://connectrpc.com/) service is defined in and catalogs it into the
[Catalog](./catalog.mdx). Connect reuses the `.proto` grammar gRPC uses, so the contract is compiled
with the same `buf` toolchain: messages and enums become types, and every `rpc` becomes an
operation. What Connect adds is a fixed way to reach each method over plain HTTP, and the catalog
item records it: the item is tagged as Connect, and every method carries the route and content types
a Connect client uses. You can then search, version, diff, lint and convert it like any other catalog
item.

## Import it

Import the contract like any other catalog format: in the [import wizard](./import-wizard.mdx)
(**Import to catalog** → **Connect RPC**), over the REST API (see
[Import a specification](./import-a-spec.md)), or from the CLI:

```bash
apiome import connectrpc ./greeter.proto
apiome import connectrpc ./greeter-module.zip
```

- **One file.** Upload, paste or link the `.proto` file.
- **A Buf module.** Upload a `.zip`, `.tar.gz` or `.tar` that holds the `.proto` files, the ones they
  import, and the module's Buf configuration (`buf.yaml`, `buf.gen.yaml`). The archive is compiled
  as one module.
- **A live endpoint.** Give the address of a running service that exposes gRPC server reflection;
  the contract is fetched from it, as for a gRPC import.

The examples in `apiome-ui/examples/connectrpc/` are a quick way to try it: `01-greeter.proto` is a
single service with a unary and a server-streaming method, and `06-payments-set/` is a two-file set.

## How a Connect service is recognised

A Connect service is an ordinary Protobuf service, so **Auto-detect** has to tell it apart from gRPC.
Three signals do, strongest first:

| Signal | Where it is read | Example |
| --- | --- | --- |
| Connect named in the contract | A comment, option or path inside the `.proto` | `// Served with connect-go`, `buf.build/connectrpc/...` |
| A Buf configuration that targets Connect | The `buf.gen.yaml` or `buf.yaml` next to the `.proto` in an uploaded archive or a scanned repository | A plugin such as `buf.build/connectrpc/go` or `protoc-gen-connect-es`, or a dependency on `buf.build/connectrpc` |
| A Connect-oriented path | The file's path in the archive or repository | `connect/greet/v1/greet.proto`, `connectrpc/...` |

A `.proto` with none of these is imported as **gRPC / Protobuf**. The Buf configuration is the
usual signal for a real module: its `.proto` files rarely say "Connect", while its `buf.gen.yaml`
always names the Connect generator. The **Dry run** on the wizard's **Options** step shows which
signal decided, as does the detection reason the REST API returns.

## What the item records

Beyond the types, services and operations every Protobuf import records (see
[What an import records](./what-an-import-records.md)), a Connect item carries:

| Where | Key | Value |
| --- | --- | --- |
| The item | `format` | `connectrpc` |
| The item | `rpc_stack` | `connect`: the protocol facet the Catalog filters on |
| The item | `connect.route_template` | `/{package.Service}/{Method}`, the route every method is served on |
| The item | `connect.unary_content_types`, `connect.streaming_content_types` | The bodies Connect accepts for unary calls and for streams |
| Each operation | `http` | The method's binding: `POST` and its route, such as `/greet.v1.GreetService/Greet` |
| Each operation | `connect.content_types` | `application/json` and `application/proto` for a unary call; `application/connect+json` and `application/connect+proto` for a client-, server- or bidirectional-streaming call |
| Each operation | `connect.streaming` | Whether the method streams |

The same contract imported as **gRPC / Protobuf** records none of the Connect keys: the binding is
what the Connect tag adds, and it is why the two formats stay distinct catalog items even though
they compile the same descriptor set.

## Convert to OpenAPI

[Converting](./convert-to-openapi.md) a Connect item to an OpenAPI project uses the recorded route
for every operation: `POST /greet.v1.GreetService/Greet` with the request message as the request
body and the response message as the `200` body. Because the route is declared by the protocol
rather than guessed, the conversion no longer reports a synthesized HTTP binding for it. A streaming
method keeps its route and is marked `x-apiome-streaming`, as OpenAPI has no streaming
representation.

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): Connect's coverage and export support
- [What an import records](./what-an-import-records.md): the model every catalog item is stored as
- [Convert to OpenAPI](./convert-to-openapi.md): how an RPC item becomes an OpenAPI project
- [RPC and event formats](./rpc-and-event-formats.mdx): every RPC, event and IDL importer, and how they work together.
