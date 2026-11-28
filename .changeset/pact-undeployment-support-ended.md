---
"@apiome/cli": minor
---

`apiome pact record-undeployment -a … --environment … [--application-instance|--target …]` records that a pacticipant is no longer deployed to an environment (the deployment in that instance, or the unnamed one), and `apiome pact record-support-ended -a … -e … --environment …` ends support for a released version, as the `pact-broker` commands of the same names do: the same flags and sentences, exit 1 with the reason when nothing matches (PFX-8.13).
