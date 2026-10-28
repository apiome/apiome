# RC8 — Plan (after RC7)

_Drafted 2026-10-28 against `main` @ `844cb2240`. RC8 is the release after RC7. It starts with
everything [`RC7_SHIP_PLAN.md`](RC7_SHIP_PLAN.md) leaves out, and RC8's other features are added
here as they are planned._

**Status: plan only.** No ticket has been moved or filed and no milestone exists yet. §8 lists the
milestone moves.

---

## 0. What is in RC8

| Section | What | Source |
| --- | --- | --- |
| §1 | RC7 tickets that miss the RC7 release (carry-over) | RC7_SHIP_PLAN §1 item 8 |
| §2 | New export targets and output modes, ranked | RC7 format gap analysis (2026-10-28) |
| §3 | Deferred import/export work already ticketed: new targets, delivery, presets and schedules, the MCP export surface, test-drive, visualizations, enterprise ops UX, cross-format breaking semantics | Formerly "move to Future" (RC7_SHIP_PLAN §11.4) |
| §4 | Formats considered and not planned, with the reason to close their tickets | RC7 format gap analysis |
| §5 | Issues that are not import or export, moved out of the RC7 milestone | RC7_CATALOG_IMPORT_EXPORT §8 |
| §6 | Other open features to plan for RC8 | The 2026-10-28 audit's out-of-scope list |
| §7 | The MFI umbrella | — |

---

## 1. Carry-over from RC7

Any RC7 ticket not closed when RC7 ships moves here, with one line saying why. MVP tickets cannot
carry over: they block RC7. Only V2 tickets can.

| R7 ticket | Reason | Moved on |
| --- | --- | --- |
| _none yet_ | | |

---

## 2. New export targets and output modes (ranked)

From the RC7 format gap analysis (2026-10-28). Each extends an existing emitter or adds one target.
Every new target must meet the RC7 bar from day one:

- a loss report with all seven categories (RC7_SHIP_PLAN §3);
- a validator, or "not validated" shown;
- foreign-source goldens;
- zero silent loss in the conformance matrix.

