# Pact specification test-suite vectors (response matching)

The **response** test cases of the Pact specification, vendored unchanged from
[pact-foundation/pact-specification](https://github.com/pact-foundation/pact-specification)
(MIT, see `LICENSE`). `tests/test_pact_spec_vectors.py` runs every file through the PFX-3.1
compiler and the PFX-3.4 matching engine (`app.pact_value_match`) and checks the verdict against
the file's `match`.

| Directory | Branch | Commit |
|-----------|--------|--------|
| `v1/` | `version-1` | `d83700c08b7c7b647b4cfcbeb8421d9c81c79f49` |
| `v1.1/` | `version-1.1` | `64b2a01db4114597a0b3165ce68d2442669ed679` |
| `v2/` | `version-2` | `e96b2acd93fc45738db1b1ebc167c975c218a394` |
| `v3/` | `version-3` | `c1aba5c7a168690e6742eff800e38f9aa1e74c3a` |
| `v4/` | `version-4` | `bdad43b24be1de1da9d2155500fb9ba4b08d44b9` |

Only `testcases/response/**` is vendored: a hosted verifier judges the provider's response, so
the request-matching cases (a mock server's job) do not apply. Files are kept byte-for-byte (some
start with a UTF-8 BOM) so they can be refreshed with:

```bash
git -C pact-specification archive origin/version-4 testcases/response | tar -x -C /tmp/v4
```

**XML.** XML bodies are compared as text and rules on XML elements are reported as not
applicable, so an XML case that expects a match may fail (with a named mismatch) — but the engine
never passes an XML case the suite expects to fail. The test holds both halves.
