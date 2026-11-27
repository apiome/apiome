---
"@apiome/cli": patch
---

`apiome-cli/pact-commands.json` lists every `apiome pact` command with its arguments and flags, rendered from the CLI's own command tree by `scripts/export_pact_commands.py` (`--check` exits 1 when the committed file is stale; a test does the same). The Contracts CLI ↔ UI parity check reads it, so a new `apiome pact` command needs its row in `docs/pact-parity-ledger.json`. No command changes.
