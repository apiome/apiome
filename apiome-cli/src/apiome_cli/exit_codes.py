"""CLI exit codes per clig.dev (success, error, usage) plus the quality-gate codes.

The first three codes are the CLI-wide contract every command honours. The gate codes
(3–5) are used **only** by the pre-flight surface (IXH-2.6): ``import preflight`` /
``export preflight`` and the ``--min-grade`` / ``--fail-on`` flags on the import and
export commands. They exist so a CI job can tell "the spec is not good enough" apart
from "the network was down" (:data:`EXIT_ERROR`) or "the credentials were wrong"
(:data:`EXIT_USAGE`, which every 4xx — including 401/403 — maps to), which is the whole
point of gating in a pipeline.

Failed import/export **jobs** reuse codes 1–3 via :mod:`apiome_cli.taxonomy_exit`
(IXH-6.4): taxonomy ``policy`` → 3, caller-fault categories → 2, transport/internal → 1.
"""

#: The command did what was asked.
EXIT_SUCCESS = 0

#: Transport failure, server error (5xx), or an unexpected client-side failure.
EXIT_ERROR = 1

#: Bad invocation, or a rejected request (any 4xx — including authentication).
EXIT_USAGE = 2

#: The tenant's import/export quality policy (IXH-2.3) **blocks** this payload. The
#: report was produced successfully; the answer is "policy refuses this". A waiver that
#: covers the shortfall downgrades the verdict server-side, so a waived payload does not
#: exit with this code — it is reported as waived and passes.
EXIT_POLICY_BLOCKED = 3

#: A ``--min-grade`` or ``--fail-on`` threshold supplied on the command line was not met.
#: Distinct from :data:`EXIT_POLICY_BLOCKED`: the tenant policy allowed the payload and
#: the caller's own, stricter CI threshold rejected it.
EXIT_QUALITY_GATE = 4

#: The pre-flight completed but its subject is unusable: an import candidate that cannot
#: be parsed at all (``ok: false``), or an export whose every ranked target is blocked or
#: unavailable. Nothing the caller can grade — there is no artifact to gate.
EXIT_PREFLIGHT_UNUSABLE = 5

#: ``apiome schema test`` (IXH-5.5) ran its cases and at least one **failed**: a payload
#: expected to satisfy the schema did not (or vice versa), or a generated mutant did not
#: violate the constraint it was built to violate. Distinct from :data:`EXIT_ERROR`
#: (transport/5xx) and :data:`EXIT_USAGE` (auth or an unresolvable schema reference — any
#: 4xx) so CI can tell "the tests failed" apart from "the tests could not run".
EXIT_SCHEMA_TEST_FAILED = 6

#: ``apiome projects update`` (CLI 3.4): the project **changed since it was read** — the
#: ``updated_at`` in the ``--from-file`` dump (or the one read just before the write) no longer
#: matches the server's, so nothing was written. Re-fetch with ``apiome projects get <id> --json``
#: and apply again. Shares the value 6 with :data:`EXIT_SCHEMA_TEST_FAILED`: codes above 5 are
#: per-command, and the two commands never overlap.
EXIT_UPDATE_CONFLICT = 6

#: ``apiome projects delete`` (CLI 3.5): the project still has **published** versions —
#: specs consumers can fetch — and ``--force`` was not passed, so nothing was deleted or
#: archived. Unpublish them first, or pass ``--force``. Another per-command use of 6.
EXIT_PUBLISHED_VERSIONS = 6

#: ``apiome versions fork`` (CLI 4.4): the target project **already has** the ``--to`` version
#: label, so nothing was forked. Choose another ``--to``. Another per-command use of 6.
EXIT_VERSION_EXISTS = 6

#: ``apiome versions unpublish`` (CLI 4.6): the version is the project's **only** published
#: version, so unpublishing it would leave consumers nothing to fetch; nothing was unpublished.
#: Pass ``--force`` to unpublish it anyway. Another per-command use of 6.
EXIT_LAST_PUBLISHED_VERSION = 6

#: ``apiome versions freeze --unfreeze`` (CLI 4.7): the frozen snapshot has already been
#: **downloaded**, so a consumer may depend on its exact bytes; nothing was unfrozen. A tenant
#: administrator can pass ``--force-unfreeze``. Another per-command use of 6.
EXIT_SNAPSHOT_DOWNLOADED = 6

#: ``apiome versions compatibility`` (CLI 4.8): at least one **unsuppressed breaking change**
#: between ``--base`` and ``--head`` (``--ignore`` / ``--allow-removals`` suppress). The CI gate's
#: failure verdict. Another per-command use of 6.
EXIT_BREAKING_CHANGES = 6

#: ``apiome versions delete`` (CLI 4.9): the version is **published or frozen** and ``--force``
#: was not passed, or version tags still point at it and neither ``--detach-tags`` nor
#: ``--force`` was passed; nothing was changed. Another per-command use of 6.
EXIT_DELETE_REFUSED = 6

#: ``apiome tags create`` (CLI 11.5): the project **already has** a version tag with that name
#: (checked first, and the server's ``409 TAG_NAME_CONFLICT``); nothing was created. Move the
#: existing tag with ``tags update`` instead. Another per-command use of 6.
EXIT_TAG_EXISTS = 6

#: ``apiome tags update`` (CLI 11.6): the tag is **immutable** (checked first, and the server's
#: ``409 TAG_IMMUTABLE``), so it can never be moved; nothing was changed. Another per-command use
#: of 6.
EXIT_TAG_LOCKED = 6

#: ``apiome checks run`` / ``checks show`` (GNC-3.1): the API change check suite **failed** — a
#: required component judged the change unacceptable. Distinct from :data:`EXIT_ERROR` (the suite
#: could not be reached) and :data:`EXIT_USAGE` (a rejected reference or credential) so CI can
#: gate on the verdict itself.
EXIT_CHECK_FAILED = 7

#: ``apiome checks run`` / ``checks show`` (GNC-3.1): the suite has **no verdict yet** — a
#: required component is waiting on evidence (a contract run of this draft), or the commit is ahead
#: of the draft the suite judges. Neither a pass nor a failure, so neither ``0`` nor ``7``: a
#: pipeline decides whether "not yet" blocks it.
EXIT_CHECK_PENDING = 8

#: ``apiome versions compatibility`` (CLI 4.8): the server could not be reached, or failed
#: fetching either side of the comparison — no verdict, so neither ``0`` nor ``6``. Another
#: per-command use of 8.
EXIT_COMPAT_UNAVAILABLE = 8