| # | Target or mode | Ticket | Effort | Why |
| --- | --- | --- | --- | --- |
| 1 | SQL DDL emitter (ANSI + PostgreSQL/MySQL) | [#4311](https://github.com/apiome/apiome/issues/4311) | M | Highest demand of the new targets. Currently in the RC7 milestone: move it here |
| 2 | Bruno and Insomnia v5 output | [#4291](https://github.com/apiome/apiome/issues/4291) | M | Collections round trip; Bruno import exists |
| 3 | TypeScript types-only emitter | new (R8-FG1) | M | TypeScript types are already imported; code-adjacent schemas are a common ask |
| 4 | gRPC JSON transcoding / gRPC-Gateway options | [#4343](https://github.com/apiome/apiome/issues/4343) | M | gRPC estates fronted by REST |
| 5 | Apollo Federation subgraph output from any source | [#4344](https://github.com/apiome/apiome/issues/4344) | M | Federated GraphQL estates |
| 6 | Google Cloud API Gateway target | new (R8-FG2) | S–M | OpenAPI 2.0/3.0.x with `x-google-*` extensions; AWS and Azure already exist |
| 7 | MCP server manifest and A2A Agent Card emitters | [#4295](https://github.com/apiome/apiome/issues/4295), [#4296](https://github.com/apiome/apiome/issues/4296) | S each | Import exists for both; RC7 adds the MCP tool-definition dialect (R7-FG4) |
| 8 | OData V2 output option | new (R8-FG3) | M | SAP estates still run V2 |
| 9 | Zod emitter | new (R8-FG4) | M | Zod is imported; TypeScript-first teams |
| 10 | DBML + Prisma output modes | [#4312](https://github.com/apiome/apiome/issues/4312) | M | After SQL DDL. Currently in the RC7 milestone: move it here |
| 11 | Multi-format Schema Registry subjects | [#4183](https://github.com/apiome/apiome/issues/4183) | M | Confluent estates |
| 12 | Protobuf Editions output | new (R8-FG5) | S | Editions are imported but written as proto3; losses are already reported |
| 13 | Tyk OAS output | new (R8-FG6) | S | Tyk is imported; the gateway set is otherwise complete |
| 14 | UN/EDIFACT message-guide emitter | [#4146](https://github.com/apiome/apiome/issues/4146) | M | EDIFACT is imported; X12 already emits |
| 15 | Parquet / Arrow schema emitter | [#4317](https://github.com/apiome/apiome/issues/4317) | M | Arrow is imported |
| 16 | FHIR R5 output | [#4157](https://github.com/apiome/apiome/issues/4157) (R5 part; RC7 rebuilds R4) | S | After RC7's R7-EM17 rebuilds FHIR output from the model |

---

## 3. Deferred import/export work (existing tickets)

These move from *Future* (or no milestone) to **RC8**.

### 3.1 New targets and modes

- Ranked in §2: [#4146](https://github.com/apiome/apiome/issues/4146), [#4183](https://github.com/apiome/apiome/issues/4183), [#4291](https://github.com/apiome/apiome/issues/4291), [#4295](https://github.com/apiome/apiome/issues/4295), [#4296](https://github.com/apiome/apiome/issues/4296), [#4311](https://github.com/apiome/apiome/issues/4311), [#4312](https://github.com/apiome/apiome/issues/4312), [#4317](https://github.com/apiome/apiome/issues/4317), [#4343](https://github.com/apiome/apiome/issues/4343), [#4344](https://github.com/apiome/apiome/issues/4344).
- Agent interfaces, the rest of the epic: [#4297](https://github.com/apiome/apiome/issues/4297) (agents.json / llms.txt), [#4298](https://github.com/apiome/apiome/issues/4298), [#4299](https://github.com/apiome/apiome/issues/4299); epic [#4294](https://github.com/apiome/apiome/issues/4294).
- Data, the rest of the epics: [#4313](https://github.com/apiome/apiome/issues/4313) (Liquibase / Flyway; [#795](https://github.com/apiome/apiome/issues/795) is a duplicate), [#4314](https://github.com/apiome/apiome/issues/4314), [#4315](https://github.com/apiome/apiome/issues/4315),
  [#4318](https://github.com/apiome/apiome/issues/4318), [#4319](https://github.com/apiome/apiome/issues/4319), [#4320](https://github.com/apiome/apiome/issues/4320), [#4321](https://github.com/apiome/apiome/issues/4321); epics [#4310](https://github.com/apiome/apiome/issues/4310), [#4316](https://github.com/apiome/apiome/issues/4316).
- Industry formats:
  - FIX Orchestra: [#4323](https://github.com/apiome/apiome/issues/4323)–[#4326](https://github.com/apiome/apiome/issues/4326); epic [#4322](https://github.com/apiome/apiome/issues/4322).
  - X12 implementation guide [#4145](https://github.com/apiome/apiome/issues/4145), HL7 v2 segment definitions [#4159](https://github.com/apiome/apiome/issues/4159), ISO 20022 profile [#4135](https://github.com/apiome/apiome/issues/4135),
    UBL / Peppol [#4346](https://github.com/apiome/apiome/issues/4346).
- Schema formats: RELAX NG and DTD [#4134](https://github.com/apiome/apiome/issues/4134), PL/I [#4141](https://github.com/apiome/apiome/issues/4141).
- REST and RPC: Google Discovery [#4174](https://github.com/apiome/apiome/issues/4174), WSDL 2.0 [#4182](https://github.com/apiome/apiome/issues/4182).
- CloudEvents + xRegistry: [#4306](https://github.com/apiome/apiome/issues/4306)–[#4309](https://github.com/apiome/apiome/issues/4309); epic [#4305](https://github.com/apiome/apiome/issues/4305).

### 3.2 Delivery, presets and schedules

- Push to registry: [#3851](https://github.com/apiome/apiome/issues/3851), and the push part of [#3912](https://github.com/apiome/apiome/issues/3912) (validation is done).
- Delivery channels: [#4328](https://github.com/apiome/apiome/issues/4328) (git), [#4329](https://github.com/apiome/apiome/issues/4329) (webhook), [#4330](https://github.com/apiome/apiome/issues/4330) (S3), [#4331](https://github.com/apiome/apiome/issues/4331) (profiles); epic [#4327](https://github.com/apiome/apiome/issues/4327).
- Presets and auto-export: [#4335](https://github.com/apiome/apiome/issues/4335), [#4336](https://github.com/apiome/apiome/issues/4336), [#4337](https://github.com/apiome/apiome/issues/4337) (multi-target batch is done; presets and
  subscriptions remain); epic [#4332](https://github.com/apiome/apiome/issues/4332).
- UI: [#4381](https://github.com/apiome/apiome/issues/4381) (destination picker), [#4382](https://github.com/apiome/apiome/issues/4382) (preset and schedule integration).
- Epic [#3817](https://github.com/apiome/apiome/issues/3817) (output delivery & packaging).

### 3.3 MCP export surface

[#4339](https://github.com/apiome/apiome/issues/4339) (generic `export.targets` + `version.export` tools), [#4340](https://github.com/apiome/apiome/issues/4340) (fidelity advisory and lossy
confirm over MCP — should carry the RC7 loss report categories), [#4341](https://github.com/apiome/apiome/issues/4341); epic [#4338](https://github.com/apiome/apiome/issues/4338).

### 3.4 Test-drive, visualizations, enterprise operations UX

- Test-drive: [#4367](https://github.com/apiome/apiome/issues/4367) (per-target tooling registry), [#4368](https://github.com/apiome/apiome/issues/4368) (Swagger UI / ReDoc), [#4369](https://github.com/apiome/apiome/issues/4369) (GraphiQL),
  [#4370](https://github.com/apiome/apiome/issues/4370) (AsyncAPI renderer), [#4372](https://github.com/apiome/apiome/issues/4372) (toolchain console); epic [#4366](https://github.com/apiome/apiome/issues/4366).
- Visualizations: [#4375](https://github.com/apiome/apiome/issues/4375) (heatmap overlay; the matrix exists, a loss-kind filter and treemap
  remain), [#4376](https://github.com/apiome/apiome/issues/4376) (ERD for database targets), [#4377](https://github.com/apiome/apiome/issues/4377); epic [#4373](https://github.com/apiome/apiome/issues/4373).
- Enterprise ops UX: [#4379](https://github.com/apiome/apiome/issues/4379) (export history & audit screen; REST exists), [#4383](https://github.com/apiome/apiome/issues/4383) (states, telemetry);
  epic [#4378](https://github.com/apiome/apiome/issues/4378).

### 3.5 Cross-format breaking semantics

[#5745](https://github.com/apiome/apiome/issues/5745) (epic), [#5743](https://github.com/apiome/apiome/issues/5743) (Protovalidate → canonical constraints), [#5746](https://github.com/apiome/apiome/issues/5746) (JSON Schema open/closed),
[#5747](https://github.com/apiome/apiome/issues/5747) (Protobuf reserved numbers and Buf categories; partly built in `proto_breaking.py`), [#5748](https://github.com/apiome/apiome/issues/5748)
(AsyncAPI channel compatibility).

### 3.6 Other export-adjacent

[#1735](https://github.com/apiome/apiome/issues/1735) (score report PDF: the jsPDF helper exists, no UI entry point), [#1747](https://github.com/apiome/apiome/issues/1747) (rule-set export; import
is done), [#3494](https://github.com/apiome/apiome/issues/3494) (legacy export epic, once [#795](https://github.com/apiome/apiome/issues/795) is resolved), [#6163](https://github.com/apiome/apiome/issues/6163) (connector push-back emits
references; gated by `connectors`).

---

## 4. Considered and not planned

These were weighed in the RC7 gap analysis and are not worth building. Unless RC8 decides
otherwise, close their tickets with the reason "not planned: low demand for the effort — see
RC8_PLAN §4".

| Format | Ticket | Why not |
| --- | --- | --- |
| Pydantic output | — | Generated from code, not exchanged as a spec |
| Pact contracts | — | Pacts come from consumer tests; Pactflow already takes OpenAPI |
| JSON:API / HAL output | — | Conventions on top of OpenAPI; belong in lint profiles |
| Postman v2.0 | — | v2.1 is the format every current tool reads |
| Swagger 1.2 | — | Obsolete |
| WSDL 2.0 | [#4182](https://github.com/apiome/apiome/issues/4182) | Little tool support; WSDL 1.1 is what estates run |
| Google API Discovery | [#4174](https://github.com/apiome/apiome/issues/4174) | Google's own format; Google publishes OpenAPI too |
| OData CSDL JSON | [#3897](https://github.com/apiome/apiome/issues/3897) (JSON part) | CSDL XML covers the tools; revisit with OData V2 (§2) |
| RELAX NG / DTD output | [#4134](https://github.com/apiome/apiome/issues/4134) | XSD covers XML schema consumers |
| PL/I include structures | [#4141](https://github.com/apiome/apiome/issues/4141) | Very small audience; copybooks cover mainframe layouts |
| Liquibase / Flyway changelogs | [#4313](https://github.com/apiome/apiome/issues/4313), [#795](https://github.com/apiome/apiome/issues/795) | Changelogs need a diff between database states, not a spec |
| Iceberg | [#4319](https://github.com/apiome/apiome/issues/4319) | Table metadata, not an API contract |
| BigQuery / Spark schemas | [#4318](https://github.com/apiome/apiome/issues/4318) | Revisit after Parquet / Arrow (§2) |
| xRegistry | [#4306](https://github.com/apiome/apiome/issues/4306)–[#4309](https://github.com/apiome/apiome/issues/4309) | Low adoption so far |
| HAR, SoapUI, tRPC output | — | Captures, test suites and code, not specs to exchange |
| nginx / HAProxy / Consul output | — | Imported for discovery; the gateway targets cover config output |
| Industry, mainframe and IoT formats | — | Stay import-only (they still export to any other target through the canonical model) |

---

## 5. Not import or export — moved out of the RC7 milestone

| Issue | Note |
| --- | --- |
| [#5594](https://github.com/apiome/apiome/issues/5594), [#5595](https://github.com/apiome/apiome/issues/5595), [#5596](https://github.com/apiome/apiome/issues/5596) | HIVE epics |
| [#5610](https://github.com/apiome/apiome/issues/5610), [#5611](https://github.com/apiome/apiome/issues/5611), [#5613](https://github.com/apiome/apiome/issues/5613), [#5614](https://github.com/apiome/apiome/issues/5614), [#5617](https://github.com/apiome/apiome/issues/5617) | HIVE-12 / HIVE-13 tickets |
| [#6317](https://github.com/apiome/apiome/issues/6317) | HIVE-14 |
| [#6263](https://github.com/apiome/apiome/issues/6263) | First-row allowances |

[#6274](https://github.com/apiome/apiome/issues/6274) (Monaco theme contrast) stays in RC7 as R7-RG5.

---

## 6. Other open features to plan for RC8

The 2026-10-28 audit found these open and outside RC7's import/export scope. Most are not started.
They are listed so RC8 planning starts from the complete set; each still needs triage into RC8 or
later.

| Area | Issues |
| --- | --- |
| Browse portal and public changelog | [#6287](https://github.com/apiome/apiome/issues/6287), [#6288](https://github.com/apiome/apiome/issues/6288), [#6289](https://github.com/apiome/apiome/issues/6289), [#6294](https://github.com/apiome/apiome/issues/6294), [#6298](https://github.com/apiome/apiome/issues/6298), [#5896](https://github.com/apiome/apiome/issues/5896) |
| SDK generation and delivery | [#4952](https://github.com/apiome/apiome/issues/4952) (umbrella), [#4498](https://github.com/apiome/apiome/issues/4498), [#4499](https://github.com/apiome/apiome/issues/4499), [#5814](https://github.com/apiome/apiome/issues/5814), [#5815](https://github.com/apiome/apiome/issues/5815), [#5816](https://github.com/apiome/apiome/issues/5816), [#5817](https://github.com/apiome/apiome/issues/5817), [#5819](https://github.com/apiome/apiome/issues/5819) |
| Mocks and contract suites | [#5729](https://github.com/apiome/apiome/issues/5729), [#5730](https://github.com/apiome/apiome/issues/5730), [#5736](https://github.com/apiome/apiome/issues/5736), [#5742](https://github.com/apiome/apiome/issues/5742), [#5755](https://github.com/apiome/apiome/issues/5755) |
| Agent runtime and registry | [#5714](https://github.com/apiome/apiome/issues/5714), [#5722](https://github.com/apiome/apiome/issues/5722) |
| Runtime drift and usage | [#5762](https://github.com/apiome/apiome/issues/5762), [#5788](https://github.com/apiome/apiome/issues/5788), [#5789](https://github.com/apiome/apiome/issues/5789) |
| API security posture | [#5931](https://github.com/apiome/apiome/issues/5931), [#5932](https://github.com/apiome/apiome/issues/5932), [#5940](https://github.com/apiome/apiome/issues/5940) |
| Governance and overlays | [#5856](https://github.com/apiome/apiome/issues/5856), [#5878](https://github.com/apiome/apiome/issues/5878) |
| Enterprise identity, audit and SIEM | [#4983](https://github.com/apiome/apiome/issues/4983), [#5029](https://github.com/apiome/apiome/issues/5029), [#5671](https://github.com/apiome/apiome/issues/5671), [#5673](https://github.com/apiome/apiome/issues/5673), [#5674](https://github.com/apiome/apiome/issues/5674), [#5676](https://github.com/apiome/apiome/issues/5676), [#5846](https://github.com/apiome/apiome/issues/5846), [#5847](https://github.com/apiome/apiome/issues/5847) |
| Product catalog | [#6101](https://github.com/apiome/apiome/issues/6101) |
| Collaboration and version control | [#3485](https://github.com/apiome/apiome/issues/3485) (beyond the RC7 merge fix, R7-PC5), [#4512](https://github.com/apiome/apiome/issues/4512), [#4526](https://github.com/apiome/apiome/issues/4526), [#4527](https://github.com/apiome/apiome/issues/4527) |
| Change reports | [#2698](https://github.com/apiome/apiome/issues/2698), [#2705](https://github.com/apiome/apiome/issues/2705) |
| CLI | [#3184](https://github.com/apiome/apiome/issues/3184), [#3222](https://github.com/apiome/apiome/issues/3222), [#3259](https://github.com/apiome/apiome/issues/3259), [#3260](https://github.com/apiome/apiome/issues/3260), [#3261](https://github.com/apiome/apiome/issues/3261), [#3262](https://github.com/apiome/apiome/issues/3262), [#3269](https://github.com/apiome/apiome/issues/3269) |
| Primitives (gated `primitives`) | [#3442](https://github.com/apiome/apiome/issues/3442), [#3482](https://github.com/apiome/apiome/issues/3482) |
| Repository refresh policy | [#3541](https://github.com/apiome/apiome/issues/3541), [#3542](https://github.com/apiome/apiome/issues/3542) |
| Legacy epics | [#1023](https://github.com/apiome/apiome/issues/1023), [#1048](https://github.com/apiome/apiome/issues/1048), [#1066](https://github.com/apiome/apiome/issues/1066) |

---

## 7. The MFI umbrella

[#3715](https://github.com/apiome/apiome/issues/3715) (Multi-Format API Import & Cataloging) stays open as the umbrella for import work after RC7.

---

## 8. Milestone and housekeeping

- **R8-HK1:** create the **RC8** milestone.
- **R8-HK2:** move every issue in §2, §3, §5 and §6 to it.
- **R8-HK3:** move [#4311](https://github.com/apiome/apiome/issues/4311) and [#4312](https://github.com/apiome/apiome/issues/4312) out of RC7.
- **R8-HK4:** close the §4 tickets with their reason, or keep them in RC8 if planning decides
  otherwise.
- **R8-HK5:** file R8-FG1–FG6 when RC8 planning confirms them.
- **R8-HK6:** at RC7 release, record any carried-over V2 tickets in §1.
