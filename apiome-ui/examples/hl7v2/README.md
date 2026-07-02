# HL7 v2 example

`01-adt-a01.hl7` is an **HL7 v2.5 ADT^A01** ("admit/visit notification") message
in the classic pipe-and-hat encoding. HL7 v2 is identified by the `MSH|^~\&|`
header that begins every message; the field separator (`|`), the message type
(`ADT^A01` in MSH-9), and the version (`2.5` in MSH-12) all live in that first
segment.

Each line is a **segment** (MSH = message header, EVN = event, PID = patient
identification, NK1 = next of kin, PV1 = patient visit). Within a segment, fields
are `|`-separated and components are `^`-separated. A catalog import maps each
segment/field to the equivalent of a class and its properties (e.g. PID → a
Patient class with name, DOB, address, and identifier properties).

> Note: the file uses a literal CR/LF per line for readability; strict HL7 v2 uses
> a carriage-return (`\r`) segment terminator. Most parsers accept both.
