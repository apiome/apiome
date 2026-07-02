# FIX / FIX Orchestra examples

Two complementary artifacts for the **FIX** (Financial Information eXchange)
protocol:

## `01-newordersingle.fix` — a FIX message instance

A single **NewOrderSingle** (`35=D`) message in the classic tag=value encoding.
FIX messages are a sequence of `tag=value` pairs delimited by the SOH control
character (ASCII 0x01); for readability this sample uses a `|` placeholder in
place of SOH. Key tags: `8` (BeginString / version), `35` (MsgType), `55`
(Symbol), `54` (Side), `38` (OrderQty), `40` (OrdType), `44` (Price). A catalog
import maps a message type to a class and each tag to a typed property.

## `02-orchestra.xml` — a FIX Orchestra service description

**FIX Orchestra** is the machine-readable, XML form of a FIX "rules of
engagement": it formally describes the messages, fields, code sets, and workflow a
counterparty supports. This is the schema/contract form (analogous to OpenAPI for
REST) — `<fixr:repository>` is the root, `<fixr:messages>` define the message
classes, `<fixr:fields>`/`<fixr:codeSets>` define the typed properties and enums.
