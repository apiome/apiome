---
"@apiome/cli": minor
---

`apiome pact migrate --from <Pact Broker or PactFlow URL>` imports a whole workspace — pacticipants and labels, versions with branches and tags, pacts, verification results, environments, current deployments and releases, webhooks — into the Apiome workspace `PACT_BROKER_BASE_URL` names, keeping the source's timestamps. The source token comes from `--token` or `PACT_SOURCE_BROKER_TOKEN` (`--username` / `--password` for basic auth) and is only ever sent to the `--from` host. `--dry-run` checks every record and writes nothing; progress is kept in `--state` (default `apiome-pact-migrate.state.json`), so a second run resumes and skips what was imported. The report lists everything not portable — PactFlow secrets for re-entry, redacted webhook credentials (those webhooks are imported disabled), events Apiome does not fire, display names — and every refused record with its reason; the command exits 1 when any record was refused.
