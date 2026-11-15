---
"@apiome/cli": minor
---

`apiome sdk compatibility --project <slug|uuid> [--version <label|uuid>] [--fail-on error|warning|info]` prints the generator compatibility manifest (SGD-2.1): findings first, each with the action that fixes it, then each generated artifact's coverage, runtime, unsupported auth and pagination, then semver and the source and options digests. `--fail-on` exits 4 when a finding reaches that severity; `--json` prints the manifest as served.
