# UN/EDIFACT — `edifact`

Fixtures for **FMT-6.1** ([#5445](https://github.com/apiome/apiome/issues/5445)), with the EANCOM and
ODETTE dialect samples **FMT-6.5** ([#5449](https://github.com/apiome/apiome/issues/5449)) needs.
Apiome reads ANSI X12; EDIFACT is its rest-of-world twin, and every EDI platform in the market
documents both. Every entry is read by the `edifact` adapter (`apiome-rest/src/app/edifact_import_source.py`).

**Detection marker.** A `UNB` interchange header (optionally preceded by `UNA` service string advice)
followed by `UNH` message headers.

**Delimiters.** Default `+` (element), `:` (component), `'` (segment terminator), `?` (release),
`.` (decimal). `UNA` overrides them, and two fixtures here declare a **comma decimal mark**
(`UNA:+,? '`) to prove the parser reads the advice rather than assuming.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-orders-d96a.edi` | minimal | One ORDERS message, no `UNA`, defaults apply. |
| `02-typical-invoic-d96a.edi` | typical | INVOIC with `UNA`, addresses, taxes, currencies, summary totals. |
| `03-typical-desadv-d01b.edi` | typical | DESADV D.01B: despatch advice with packaging (`PAC`/`MEA`/`GIN`) and transport (`TDT`). |
| `04-stress-multi-message-group.edi` | stress | Two `UNG`/`UNE` functional groups, three messages, comma decimal mark, a release character (`?,`), an empty `LIN` element set. |
| `05-real-world-eancom-orders.edi` | real-world | EANCOM ORDERS: GS1 GLNs as party ids, `PIA`/`IMD`/`LOC`, association code `EAN008` in `UNH` — read with the **EANCOM profile**. |
| `06-typical-odette-delfor.edi` | typical | ODETTE DELFOR delivery schedule: `SCC`/`QTY 113` schedule lines per delivery date, ODETTE organisation codes — read with the **ODETTE/VDA profile**. |
| `07-stress-control-count-mismatch.edi` | stress | `UNT` claims 99 segments and `UNZ` claims 7 interchanges; both are wrong. This must **import with warnings**, showing declared *and* observed counts — not reject. |
| `08-composition-nested-segment-groups.edi` | composition | Nested segment groups: party → contact → communication, line → tax → allowance/charge. |
| `09-interchange-set/` | multi-file | An ORDERS interchange plus the CONTRL acknowledgment that refers to it by control reference. |
| `negative/` | — | Missing segment terminator, an interchange with no message, truncation mid-segment, an **X12** interchange, and UTF-16. Plus a `UNH` with no `UNT`, and a **TRADACOMS** transmission sent to the EDIFACT importer (the FMT-6.5 misroute). |

**Dialect profiles (FMT-6.5).** Every interchange is recorded with the profile it was read with —
EANCOM (an `EAN` association code), ODETTE/VDA (an ODETTE subset designator, or an ODETTE organisation
code together with an ODETTE/VDA message), or plain UN/EDIFACT — in the import's provenance, the
canonical `format_profile` extras and the analysis. TRADACOMS has its own directory and adapter.

**The honesty contract this corpus assumes.** Mirroring the X12 analyzer exactly: declared-versus-
observed control counts on `UNT`/`UNE`/`UNZ`, the five-way element presence vocabulary (has value /
present-empty / withheld / not present / not recorded), the same value-visibility policy, the
canonical model derived from the **first** group's first message with a warning when the interchange
carried more — and an explicit statement that **no implementation guide (D.96A, D.01B, EANCOM…) was
consulted**.
