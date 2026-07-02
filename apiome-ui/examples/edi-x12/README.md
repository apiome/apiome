# EDI X12 example

`01-850-purchase-order.edi` is an **ANSI ASC X12 850 Purchase Order** (version
004010). X12 EDI is a flat, segment-oriented format:

- The interchange is framed by `ISA`/`IEA` envelopes and `GS`/`GE` functional
  group envelopes; the transaction set itself is framed by `ST`/`SE`.
- `ST*850*...` names the transaction set (850 = Purchase Order). Other common
  sets: 810 (invoice), 856 (advance ship notice), 837 (healthcare claim).
- Within a segment, elements are `*`-delimited and segments end with `~`.

A catalog import maps a transaction set to a class and each segment/element to a
property (e.g. `PO1` line items → a repeating LineItem property; `N1` → a party
class). The delimiters are declared in the `ISA` header (positions are fixed-width
in `ISA`, which is why it is padded).
