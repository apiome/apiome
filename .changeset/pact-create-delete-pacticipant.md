---
"@apiome/cli": minor
---

`apiome pact create-or-update-pacticipant --name … [--display-name …] [--main-branch …] [--repository-url …]` registers a pacticipant, or updates the one with that name, as `pact-broker create-or-update-pacticipant` does (it never renames; a name the pacticipant had before a rename finds it). `apiome pact delete-pacticipant --name … [--reason …]` deletes one with its versions, pacts and results; the delete can be undone from the Pacticipants page until it is purged, and is refused while a version is deployed or released (PFX-8.10).
