# Export ticket triage — RC7 appendices and RC8 plan (COA-3.6)

_Checked 2026-11-20 against GitHub and `main` @ `e9629a7d4` for COA-3.6 ([#7057](https://github.com/apiome/apiome/issues/7057))._

This is the one table for every export ticket named in
[`RC7_CATALOG_IMPORT_EXPORT.md`](RC7_CATALOG_IMPORT_EXPORT.md) Appendix A and B and in
[`RC8_PLAN.md`](RC8_PLAN.md) §2, §3 and §4. Each ticket has its GitHub state and one decision:

- **Do** — wanted and not built; a ticket is open for it.
- **Close** — nothing left to do; the ticket is closed (or the format has no ticket and gets none).
- **Later** — still wanted, not scheduled.

## 1. Result

| | Count |
| --- | --- |
| Existing tickets checked | 109 |
| Closed — shipped | 106 |
| Closed — absorbed by another ticket ([#4374](https://github.com/apiome/apiome/issues/4374)) | 1 |
| Closed, work not finished — **Later** ([#1735](https://github.com/apiome/apiome/issues/1735)) | 1 |
| Open — **Later** ([#6163](https://github.com/apiome/apiome/issues/6163)) | 1 |
| New tickets opened — **Do** | 7 |
| Formats with no ticket, not planned — **Close** | 9 |

What the plans had wrong:

- **Nothing in the two RC7 appendices is still deferred.** Every target and every piece of "other export
  work" listed there shipped between 2026-10-29 and 2026-11-14.
- **RC8_PLAN §4 proposed closing ten tickets unbuilt; all ten were built.** WSDL 2.0, Google API Discovery,
  RELAX NG / DTD, PL/I, Iceberg, BigQuery / Spark and xRegistry are export targets or output modes today. No
  ticket was closed as "not planned", so there was none left to close; each carries a comment recording this.
- **Seven ranked targets were never ticketed** (RC8_PLAN §2 "new", R8-HK5). They are open now — §2 below.

## 2. New tickets — Do

None of these exists in `apiome-rest/src/app` today. They are on the *Apiome: Import and Export* project,
in no release yet.

| Ticket | Target or mode | RC8 §2 rank | Effort | What exists today |
| --- | --- | --- | --- | --- |
| [#7118](https://github.com/apiome/apiome/issues/7118) (R8-FG7) | Insomnia v5 and Bruno OpenCollection output modes | 2 | M | [#4291](https://github.com/apiome/apiome/issues/4291) shipped Insomnia v4 JSON and Bruno `.bru`; Insomnia v5 is imported |
| [#7116](https://github.com/apiome/apiome/issues/7116) (R8-FG1) | TypeScript types-only export target | 3 | M | Import only |
| [#7119](https://github.com/apiome/apiome/issues/7119) (R8-FG2) | Google Cloud API Gateway export target | 6 | S–M | AWS and Azure targets exist |
| [#7122](https://github.com/apiome/apiome/issues/7122) (R8-FG3) | OData V2 output option | 8 | M | CSDL JSON 4.01 and CSDL XML 4.x |
| [#7117](https://github.com/apiome/apiome/issues/7117) (R8-FG4) | Zod export target | 9 | M | Import only |
| [#7120](https://github.com/apiome/apiome/issues/7120) (R8-FG5) | Protobuf Editions output option | 12 | S | Editions are imported and written as proto3, with the losses reported |
| [#7121](https://github.com/apiome/apiome/issues/7121) (R8-FG6) | Tyk OAS export target | 13 | S | Import only |

## 3. Formats with no ticket — Close (not planned)

From RC8_PLAN §4. No ticket exists and none is opened. The reasons stand.

| Format | Why not |
| --- | --- |
| Pydantic output | Generated from code, not exchanged as a spec |
| Pact contracts | Pacts come from consumer tests; Pactflow already takes OpenAPI |
| JSON:API / HAL output | Conventions on top of OpenAPI; belong in lint profiles |
| Postman v2.0 | v2.1 is the format every current tool reads |
| Swagger 1.2 | Obsolete |
| HAR, SoapUI, tRPC output | Captures, test suites and code, not specs to exchange |
| nginx / HAProxy / Consul output | Imported for discovery; the gateway targets cover config output |
| Industry, mainframe and IoT formats without an export target | Stay import-only (they still export to any other target through the canonical model) |
| Emitted-schema graph view as its own screen | Absorbed by the Export studio mapping graph ([#4374](https://github.com/apiome/apiome/issues/4374) → [#5110](https://github.com/apiome/apiome/issues/5110)) |

## 4. Existing tickets

"Listed in" names the plan sections that mention the ticket. A ticket closed by more than one pull request
lists each.

| Ticket | Title | Listed in | State | Decision |
| --- | --- | --- | --- | --- |
| [#795](https://github.com/apiome/apiome/issues/795) | Export Liquibase statements | RC7 App. A, RC8 §3.1, RC8 §3.6, RC8 §4 | Closed, completed (2026-11-09) | **Close** — shipped in [#6746](https://github.com/apiome/apiome/pull/6746); RC8 §4 "not planned" entry withdrawn |
| [#1735](https://github.com/apiome/apiome/issues/1735) | Score Report Export as PDF | RC8 §3.6 | Closed, completed (2026-11-10), no linked pull request | **Later** — the PDF helper (`downloadSchemaScoreReportPdf`) still has no screen that calls it; reopen or re-ticket with the Quality score work, not with exports |
| [#1747](https://github.com/apiome/apiome/issues/1747) | Rule Set Import/Export | RC8 §3.6 | Closed, completed (2026-11-13) | **Close** — shipped in [#6786](https://github.com/apiome/apiome/pull/6786) |
| [#3494](https://github.com/apiome/apiome/issues/3494) | [Epic] Export & Interoperability | RC8 §3.6 | Closed, completed (2026-11-19) | **Close** — shipped in [#7066](https://github.com/apiome/apiome/pull/7066) |
| [#3813](https://github.com/apiome/apiome/issues/3813) | MFX: Multi-Format API Export & Cross-Protocol Transcoding | RC8 §3.6 | Closed, completed (2026-11-05) | **Close** — shipped in [#6685](https://github.com/apiome/apiome/pull/6685) |
| [#3817](https://github.com/apiome/apiome/issues/3817) | MFX-EPIC-4: Output Delivery & Packaging | RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6684](https://github.com/apiome/apiome/pull/6684) |
| [#3851](https://github.com/apiome/apiome/issues/3851) | MFX-4.4: Push-to-registry delivery | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6683](https://github.com/apiome/apiome/pull/6683) |
| [#3858](https://github.com/apiome/apiome/issues/3858) | MFX-6.4: Round-trip diff view | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6472](https://github.com/apiome/apiome/pull/6472) |
| [#3865](https://github.com/apiome/apiome/issues/3865) | MFX-8.3: Toolchain runner reuse | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6449](https://github.com/apiome/apiome/pull/6449) |
| [#3876](https://github.com/apiome/apiome/issues/3876) | MFX-11.3: Multi-version (2.6/3.0/3.1) | RC7 App. A | Closed, completed (2026-10-31) | **Close** — shipped in [#6485](https://github.com/apiome/apiome/pull/6485) |
| [#3891](https://github.com/apiome/apiome/issues/3891) | MFX-14.3: Multi-file packaging + validate | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6439](https://github.com/apiome/apiome/pull/6439) |
| [#3895](https://github.com/apiome/apiome/issues/3895) | MFX-15.3: Validate (tsp compile) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6440](https://github.com/apiome/apiome/pull/6440) |
| [#3897](https://github.com/apiome/apiome/issues/3897) | MFX-16.1: CSDL emitter | RC7 App. A, RC8 §4 | Closed, completed (2026-10-29) | **Close** — shipped in [#6422](https://github.com/apiome/apiome/pull/6422); RC8 §4 "not planned" entry withdrawn |
| [#3899](https://github.com/apiome/apiome/issues/3899) | MFX-16.3: Validate (OASIS schema) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6450](https://github.com/apiome/apiome/pull/6450) |
| [#3903](https://github.com/apiome/apiome/issues/3903) | MFX-17.3: Validate (AMF) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6441](https://github.com/apiome/apiome/pull/6441) |
| [#3907](https://github.com/apiome/apiome/issues/3907) | MFX-18.3: Validate (drafter) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6442](https://github.com/apiome/apiome/pull/6442) |
| [#3912](https://github.com/apiome/apiome/issues/3912) | MFX-19.4: Validate + (push) | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-02) | **Close** — shipped in [#6527](https://github.com/apiome/apiome/pull/6527) |
| [#3914](https://github.com/apiome/apiome/issues/3914) | MFX-20.1: Smithy emitter | RC7 App. A | Closed, completed (2026-10-29) | **Close** — shipped in [#6416](https://github.com/apiome/apiome/pull/6416) |
| [#3916](https://github.com/apiome/apiome/issues/3916) | MFX-20.3: Validate (smithy build) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6443](https://github.com/apiome/apiome/pull/6443) |
| [#4129](https://github.com/apiome/apiome/issues/4129) | MFX-21.4: Validate + round-trip (JSON Schema) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6444](https://github.com/apiome/apiome/pull/6444) |
| [#4134](https://github.com/apiome/apiome/issues/4134) | MFX-22.3: RELAX NG + DTD output modes | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-03) | **Close** — shipped in [#6611](https://github.com/apiome/apiome/pull/6611); RC8 §4 "not planned" entry withdrawn |
| [#4135](https://github.com/apiome/apiome/issues/4135) | MFX-22.4: ISO 20022 message profile | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6612](https://github.com/apiome/apiome/pull/6612) |
| [#4136](https://github.com/apiome/apiome/issues/4136) | MFX-22.5: Validate + round-trip (XSD) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6445](https://github.com/apiome/apiome/pull/6445) |
| [#4139](https://github.com/apiome/apiome/issues/4139) | MFX-23.1: COBOL copybook emitter | RC7 App. A | Closed, completed (2026-10-30) | **Close** — shipped in [#6435](https://github.com/apiome/apiome/pull/6435) |
| [#4141](https://github.com/apiome/apiome/issues/4141) | MFX-23.3: PL/I include structure output mode | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6614](https://github.com/apiome/apiome/pull/6614); RC8 §4 "not planned" entry withdrawn |
| [#4142](https://github.com/apiome/apiome/issues/4142) | MFX-23.4: Validate emitted copybooks (cb2xml) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6453](https://github.com/apiome/apiome/pull/6453) |
| [#4145](https://github.com/apiome/apiome/issues/4145) | MFX-24.1: X12 implementation-guide emitter | RC7 App. A, RC8 §3.1 | Closed, completed (2026-10-30) | **Close** — shipped in [#6437](https://github.com/apiome/apiome/pull/6437) |
| [#4146](https://github.com/apiome/apiome/issues/4146) | MFX-24.2: UN/EDIFACT message-guide emitter | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6616](https://github.com/apiome/apiome/pull/6616) |
| [#4148](https://github.com/apiome/apiome/issues/4148) | MFX-24.4: Validate emitted EDI guides | RC7 App. B | Closed, completed (2026-10-31) | **Close** — shipped in [#6482](https://github.com/apiome/apiome/pull/6482) |
| [#4154](https://github.com/apiome/apiome/issues/4154) | MFX-25.4: Validate + round-trip (Thrift) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6446](https://github.com/apiome/apiome/pull/6446) |
| [#4157](https://github.com/apiome/apiome/issues/4157) | MFX-26.1: FHIR StructureDefinition emitter (R4/R5) | RC7 App. A, RC8 §2 | Closed, completed (2026-10-29) | **Close** — shipped in [#6424](https://github.com/apiome/apiome/pull/6424) |
| [#4159](https://github.com/apiome/apiome/issues/4159) | MFX-26.3: HL7 v2 segment-definition emitter | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6619](https://github.com/apiome/apiome/pull/6619) |
| [#4160](https://github.com/apiome/apiome/issues/4160) | MFX-26.4: Validate emitted FHIR artifacts | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6451](https://github.com/apiome/apiome/pull/6451) |
| [#4161](https://github.com/apiome/apiome/issues/4161) | MFX-26.5: Healthcare target cards + CLI + fixtures | RC7 App. A | Closed, completed (2026-10-29) | **Close** — shipped in [#6426](https://github.com/apiome/apiome/pull/6426) |
| [#4170](https://github.com/apiome/apiome/issues/4170) | MFX-28.3: Validate emitted IDL | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6452](https://github.com/apiome/apiome/pull/6452) |
| [#4174](https://github.com/apiome/apiome/issues/4174) | MFX-29.2: Google API Discovery document emitter | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6621](https://github.com/apiome/apiome/pull/6621); RC8 §4 "not planned" entry withdrawn |
| [#4180](https://github.com/apiome/apiome/issues/4180) | MFX-30.3: Fidelity packs + compile validation (FlatBuffers/Cap'n Proto) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6454](https://github.com/apiome/apiome/pull/6454) |
| [#4182](https://github.com/apiome/apiome/issues/4182) | MFX-14.5: WSDL 2.0 output option | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6626](https://github.com/apiome/apiome/pull/6626); RC8 §4 "not planned" entry withdrawn |
| [#4183](https://github.com/apiome/apiome/issues/4183) | MFX-19.6: Multi-format Schema Registry subjects (JSON Schema + Protobuf) | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6625](https://github.com/apiome/apiome/pull/6625) |
| [#4291](https://github.com/apiome/apiome/issues/4291) | MFX-31.3: Insomnia / Bruno output modes | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-10-31) | **Close** — shipped in [#6476](https://github.com/apiome/apiome/pull/6476) |
| [#4294](https://github.com/apiome/apiome/issues/4294) | MFX-EPIC-32: Agent-interface emitters (MCP server descriptor, A2A Agent Card, agentic-web manifests) | RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6631](https://github.com/apiome/apiome/pull/6631) |
| [#4295](https://github.com/apiome/apiome/issues/4295) | MFX-32.1: MCP tool-definition emitter | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-10-31) | **Close** — shipped in [#6487](https://github.com/apiome/apiome/pull/6487), [#6631](https://github.com/apiome/apiome/pull/6631) |
| [#4296](https://github.com/apiome/apiome/issues/4296) | MFX-32.2: A2A Agent Card emitter | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6627](https://github.com/apiome/apiome/pull/6627) |
| [#4297](https://github.com/apiome/apiome/issues/4297) | MFX-32.3: Agentic-web site manifests (agents.json / llms.txt) | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6628](https://github.com/apiome/apiome/pull/6628) |
| [#4298](https://github.com/apiome/apiome/issues/4298) | MFX-32.4: Agent-interface fidelity packs | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6629](https://github.com/apiome/apiome/pull/6629) |
| [#4299](https://github.com/apiome/apiome/issues/4299) | MFX-32.5: Target cards + CLI + fixtures | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6630](https://github.com/apiome/apiome/pull/6630) |
| [#4305](https://github.com/apiome/apiome/issues/4305) | MFX-EPIC-34: CloudEvents + xRegistry export (emit & expose-as-registry) | RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6636](https://github.com/apiome/apiome/pull/6636) |
| [#4306](https://github.com/apiome/apiome/issues/4306) | MFX-34.1: xRegistry document emitter (schemas + message definitions) | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6632](https://github.com/apiome/apiome/pull/6632), [#6636](https://github.com/apiome/apiome/pull/6636); RC8 §4 "not planned" entry withdrawn |
| [#4307](https://github.com/apiome/apiome/issues/4307) | MFX-34.2: Expose-as-xRegistry read-only API façade | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6633](https://github.com/apiome/apiome/pull/6633); RC8 §4 "not planned" entry withdrawn |
| [#4308](https://github.com/apiome/apiome/issues/4308) | MFX-34.3: Fidelity pack + validation | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6634](https://github.com/apiome/apiome/pull/6634); RC8 §4 "not planned" entry withdrawn |
| [#4309](https://github.com/apiome/apiome/issues/4309) | MFX-34.4: Target card + CLI + fixtures | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6635](https://github.com/apiome/apiome/pull/6635); RC8 §4 "not planned" entry withdrawn |
| [#4310](https://github.com/apiome/apiome/issues/4310) | MFX-EPIC-35: SQL DDL & database-schema emitters (DDL, DBML/Prisma, Liquibase/Flyway) | RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6641](https://github.com/apiome/apiome/pull/6641) |
| [#4311](https://github.com/apiome/apiome/issues/4311) | MFX-35.1: SQL DDL emitter (ANSI + PostgreSQL/MySQL dialects) | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-10-31) | **Close** — shipped in [#6488](https://github.com/apiome/apiome/pull/6488) |
| [#4312](https://github.com/apiome/apiome/issues/4312) | MFX-35.2: DBML + Prisma output modes | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-10-31) | **Close** — shipped in [#6489](https://github.com/apiome/apiome/pull/6489) |
| [#4313](https://github.com/apiome/apiome/issues/4313) | MFX-35.3: Liquibase / Flyway changelog mode | RC7 App. A, RC8 §3.1, RC8 §3.6, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6637](https://github.com/apiome/apiome/pull/6637); RC8 §4 "not planned" entry withdrawn |
| [#4314](https://github.com/apiome/apiome/issues/4314) | MFX-35.4: SQL fidelity pack | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6639](https://github.com/apiome/apiome/pull/6639) |
| [#4315](https://github.com/apiome/apiome/issues/4315) | MFX-35.5: Validate + target card + CLI + fixtures | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6640](https://github.com/apiome/apiome/pull/6640) |
| [#4316](https://github.com/apiome/apiome/issues/4316) | MFX-EPIC-36: Data-lake / analytics schema emitters (Parquet/Arrow, BigQuery, Spark, Iceberg) | RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6647](https://github.com/apiome/apiome/pull/6647) |
| [#4317](https://github.com/apiome/apiome/issues/4317) | MFX-36.1: Parquet / Arrow schema emitter | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6642](https://github.com/apiome/apiome/pull/6642) |
| [#4318](https://github.com/apiome/apiome/issues/4318) | MFX-36.2: BigQuery + Spark schema modes | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6643](https://github.com/apiome/apiome/pull/6643); RC8 §4 "not planned" entry withdrawn |
| [#4319](https://github.com/apiome/apiome/issues/4319) | MFX-36.3: Iceberg schema emitter | RC7 App. A, RC8 §3.1, RC8 §4 | Closed, completed (2026-11-04) | **Close** — shipped in [#6644](https://github.com/apiome/apiome/pull/6644); RC8 §4 "not planned" entry withdrawn |
| [#4320](https://github.com/apiome/apiome/issues/4320) | MFX-36.4: Fidelity packs + validation | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6645](https://github.com/apiome/apiome/pull/6645) |
| [#4321](https://github.com/apiome/apiome/issues/4321) | MFX-36.5: Target cards + CLI + fixtures | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6646](https://github.com/apiome/apiome/pull/6646) |
| [#4322](https://github.com/apiome/apiome/issues/4322) | MFX-EPIC-37: FIX Orchestra emitter (capital markets) | RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6653](https://github.com/apiome/apiome/pull/6653) |
| [#4323](https://github.com/apiome/apiome/issues/4323) | MFX-37.1: FIX Orchestra emitter | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6648](https://github.com/apiome/apiome/pull/6648) |
| [#4324](https://github.com/apiome/apiome/issues/4324) | MFX-37.2: Orchestra fidelity pack | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6649](https://github.com/apiome/apiome/pull/6649) |
| [#4325](https://github.com/apiome/apiome/issues/4325) | MFX-37.3: Validate (Orchestra XSD) | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6650](https://github.com/apiome/apiome/pull/6650) |
| [#4326](https://github.com/apiome/apiome/issues/4326) | MFX-37.4: Target card + CLI + fixtures | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6652](https://github.com/apiome/apiome/pull/6652) |
| [#4327](https://github.com/apiome/apiome/issues/4327) | MFX-EPIC-38: Export delivery channels (git, webhook, object storage) | RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6659](https://github.com/apiome/apiome/pull/6659) |
| [#4328](https://github.com/apiome/apiome/issues/4328) | MFX-38.1: Git repository delivery (branch, commit, PR) | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-04) | **Close** — shipped in [#6655](https://github.com/apiome/apiome/pull/6655) |
| [#4329](https://github.com/apiome/apiome/issues/4329) | MFX-38.2: Webhook delivery | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6656](https://github.com/apiome/apiome/pull/6656) |
| [#4330](https://github.com/apiome/apiome/issues/4330) | MFX-38.3: Object-storage delivery (S3-compatible) | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6657](https://github.com/apiome/apiome/pull/6657) |
| [#4331](https://github.com/apiome/apiome/issues/4331) | MFX-38.4: Delivery profiles + audit | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6658](https://github.com/apiome/apiome/pull/6658) |
| [#4332](https://github.com/apiome/apiome/issues/4332) | MFX-EPIC-39: Batch, multi-target, presets & scheduled export | RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6663](https://github.com/apiome/apiome/pull/6663) |
| [#4335](https://github.com/apiome/apiome/issues/4335) | MFX-39.3: Export presets | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6660](https://github.com/apiome/apiome/pull/6660) |
| [#4336](https://github.com/apiome/apiome/issues/4336) | MFX-39.4: Auto-export on version publish | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6661](https://github.com/apiome/apiome/pull/6661) |
| [#4337](https://github.com/apiome/apiome/issues/4337) | MFX-39.5: Batch / preset / schedule UI | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6662](https://github.com/apiome/apiome/pull/6662) |
| [#4338](https://github.com/apiome/apiome/issues/4338) | MFX-EPIC-40: MCP export surface (generic version.export tools) | RC8 §3.3 | Closed, completed (2026-11-05) | **Close** — shipped in [#6667](https://github.com/apiome/apiome/pull/6667) |
| [#4339](https://github.com/apiome/apiome/issues/4339) | MFX-40.1: Generic export MCP tools (export.targets + version.export) | RC7 App. B, RC8 §3.3 | Closed, completed (2026-11-05) | **Close** — shipped in [#6664](https://github.com/apiome/apiome/pull/6664) |
| [#4340](https://github.com/apiome/apiome/issues/4340) | MFX-40.2: Fidelity advisory + lossy confirm over MCP | RC7 App. B, RC8 §3.3 | Closed, completed (2026-11-05) | **Close** — shipped in [#6665](https://github.com/apiome/apiome/pull/6665) |
| [#4341](https://github.com/apiome/apiome/issues/4341) | MFX-40.3: Surface-parity tests + fixtures + docs | RC7 App. B, RC8 §3.3 | Closed, completed (2026-11-05) | **Close** — shipped in [#6666](https://github.com/apiome/apiome/pull/6666) |
| [#4342](https://github.com/apiome/apiome/issues/4342) | MFX-9.5: OpenAPI 3.2 output option | RC7 App. A | Closed, completed (2026-10-31) | **Close** — shipped in [#6484](https://github.com/apiome/apiome/pull/6484) |
| [#4343](https://github.com/apiome/apiome/issues/4343) | MFX-12.6: Connect-RPC / gRPC-Gateway flavor options | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-11-14) | **Close** — shipped in [#6799](https://github.com/apiome/apiome/pull/6799) |
| [#4344](https://github.com/apiome/apiome/issues/4344) | MFX-13.6: Federation subgraph output mode | RC7 App. A, RC8 §2, RC8 §3.1 | Closed, completed (2026-11-14) | **Close** — shipped in [#6800](https://github.com/apiome/apiome/pull/6800) |
| [#4346](https://github.com/apiome/apiome/issues/4346) | MFX-24.6: UBL / Peppol BIS guide mode | RC7 App. A, RC8 §3.1 | Closed, completed (2026-11-04) | **Close** — shipped in [#6617](https://github.com/apiome/apiome/pull/6617) |
| [#4364](https://github.com/apiome/apiome/issues/4364) | [MFX-43.4] Round-trip Monaco diff (implements MFX-6.4) | RC7 App. B | Closed, completed (2026-10-30) | **Close** — shipped in [#6472](https://github.com/apiome/apiome/pull/6472) |
| [#4366](https://github.com/apiome/apiome/issues/4366) | [MFX-EPIC-44] Format test-drive tooling | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6673](https://github.com/apiome/apiome/pull/6673) |
| [#4367](https://github.com/apiome/apiome/issues/4367) | [MFX-44.1] (rest+ui) Per-target tooling registry | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6668](https://github.com/apiome/apiome/pull/6668) |
| [#4368](https://github.com/apiome/apiome/issues/4368) | [MFX-44.2] OpenAPI test-drive (Swagger UI / ReDoc) | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6669](https://github.com/apiome/apiome/pull/6669) |
| [#4369](https://github.com/apiome/apiome/issues/4369) | [MFX-44.3] GraphQL test-drive (GraphiQL) | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6670](https://github.com/apiome/apiome/pull/6670) |
| [#4370](https://github.com/apiome/apiome/issues/4370) | [MFX-44.4] AsyncAPI test-drive (renderer) | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6671](https://github.com/apiome/apiome/pull/6671) |
| [#4371](https://github.com/apiome/apiome/issues/4371) | [MFX-44.5] Mock-server try-out | RC7 App. B | Closed, completed (2026-08-26) | **Close** — shipped in [#5538](https://github.com/apiome/apiome/pull/5538) |
| [#4372](https://github.com/apiome/apiome/issues/4372) | [MFX-44.6] Toolchain check console | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6672](https://github.com/apiome/apiome/pull/6672) |
| [#4373](https://github.com/apiome/apiome/issues/4373) | [MFX-EPIC-45] Export visualizations | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6677](https://github.com/apiome/apiome/pull/6677) |
| [#4374](https://github.com/apiome/apiome/issues/4374) | [MFX-45.1] Emitted-schema graph view | RC7 App. B | Closed, not planned (2026-07-25) | **Close** — absorbed by [#5110](https://github.com/apiome/apiome/issues/5110) (the Export studio mapping graph, [#5154](https://github.com/apiome/apiome/pull/5154)) |
| [#4375](https://github.com/apiome/apiome/issues/4375) | [MFX-45.2] Fidelity heatmap overlay | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6674](https://github.com/apiome/apiome/pull/6674) |
| [#4376](https://github.com/apiome/apiome/issues/4376) | [MFX-45.3] ERD mode for database targets | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6675](https://github.com/apiome/apiome/pull/6675) |
| [#4377](https://github.com/apiome/apiome/issues/4377) | [MFX-45.4] Paradigm-specific viz modes | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6676](https://github.com/apiome/apiome/pull/6676) |
| [#4378](https://github.com/apiome/apiome/issues/4378) | [MFX-EPIC-46] Enterprise operations UX | RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6682](https://github.com/apiome/apiome/pull/6682) |
| [#4379](https://github.com/apiome/apiome/issues/4379) | [MFX-46.1] Export history & audit screen | RC7 App. B, RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6678](https://github.com/apiome/apiome/pull/6678) |
| [#4381](https://github.com/apiome/apiome/issues/4381) | [MFX-46.3] Delivery destination picker | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6679](https://github.com/apiome/apiome/pull/6679) |
| [#4382](https://github.com/apiome/apiome/issues/4382) | [MFX-46.4] Preset & schedule integration | RC7 App. B, RC8 §3.2 | Closed, completed (2026-11-05) | **Close** — shipped in [#6680](https://github.com/apiome/apiome/pull/6680) |
| [#4383](https://github.com/apiome/apiome/issues/4383) | [MFX-46.5] States, empty/error patterns, telemetry & docs | RC8 §3.4 | Closed, completed (2026-11-05) | **Close** — shipped in [#6681](https://github.com/apiome/apiome/pull/6681) |
| [#5743](https://github.com/apiome/apiome/issues/5743) | [XPC-3.3] Protovalidate mapping into canonical constraints | RC8 §3.5 | Closed, completed (2026-11-15) | **Close** — shipped in [#6829](https://github.com/apiome/apiome/pull/6829) |
| [#5745](https://github.com/apiome/apiome/issues/5745) | [XPC-EPIC-4] Cross-format breaking semantics | RC8 §3.5 | Closed, completed (2026-11-16) | **Close** — shipped in [#6835](https://github.com/apiome/apiome/pull/6835) |
| [#5746](https://github.com/apiome/apiome/issues/5746) | [XPC-4.2] JSON Schema open/closed compatibility classifier | RC8 §3.5 | Closed, completed (2026-11-15) | **Close** — shipped in [#6830](https://github.com/apiome/apiome/pull/6830) |
| [#5747](https://github.com/apiome/apiome/issues/5747) | [XPC-4.3] Protobuf reserved numbers and Buf categories | RC8 §3.5 | Closed, completed (2026-11-16) | **Close** — shipped in [#6831](https://github.com/apiome/apiome/pull/6831) |
| [#5748](https://github.com/apiome/apiome/issues/5748) | [XPC-4.4] AsyncAPI channel and operation compatibility (W12) | RC8 §3.5 | Closed, completed (2026-11-16) | **Close** — shipped in [#6832](https://github.com/apiome/apiome/pull/6832) |
| [#6163](https://github.com/apiome/apiome/issues/6163) | [CVT-5.5] Push-back emits references, not literals | RC8 §3.6 | Open | **Later** — Connectors are held back ([#6894](https://github.com/apiome/apiome/issues/6894)); tracked on the *Enable: Connectors* project |
