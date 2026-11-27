---
"@apiome/cli": minor
---

`apiome pact check <files> --against main --against deployed:production` compares pacts with several provider versions before publishing (`POST …/pact-broker/pacts/check`, PFX-8.4) and publishes nothing. `--against` takes `main`, `deployed:<environment>`, `version:<number>` or `draft:<revision>` (repeatable, at most 10; a bad one is refused before anything is sent). Prints one row per provider version with the verdict a publish would record, every interaction that differs or is not in the spec, and every selector that named nothing. Exits `0` only when every pact passes against every version and every selector named one, `1` otherwise, as `pact-broker` does.
