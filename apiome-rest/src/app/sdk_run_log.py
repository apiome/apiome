"""A redacting event log for SDK release runs — shared by SDK-4.1 (#4495) and SDK-4.2 (#4496).

Both ways an SDK leaves Apiome — uploading a package to a registry (:mod:`app.sdk_publish_pipeline`)
and opening a pull request against a tenant's repository (:mod:`app.sdk_git_delivery_pipeline`) —
hold a plaintext secret in memory for the length of one run, and both keep a step-by-step log of
that run in a ledger row that is kept forever. This module is the one place the two meet: a log
that **redacts the secrets in play on the way in**, so no caller has to remember to, and that is
**capped**, so a pathological retry loop cannot grow a row without bound.

Extracted from SDK-4.1's pipeline rather than copied into SDK-4.2's: two copies of the redaction
step agree until one of them is changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from .sdk_registry_credentials import REDACTION_MARKER, redact_secrets

__all__ = ["LOG_LEVELS", "MAX_LOG_ENTRIES", "RunLog"]

#: How many events one run's log keeps. A run has a dozen steps; the cap exists so a pathological
#: retry loop cannot grow a row without bound.
MAX_LOG_ENTRIES = 200

#: The levels an entry may carry, mildest first.
LOG_LEVELS = ("info", "warn", "error")


@dataclass
class RunLog:
    """A run's event log, redacted on the way in.

    Attributes:
        secrets: The plaintext secrets in play. Every message is scrubbed of them before it is
            kept. A secret learned part-way through a run (a repository token resolved after the
            run row was written, say) is appended here before anything that could echo it is
            logged.
        marker: What a redacted secret is replaced with, so a reader can tell *which* kind of
            secret a log line once held.
        entries: The events so far, oldest first. Each is ``{at, step, level, message}``.
    """

    secrets: List[str] = field(default_factory=list)
    marker: str = REDACTION_MARKER
    entries: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, step: str, message: str, *, level: str = "info") -> None:
        """Append one event, unless the log is already full.

        Args:
            step: Which stage of the run this belongs to (``resolve``, ``build``, ``push``…).
            message: What happened. Redacted before storage.
            level: One of :data:`LOG_LEVELS`; anything else is stored as ``info``.
        """
        if len(self.entries) >= MAX_LOG_ENTRIES:
            return
        self.entries.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "step": step,
                "level": level if level in LOG_LEVELS else "info",
                "message": self.redact(message),
            }
        )

    def redact(self, message: str) -> str:
        """Scrub a message for use outside the log (an error field, say).

        Args:
            message: Text that may quote a secret.

        Returns:
            The text with every secret in :attr:`secrets` replaced by :attr:`marker`.
        """
        return redact_secrets(message, self.secrets, marker=self.marker)
