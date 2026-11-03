---
title: "Import CORBA IDL (OMG IDL) definitions"
description: "Catalog CORBA interfaces, operations and types, with lint and GIOP-aware diff rules."
sidebar_position: 23.3
tags: [import, corba, corbaidl, omg-idl, idl, rpc, legacy, lint]
---

**CORBA** (Common Object Request Broker Architecture) is the distributed-object RPC standard of
the OMG. It still runs inside telecom, defense and finance back-ends. Its contracts are written
in **OMG IDL**: `module`s hold `interface`s (remote objects) with operations and attributes,
plus the `struct`, `exception`, `enum` and `typedef` declarations they exchange. On the wire,
CORBA's GIOP protocol invokes an operation by name and encodes its values positionally in CDR.
The **CORBA IDL** importer (`corbaidl`) reads an `.idl` file into the [Catalog](./catalog.mdx),
so the interfaces can be searched, versioned, diffed and linted like any other catalog item.

## What you can import

An OMG IDL file:

```idl
module Brokerage {
  typedef string<12> Symbol;
  enum Side { BUY, SELL };

  struct Order {
    Symbol symbol;
    Side side;
    long quantity;
  };

  exception Rejected { string reason; };

  interface Auditable {
    readonly attribute string auditId;
    void audit(in string note);
  };

  interface Account : Auditable {
    attribute string nickname;
    string place(in Order order, inout double price) raises (Rejected);
    oneway void heartbeat(in long seq);
  };
};
```

Apiome reads:
- nested modules, which are flattened into one namespace;
- interfaces, including `abstract` and `local` ones and those that inherit from other
  interfaces (`interface Account : Auditable`);
- operations, with `in` / `out` / `inout` parameters, `raises` clauses and `oneway`;
- attributes, including `readonly` ones and several names in one declaration;
- structs, exceptions, enums and typedefs, with bounded `string<N>` and `sequence<T, N>`;
- IDL 4 annotations (`@key`, `@optional`), which are accepted and skipped.

Forward declarations (`interface Account;`) are skipped, and unions, constants and value types
are not modelled.

A file that contains an `#include` line is not recognised as IDL: the importer reports it as a
different format (Thrift, which also writes `include "…"`). Paste the included definitions into
the file, or remove the `#include` line, before importing.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the `.idl` file (try
   `apiome-ui/examples/corba-idl/06-cosnaming.idl`), or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: CORBA IDL** (`corbaidl`) and routes
   it to the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the file to the import endpoints with the source kind `corbaidl`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import corbaidl ./06-cosnaming.idl
