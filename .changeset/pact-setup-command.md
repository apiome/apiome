---
"@apiome/cli": minor
---

`apiome pact setup` is the Contracts guided set-up for scripted workspaces. With no flag it shows the six sections (Done, Next, To do). `--from-projects` creates a pacticipant for each proposed project and repository that has none, `--environments production,staging` creates the missing environments (`--require-contract` for production), `--ci github` opens pull requests adding can-i-deploy and record-deployment (and prints the workflow where it could not), and `--write-secrets` stores the command's own broker address and key as Actions secrets. What already exists is reported and left alone; `--dry-run` changes nothing (PFX-8.20).
