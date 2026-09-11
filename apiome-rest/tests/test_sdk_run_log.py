"""The shared SDK run log — SDK-4.1 (#4495) / SDK-4.2 (#4496).

:class:`app.sdk_run_log.RunLog` is the one place both SDK release pipelines redact secrets before a
log line is stored, so these tests pin its promises: redaction on the way in (including a secret
learned part-way through a run), a per-pipeline marker, a bounded length and a closed level set.
"""

from __future__ import annotations

from app.sdk_registry_credentials import REDACTION_MARKER, redact_secrets
from app.sdk_run_log import MAX_LOG_ENTRIES, RunLog

_SECRET = "ghp_aSecretThatMustNeverBeStored"


def test_messages_are_redacted_on_the_way_in():
    log = RunLog(secrets=[_SECRET])
    log.add("push", f"GitHub said: bad token {_SECRET}")
    [entry] = log.entries
    assert _SECRET not in entry["message"]
    assert REDACTION_MARKER in entry["message"]
    assert set(entry) == {"at", "step", "level", "message"}


def test_a_secret_learned_mid_run_redacts_every_later_line():
    log = RunLog(marker="[git-token-redacted]")
    log.add("resolve", "no secret yet")
    log.secrets.append(_SECRET)
    log.add("push", f"echo {_SECRET}")
    assert log.entries[1]["message"] == "echo [git-token-redacted]"
    assert log.redact(f"x {_SECRET} y") == "x [git-token-redacted] y"


def test_the_log_is_bounded():
    log = RunLog()
    for index in range(MAX_LOG_ENTRIES + 25):
        log.add("retry", f"attempt {index}")
    assert len(log.entries) == MAX_LOG_ENTRIES


def test_an_unknown_level_is_stored_as_info():
    log = RunLog()
    log.add("x", "y", level="catastrophic")
    log.add("x", "y", level="warn")
    assert [entry["level"] for entry in log.entries] == ["info", "warn"]


def test_redact_secrets_defaults_to_the_registry_marker_and_accepts_another():
    assert redact_secrets(f"a {_SECRET}", [_SECRET]) == f"a {REDACTION_MARKER}"
    assert redact_secrets(f"a {_SECRET}", [_SECRET], marker="[x]") == "a [x]"
