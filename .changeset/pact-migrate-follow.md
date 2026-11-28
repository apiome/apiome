---
"@apiome/cli": minor
---

`apiome pact migrate --follow` keeps copying until everyone has moved: after the copy it runs again every `--interval` minutes (15 by default), reading the state file, so only what was published to the old broker since is read and copied. It stops on Ctrl-C, or by itself — saying so, with exit 1 — when the source has been unreachable for 24 hours. A wrong URL or token on the first pass fails at once (PFX-8.17).
