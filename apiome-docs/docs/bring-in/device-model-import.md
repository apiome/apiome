---
title: "Import LwM2M and Matter device models"
description: "Catalog LwM2M / IPSO objects and Matter clusters and device types."
sidebar_position: 28
tags: [import, lwm2m, ipso, matter, iot, device-model]
---

IoT devices publish their interfaces as **device models**: OMA **LwM2M** object definitions
(including the **IPSO** smart objects) and **Matter** cluster and device-type definitions. Both are
XML registries. Apiome reads them into the [Catalog](./catalog.mdx) so you can search, version,
diff and convert a device's interface like any other API:

- **LwM2M / IPSO objects** (`lwm2m`) become a **data schema**: objects as records, resources as
  fields, executable resources as operations.
- **Matter clusters and device types** (`matter`) become an **RPC** API: clusters as records of
  their attributes, commands as request/response operations, events as subscriptions, and a device
  type as the set of clusters it is made of.

Apiome reads the definition files you supply. It does not crawl the public LwM2M or Matter
registries.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One LwM2M object definition file (`3303.xml`) | One catalog item with one record per object in the file |
| Several LwM2M object files in an archive (`.zip`, `.tar.gz`), one per object as the registry publishes them | One catalog item with every object. The item is named after the object in the root file |
| One Matter cluster definition file | One catalog item with the cluster, its enums, bitmaps and structs |
| A Matter device type in an archive beside the cluster files it includes | One catalog item named after the device type. The device type links to the clusters in the archive |

Apiome recognises an LwM2M file by its `<LWM2M>` root element with `<Object>` definitions, and a
Matter file by its `<configurator>` root element with a `<cluster>` or `<deviceType>`. In an archive,
files with a different root (a README, another XML vocabulary) are ignored.

## Import it

Import the file or the archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks **LwM2M / IPSO objects** (`lwm2m`) or
**Matter clusters and device types** (`matter`).

**Import a device type together with its clusters.** A Matter device type only names the clusters it
includes. Put the device type and the cluster files in one archive so Apiome can link them. A cluster
that is not in the archive is kept, and listed as unresolved.

## What each part becomes: LwM2M

| LwM2M | In the catalog item |
| --- | --- |
| An `Object` (`Temperature`, id 3303) | A **record** `Temperature`. Names become identifiers: `Firmware Update` is `FirmwareUpdate`. The object id, URN, versions and instance rules are kept on the record |
| A resource with `Operations` `R`, `W` or `RW` | A **field**, numbered by its resource id. The access mode is kept on the field as `read`, `write` or `read-write` |
| A resource with `Operations` `E` (executable) | A **one-way operation** of the service `<Object>Service`, not a field |
| `Mandatory` | A required field. `Optional` resources are optional fields |
| `MultipleInstances` `Multiple` | A list |
| `String`, `Integer`, `Unsigned Integer`, `Float`, `Boolean`, `Opaque` | `string`, `int64`, `uint64`, `double`, `boolean`, `bytes` |
| `Time` | `int64` with the format `unix-time` |
| `Corelnk` | `string` with the format `core-link` |
| `Objlnk` | The record `Objlnk` (object id and instance id). Apiome names this record, so it is labelled **synthesized** |
| `RangeEnumeration` `0..100` | Minimum 0 and maximum 100. On a `String` or `Opaque` resource, a minimum and maximum length |
| `RangeEnumeration` `0, 1, 2` | The permitted values 0, 1 and 2 |
| `Units` (`Cel`, `%`) | The field's unit |

On a multi-instance resource, the range applies to each instance.

## What each part becomes: Matter

| Matter | In the catalog item |
| --- | --- |
| A `cluster` (`On/Off`, `0x0006`) | A **record** `OnOff` with one field per attribute, and a service `OnOffService` |
| An `attribute` | A **field**, numbered by its attribute id. `writable` makes its access `read-write`, otherwise `read`; `access` privileges are kept beside it |
| `optional` or `isNullable` | An optional field |
| `min`, `max` | A minimum and maximum |
| `length`, `minLength` | A maximum and minimum length, or the maximum and minimum number of items on a list |
| `default` | The field's default value |
| `type="array"` with `entryType`, or `array="true"` | A list |
| `int8u` … `int64s`, `boolean`, `char_string`, `octet_string`, `single`, `double` | The matching scalar, such as `uint8`, `int64`, `boolean`, `string`, `bytes`, `float`, `double` |
| A semantic type (`temperature`, `percent100ths`, `epoch_s`, `vendor_id` …) | Its base scalar. The written type is kept on the field |
| A `command` with `source="client"` | A **request/response operation**. Its arguments become the record `<Cluster>.<Command>Request` |
| A `command` with `source="server"` | The record a client command's `response` names, used as that operation's response |
| An `event` | A **subscribe** operation carrying the record `<Cluster>.<Event>Event`. Its priority is kept |
| An `enum` | An **enum** |
| A `bitmap` | An **enum** of its flag masks |
| A `struct` | A **record** |
| A `deviceType` | A **record** named after the device type, with one field per included cluster, typed by that cluster's record |

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **An object link's target** (LwM2M): an `Objlnk` resource does not say which object it links to,
  so it is typed as the generic `Objlnk` record.
- **An unreadable range** (LwM2M): a `RangeEnumeration` that is neither `a..b` nor a list of values
  sets no constraint. The text is kept on the field.
- **A standard type that is not declared** (Matter): a member of a standard cluster uses a type the
  upload does not declare. The Matter specification defines it, so the member is kept and typed as
  *any*.
- **A cluster outside the upload** (Matter): a device type includes a cluster whose file is not in
  the archive.
- **A bitmap** (Matter): a value can combine several flags, which an enum does not express.
- **Feature conformance** (Matter): a cluster's features are kept, but which members each feature
  enables is not evaluated.

## How Matter references resolve

| The member's type | What happens |
| --- | --- |
| A Matter base or semantic type (`int16u`, `temperature`) | Mapped to its scalar |
| An `enum`, `bitmap` or `struct` declared in the upload | Linked to it |
| A type not declared in the upload, on a **standard cluster** (code `0x0000` to `0x7FFF`) | Kept, typed as *any*, and listed as unresolved |
| A type not declared in the upload, on a manufacturer-specific or test cluster | **Refused** with `INPUT_REFERENCE_UNRESOLVED` |

A device type that requires an attribute or command its included cluster does not declare is
refused with `INPUT_REFERENCE_UNRESOLVED`.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The XML is not well formed, for example an element is never closed. |
| `INPUT_TRUNCATED` | The file ends in the middle of an element or attribute. |
| `INPUT_SEMANTIC_INVALID` | LwM2M: an object has no resources, a resource has an unknown `Type`, an `Operations` value other than `R`, `W`, `RW` or `E`, or an id is used twice. Matter: a cluster has no attributes, commands or events, a member has no type, an `array` has no `entryType`, or a name or code is used twice. Every problem is listed. |
| `INPUT_REFERENCE_UNRESOLVED` | A Matter reference the upload cannot account for (see [How Matter references resolve](#how-matter-references-resolve)). |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `INPUT_UNSAFE_CONSTRUCT` | The file declares a DTD or an entity. |
| `FORMAT_MISMATCH` | The root element is wrong: a Matter `configurator` file imported as LwM2M, or an `LWM2M` file imported as Matter. |

## Related

- [Supported formats](./supported-formats.md#format-lwm2m): what the LwM2M importer reads.
- [Supported formats](./supported-formats.md#format-matter): what the Matter importer reads.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why the `Objlnk` record is
  labelled synthesized.
- [Import a specification](./import-a-spec.md): the import job and its options.
