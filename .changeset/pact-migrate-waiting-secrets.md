---
"@apiome/cli": minor
---

`apiome pact migrate` no longer drops a webhook credential the source redacted (`**********` header or basic-auth password). It sends it as it is, and Apiome keeps it as a secret with no value yet and imports the webhook turned off, waiting for it. The report says which value to set under **Contracts → Settings → Secrets**; setting it turns the webhook on (PFX-8.15).
