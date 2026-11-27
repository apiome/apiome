---
"@apiome/cli": minor
---

`apiome teams assign pacticipant <id> --team <slug>` gives a Pact Broker pacticipant an owner team (PFX-6.4): the team is then told when a verification of one of its pacticipants' pacts fails, and receives the stale-pact re-publish requests and escalations. `apiome graph` still takes only its own entity kinds.
