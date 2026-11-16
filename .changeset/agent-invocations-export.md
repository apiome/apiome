---
"@apiome/cli": minor
---

`apiome mcp agent-invocations export --day YYYY-MM-DD [--format jsonl|csv] [--out FILE]` writes one finalized UTC day of the agent invocation audit (every stored column, plus `key_name` and a hashed `key_fingerprint`) to stdout or a file, for a SIEM or `jq`. A day that is not final yet, or past the plan's retention, prints the server's reason and exits with the usage code.
