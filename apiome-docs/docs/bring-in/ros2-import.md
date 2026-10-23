---
title: "Import ROS 2 interfaces"
description: "Catalog ROS 2 messages, services and actions from .msg, .srv and .action files."
sidebar_position: 26
tags: [import, ros2, robotics, msg, srv, action]
---

**ROS 2** robots talk through typed **interfaces**: messages (`.msg`), services (`.srv`) and
actions (`.action`), grouped into interface packages. The **ROS 2 interfaces** importer (`ros2`)
reads those files into the [Catalog](./catalog.mdx) as an **RPC** API you can search, version and
diff — and, because AsyncAPI 3.1 added ROS 2 bindings, convert to the standards the rest of your
estate already speaks.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| One `.msg` file | One catalog item with one record, plus an enum for the message's constants |
| One `.srv` file | One catalog item with a request and a response record and one request/response operation |
| One `.action` file | One catalog item with goal, result and feedback records, a goal operation and a feedback channel |
| An interface package in an archive (`.zip`, `.tar.gz`): `package.xml` beside its `msg/`, `srv/` and `action/` files | One catalog item named after the package, with every interface. References between the files are resolved |
| Several packages in one archive | One catalog item. A reference from one package to another resolves too |

Apiome recognises an interface file by its lines: every line is a field (`float32 voltage`), a
constant (`uint8 STATE_EMPTY=0`), a comment or a `---` separator. It recognises a package by a
`package.xml` that is a member of `rosidl_interface_packages` or builds with
`rosidl_default_generators`. Files other than `package.xml` and interface files (`CMakeLists.txt`,
a README) are ignored.

## Import it

Import the file or the archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome picks **ROS 2 interfaces** (`ros2`).

**Keep the file name.** The interface's name is its file name (`BatteryState.msg` is the
`BatteryState` message), and the extension says whether it is a message, a service or an action. A
pasted interface with no name is called `Message`, `Service` or `Action`, by how many `---`
sections it has.

**Import the whole package when its files refer to each other.** A field typed by a bare name
(`LoadCell[] cells`) names a message of the same package. In an archive, Apiome links it to that
message. A file imported on its own cannot see its siblings, so the field is kept and the reference
is listed as unresolved.

## What each part becomes

| ROS 2 | In the catalog item |
| --- | --- |
| A message (`LoadCell.msg`) | A **record** `LoadCell`. In a package it is keyed by the package: `my_robot_msgs.LoadCell` |
| A service (`LiftPallet.srv`) | Records `LiftPallet_Request` and `LiftPallet_Response`, and a **request/response** operation `LiftPallet` |
| An action (`NavigateToPose.action`) | Records `NavigateToPose_Goal`, `NavigateToPose_Result` and `NavigateToPose_Feedback`; a **request/response** operation `NavigateToPose` (goal in, result out); and a **subscribe** operation on the channel `NavigateToPose/_action/feedback`, which carries the feedback. The interface does not name the action at run time, so the interface name stands in for it and the channel is labelled **synthesized** |
| Constants (`uint8 STATE_EMPTY=0`) | An **enum** `<record>_Constants` with one member per constant and its value. Apiome names this enum, so it is labelled **synthesized** |
| `bool`, `int8` … `uint64`, `float32`, `float64` | `boolean`, `int8` … `uint64`, `float`, `double` |
| `byte`, `char` | `uint8` |
| `string`, `wstring` | `string`. A `wstring` is listed in the coverage ledger, because it is UTF-16 on the wire |
| `string<=32` | A string with a maximum length of 32 |
| `float64[]` | A list |
| `float64[3]` | A list of exactly 3 items (minimum and maximum items 3) |
| `float64[<=10]` | A list of at most 10 items |
| `string<=8[<=4]` | A list of at most 4 items, each at most 8 characters |
| A default (`float32 max_speed 0.55`, `bool[3] mask [true, false, true]`) | The field's default value |
| A comment above a field, or after it on the same line | The field's description. The comment block at the top of the file describes the interface |
| `package.xml` | The item's name, namespace, version and description; its dependencies are kept |

The written ROS 2 type of every field (`string<=8[<=4]`) is kept on the field. Every field is always
present on the wire, so no field is optional.

## How references resolve

| The field's type | In a package archive | In a single file |
| --- | --- | --- |
| A bare name (`LoadCell`) | Must be a message of the same package in the archive | Kept, and listed as an **unresolved sibling reference** |
| A message of a package in the archive (`my_robot_msgs/LoadCell`) | Must be in the archive | — |
| A message of a standard ROS 2 package (`std_msgs/Header`, `geometry_msgs/Pose`, `builtin_interfaces/Duration` …) | Kept, and listed as an **unresolved external reference** | Same |
| A message of a package that `package.xml` declares as a dependency | Kept, and listed as an **unresolved external reference** | — |
| A message of any other package | **Refused** with `INPUT_REFERENCE_UNRESOLVED` | Same |

An unresolved field is typed as *any* and names the message it refers to, such as
`std_msgs/msg/Header`. To resolve it, put that package's interface files in the same archive.

## What is declared, not imported

Apiome records these in the import's coverage ledger instead of guessing:

- **An external reference**: a field typed by a message of a package that is not in the upload.
- **A sibling reference**: a field typed by a bare name, in a file imported without its package.
- **A wide string**: a `wstring` is read as a string; its UTF-16 encoding is kept on the field.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | A line is neither a field nor a constant: a type with no name, an unknown type, a field name that is not `lower_snake_case`, a constant name that is not `UPPER_CASE`, a default that does not fit its type (`uint8 x 300`), a default on a message-typed field, or a `.msg` with a `---` separator. Every bad line is listed, with its number. |
| `INPUT_TRUNCATED` | A `.srv` with only one section, or an `.action` with fewer than three. The file looks cut short. |
| `INPUT_SEMANTIC_INVALID` | The interface has no fields and no constants, a name is declared twice, an archive holds no interface files, or `package.xml` names no valid package. |
| `INPUT_REFERENCE_UNRESOLVED` | A reference the upload cannot account for (see [How references resolve](#how-references-resolve)). |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |
| `FORMAT_MISMATCH` | No line reads as a ROS 2 field or constant, such as a Protocol Buffers `.proto` file. |

## Related

- [Supported formats](./supported-formats.md#format-ros2): what this importer reads.
- [Declared, inferred and synthesized](./inference-provenance.mdx): why the constants enum and the
  feedback channel are labelled synthesized.
- [Import a specification](./import-a-spec.md): the import job and its options.