```

The six examples in `apiome-ui/examples/corba-idl/` cover a bank, an inventory, a minimal echo
service, nested modules, a trading system with every parameter direction and `oneway`, and a
reconstruction of the OMG Naming Service (`CosNaming`).

## What Apiome reads

| In the file | Becomes |
| --- | --- |
| Each `interface` | A **service**. The interfaces it inherits from are listed in `corbaidl_bases`. |
| Each operation | An **operation** keyed `<module>.<Interface>.<operation>`. Its request carries the `in` / `inout` parameters, its response the return value, and there is one error message per `raises` exception. |
| A `oneway` operation | A **one-way** operation, with no response |
| Each `attribute` | The operations CORBA gives it: `_get_<name>` returns its value and, unless `readonly`, `_set_<name>` sets it |
| Operations and attributes an interface inherits | Copied into the derived interface's service, because a client calls them on the derived object. `corbaidl_inherited` records which base each one comes from. |
| Each `struct` and `exception` | A **record type**. Each member keeps its declared IDL type (`corbaidl_type_expr`), and a `string<N>` or `sequence<T, N>` bound becomes `max_length` or `max_items`. |
| Each `enum` | An **enum type**, with each enumerator's ordinal as its value |
| Each `typedef` | Resolved into the members and parameters that use it, and listed under `corbaidl_typedefs` |

## Versions and changes

Import a newer `.idl` file into the same item to add a version. A CORBA client calls an operation
by **name**, and CDR encodes parameters, return values and struct members **by position**, with no
tags or lengths. Enums travel as their **ordinal**. The comparison grades changes with those
rules:

| Change | Severity | Rule |
| --- | --- | --- |
| A parameter added or removed | Breaking: CDR is positional | `corbaidl.parameter-added`, `corbaidl.parameter-removed` |
| A parameter's type changed | Breaking | `corbaidl.parameter-type-changed` |
| A parameter's direction changed (`in` → `out`) | Breaking: it moved between request and reply | `corbaidl.parameter-direction-changed` |
| Only a parameter's name changed | Safe: names are not on the wire | `corbaidl.parameter-renamed` |
| The return type changed | Breaking | `corbaidl.return-type-changed` |
| An operation became, or stopped being, `oneway` | Breaking | `corbaidl.oneway-changed` |
| A `raises` exception added | Dangerous: an old client receives it as `CORBA::UNKNOWN` | `corbaidl.raises-added` |
| A `raises` exception removed | Safe | `corbaidl.raises-removed` |
| A struct member added, removed or reordered | Breaking: old readers misread every byte after it | `corbaidl.member-added`, `corbaidl.member-removed`, `corbaidl.member-reordered` |
| A member moved only because another was added or removed | Safe: that other change is graded on its own | `corbaidl.member-shifted` |
| A member's type changed | Breaking | `corbaidl.member-type-changed` |
| A `string<N>` / `sequence<T, N>` bound shrank | Breaking: old senders overflow it | `corbaidl.bound-narrowed` |
| A bound grew or was dropped | Dangerous: old receivers reject longer values | `corbaidl.bound-widened` |
| An enumerator removed, inserted before the end, or reordered | Breaking: ordinals shift | `corbaidl.enumerator-removed`, `corbaidl.enumerator-inserted`, `corbaidl.enumerator-reordered` |
| An enumerator appended at the end | Dangerous: old receivers cannot decode it | `corbaidl.enumerator-appended` |
| A struct became an exception, or back | Breaking | `corbaidl.kind-changed` |
| An interface no longer inherits from a base | Breaking | `corbaidl.base-removed` |
| An interface gained a base | Safe | `corbaidl.base-added` |

A removed interface or operation is breaking, and an added one is safe.

## Lint

The **Quality** step and the item's **Lint & score** tab add the `corbaidl` rules on top of the
common ones. Most of them catch what an IDL compiler (`idlj`, `omniidl`, `tao_idl`) would reject,
which the importer's reader lets through:

| Rule | Severity | Flags |
| --- | --- | --- |
| [`corbaidl.type-resolves`](../build/lint-rules.md#corbaidl-type-resolves) | Error | A type that is neither an IDL base type nor declared in the file |
| [`corbaidl.raises-declared`](../build/lint-rules.md#corbaidl-raises-declared) | Error | A `raises` clause naming a struct or an undeclared name |
| [`corbaidl.exception-as-type`](../build/lint-rules.md#corbaidl-exception-as-type) | Error | An exception used as a member, parameter, return or attribute type |
| [`corbaidl.oneway-signature`](../build/lint-rules.md#corbaidl-oneway-signature) | Error | A `oneway` operation that returns a value, has an `out` / `inout` parameter or raises |
| [`corbaidl.operation-names-unique`](../build/lint-rules.md#corbaidl-operation-names-unique) | Error | Two operations or attribute accessors of an interface (inherited ones included) whose names differ only in case |
| [`corbaidl.member-names-unique`](../build/lint-rules.md#corbaidl-member-names-unique) | Error | Two struct members, or two parameters, whose names differ only in case |
| [`corbaidl.identifier-not-keyword`](../build/lint-rules.md#corbaidl-identifier-not-keyword) | Error | A name that is an IDL keyword compared case-insensitively (`Short`, `Sequence`) |
| [`corbaidl.inheritance-acyclic`](../build/lint-rules.md#corbaidl-inheritance-acyclic) | Error | An interface that inherits from itself |
| [`corbaidl.base-interface-declared`](../build/lint-rules.md#corbaidl-base-interface-declared) | Warning | A base interface the file does not declare, so its operations are missing |
| [`corbaidl.any-typed`](../build/lint-rules.md#corbaidl-any-typed) | Info | An `any` value: the contract does not say what it carries |
| [`corbaidl.object-reference-typed`](../build/lint-rules.md#corbaidl-object-reference-typed) | Info | The untyped `Object` reference: name the interface instead |

## Export

A CORBA IDL item writes back out as OMG IDL through the **CORBA IDL** target, with its base
interfaces, attributes and `oneway` operations as declared; see
[Export a spec](../ship/export-a-spec.md). To move a CORBA service to gRPC, export the item to
**Protocol Buffers**.

## When an import is refused

| Message | Why | What to do |
| --- | --- | --- |
| `Content does not appear to be a CORBA IDL definition` | The file has no `module` or `interface` with IDL declarations, it contains an `#include` line, or it is another format (a `.proto`, a UTF-16 file) | Remove the `#include` (inline what it brings in), pick the right format, or save the file as UTF-8 |
| `No struct, exception, enum, or interface definitions found…` | An `interface` or `module` is not closed, or the file is cut off | Close every block with `};` |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): CORBA IDL's coverage and export support
- [Import ONC RPC (XDR) definitions](./oncrpc-import.md): another positional RPC format
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
- [Legacy, mainframe and middleware formats](./legacy-and-mainframe-formats.mdx): every legacy, mainframe and middleware importer, and how they work together.
