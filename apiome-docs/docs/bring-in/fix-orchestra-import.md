---
title: "Import a FIX Orchestra repository"
description: "Catalog the declared FIX schema from an Orchestra repository."
sidebar_position: 23
tags: [import, fix, orchestra, finance, trading]
---

**FIX Orchestra** is the machine-readable specification of a FIX interface — a firm's or a venue's
"rules of engagement" as XML. Where the **FIX** importer reads `tag=value` messages and *infers* the
fields they use, the **FIX Orchestra** importer (`fix-orchestra`) reads the repository that
*declares* them: message definitions, field types, code sets, components, repeating groups, and
whether each field is required. The result is a schema in the [Catalog](./catalog.mdx) you can
version and diff.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| An Orchestra repository (`.xml`) | One catalog item with every message, component, group and code set |
| A repository with several scenarios of a message (`scenario="dark"`) | One record type per scenario |
| An archive (`.zip`, `.tar.gz`) of a repository and the files it pulls in with `xi:include` | One catalog item read from the repository with its includes resolved |
| A FIX `tag=value` message log (`8=FIX.4.4…`) | Not this importer — it imports as **FIX** |

Apiome recognises a repository by its root element: `repository` in the
`http://fixprotocol.io/2020/orchestra/repository` namespace (or the 2016 FIX Repository draft
namespace).

## Import a repository

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the repository — try
   `apiome-ui/examples/fix-orchestra/04-stress-presence-and-rules.xml` — or choose **Paste** and
   paste it. For a repository split across files, drop an archive of the folder (for example
   `apiome-ui/examples/fix-orchestra/07-modular-set/` zipped).
3. On **Detect & route**, Apiome reports **Auto-detected: FIX Orchestra** (`fix-orchestra`) and
   routes it to the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the file to the import endpoints with the source kind `fix-orchestra`; see
[Import sources](../reference/rest/import-sources.md).

## What Apiome reads

| In the repository | Becomes |
| --- | --- |
| Each `message` (`NewOrderSingle`, `msgType="D"`) | A record type named by the message; a non-`base` scenario is `NewOrderSingle_dark`. Its `msgType`, category, flow and `responses` are recorded on the type |
| Each `fieldRef` in a message's `structure` | A field named by the FIX field (`ClOrdID`), with the tag (`11`) as its field number |
| A field's `type` naming a `codeSet` | The field takes the code set's enum type |
| A field's `type` naming a datatype | A primitive: `int`, `Length`, `NumInGroup`… → integer; `Qty`, `Price`, `Amt`… → number; `Boolean` → boolean; everything else a string, with `date-time`, `date` or `time` for the timestamp types. Declared `datatypes` are followed through their `baseType` |
| Each `codeSet` | An enum type; each `code` is a value (`Buy` = `1`) |
| Each `component` and its `componentRef` | A record type, and a field of that type |
| Each `group` and its `groupRef` | A record type for one entry, and a **list** of it with at least one entry; the `numInGroup` counter (`NoPartyIDs`, `453`) is recorded on the field. Groups may nest |
| A field's or ref's `documentation` | The field's description |
| `actors`, `flow` (with `reliability`) and an actor's `states` / `transition` state machine | Recorded on the item, so a changed workflow is a new version |
| The repository's `name` and `version` (`FIX.4.4_EP001`) | The item's identity; the Dublin Core `metadata` title is its title |

The repository's `metadata` (`dc:date`, `dc:creator`…) is kept with the source but is not part of
the contract, so re-dating an otherwise unchanged repository is the same version.

## Presence

Every `fieldRef`, `componentRef` and `groupRef` carries a `presence`. Apiome maps it onto the
field's optionality and constraints. **No field is ever dropped for its presence.**

| `presence` | The field is | Constraint recorded |
| --- | --- | --- |
| `required` | Required | — |
| `optional` (or none given) | Optional | — |
| `conditional` | Optional | `fix_presence: conditional`, plus each `rule` with its `when` expression (`OrdType in {"^Limit"}`) |
| `forbidden` | Optional | `fix_presence: forbidden` — a declared constraint: the field must not be sent |
| `ignored` | Optional | `fix_presence: ignored` — accepted on the wire, never acted on |
| `constant` | Required | The fixed `value` as the only allowed value, and as the default |

A rule with an `assign` expression (`OrderQty > 0`) is recorded on the field the same way. Because
presence is part of the contract, changing a field from `optional` to `forbidden` shows in the
version diff.

## Link it to FIX messages

The repository records the `msgType` of every message it declares, and a **FIX** message item
records its own. On either item's detail page, in **Related artifacts**, **click "Suggest links"**:
an Orchestra repository and a FIX message with the same message type (`D` for NewOrderSingle) are
suggested for each other, with the reason **shared FIX message type(s) D**. Nothing is linked until
you link it.

Try it with `apiome-ui/examples/fix-orchestra/02-typical-order-repository.xml` and
`apiome-ui/examples/fix/01-newordersingle.fix`.

## Supported versions

| Version | How it is read |
| --- | --- |
| FIX Orchestra 1.0 repository (and the 2016 FIX Repository draft namespace) | In full. The FIX version the repository describes (`FIX.4.4`, `FIX.Latest_EP…`) is recorded, not branched on |

FIX Orchestra is **import only** for now: the Orchestra exporter is planned separately.

## When an import is refused

| What is wrong | Error code |
| --- | --- |
| The XML stops partway through | `INPUT_TRUNCATED` |
| The XML is not well formed | `INPUT_MALFORMED` |
| The repository declares no messages; a field, component, group, code set or message has no `id` or `name`; an entity is declared twice in one scenario; a `presence` is not one of the six values | `INPUT_SEMANTIC_INVALID` |
| A ref points at a field, component or group the repository does not declare, a group's `numInGroup` names an unknown field, or an `xi:include` names a file that was not uploaded with it | `INPUT_REFERENCE_UNRESOLVED` |
| The file is not an Orchestra repository — a FIX `tag=value` message log, for one | `FORMAT_MISMATCH` |
| The file is not UTF-8 text (UTF-16, for example) | `INPUT_ENCODING_INVALID` |
| The XML declares a DTD or an entity | `INPUT_UNSAFE_CONSTRUCT` |

An `xi:include` is only ever resolved against the other files of the same upload — never fetched
from a URL or read from disk. A single uploaded file that uses one is refused; upload the folder as
an archive instead.

## Related

- [Supported formats](./supported-formats.md): every format and the versions it reads.
- [Import a spec](./import-a-spec.md): every way to bring a document in.
