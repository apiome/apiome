# OpenAPI Initiative test documents (COA-2.1, #7044)

Unmodified copies of the OpenAPI Initiative's published example and test documents, used by
`tests/test_openapi_construct_audit.py` to prove that every OpenAPI construct survives
import → canonical → emit → re-import.

| Files | Source | Commit | Licence |
| --- | --- | --- | --- |
| `v3.1/spec-pass-*.yaml` | [OAI/OpenAPI-Specification](https://github.com/OAI/OpenAPI-Specification) `tests/schema/pass` on `v3.1-dev` | `642ee90575f60233302ad3e82f9de83e02996532` | Apache-2.0 |
| `v3.2/spec-pass-*.yaml` | [OAI/OpenAPI-Specification](https://github.com/OAI/OpenAPI-Specification) `tests/schema/pass` on `v3.2-dev` | `6d86f6560681d0c461cd06b3faa80814aa120fda` | Apache-2.0 |
| `v3.*/learn-*.yaml` | [OAI/learn.openapis.org](https://github.com/OAI/learn.openapis.org) `examples/` | `5f26927b00d5d3d10c1a1a6bbe2d9b41b4a726e7` | CC-BY-4.0 |

Copyright the OpenAPI Initiative contributors. The files are kept byte-for-byte so they can be
refreshed by re-downloading; do not edit them. Apiome's own construct fixtures live one level up.
