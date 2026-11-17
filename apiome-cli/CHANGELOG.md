# @apiome/cli

## 0.148.0

### Minor Changes

- 1bded9e: `apiome mcp agent-invocations export --day YYYY-MM-DD [--format jsonl|csv] [--out FILE]` writes one finalized UTC day of the agent invocation audit (every stored column, plus `key_name` and a hashed `key_fingerprint`) to stdout or a file, for a SIEM or `jq`. A day that is not final yet, or past the plan's retention, prints the server's reason and exits with the usage code.
- 4ed9afc: Releases are versioned with changesets: each pull request adds a changeset, a `Release: apiome-cli vX.Y.Z` pull request bumps the version and this changelog, and merging it pushes the `cli-vX.Y.Z` tag.
- b2c28f0: `apiome export graphql --federation` writes Apollo Federation v2 subgraph SDL (an `@link` header and an `@key` on every entity) and sends the option to the fidelity preview, so each synthesized key is counted as SYNTH.
- 9c9c68b: `apiome sdk compatibility --project <slug|uuid> [--version <label|uuid>] [--fail-on error|warning|info]` prints the generator compatibility manifest (SGD-2.1): findings first, each with the action that fixes it, then each generated artifact's coverage, runtime, unsupported auth and pagination, then semver and the source and options digests. `--fail-on` exits 4 when a finding reaches that severity; `--json` prints the manifest as served.
