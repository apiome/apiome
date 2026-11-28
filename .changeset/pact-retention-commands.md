---
"@apiome/cli": minor
---

`apiome pact retention show|set|preview` reads and changes the Contracts clean-up rules: every deployed or released version is always kept; then the latest N versions of each main branch, the latest N of every other branch (optionally for D days) and anything with a listed tag, the nightly switch and the restore window. `set` changes only the flags it is given; `preview` prints what the saved rules — or a draft given as flags — would remove if the clean-up ran now (PFX-8.14).
