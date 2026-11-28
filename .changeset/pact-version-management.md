---
"@apiome/cli": minor
---

`apiome pact create-version-tag -a … -e … -t … [--auto-create-version] [-g]` tags a pacticipant version, as `pact-broker create-version-tag` does (one request per tag; a tag the version already has changes nothing). `apiome pact delete-version -a … -e … [--reason …]` deletes a version with its pacts and results — refused while it is deployed or released — and `apiome pact restore-version -a … -e …` brings it back until it is purged (PFX-8.11).
