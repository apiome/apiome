"""The import poll loop's timeout message names the job and its last reported state.

A CI import that runs out of time used to say only "Import timed out after N seconds.", which cannot
tell a job that was still working from one that never left its first state. The message keeps that
sentence and adds the job id, the last state, the last ``percent`` when the server sent one, and how
many status checks answered.
"""

from __future__ import annotations

from typing import Any

import pytest
import typer

from apiome_cli.import_.jobs import format_import_timeout, wait_for_import_job

_JOB_ID = "11111111-2222-3333-4444-555555555555"


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _Client:
    """Answers every poll with the next payload, repeating the last one."""

    def __init__(self, *payloads: Any) -> None:
        self._payloads = list(payloads)
        self.calls = 0

    def get(self, path: str) -> _Response:
        payload = self._payloads[min(self.calls, len(self._payloads) - 1)]
        self.calls += 1
        return _Response(payload)


class _Clock:
    """A monotonic clock that advances by ``step`` seconds on every read."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def _wait(client: _Client, *, timeout: float = 3.0) -> None:
    wait_for_import_job(
        client,  # type: ignore[arg-type]
        "acme",
        _JOB_ID,
        poll_interval=1.0,
        timeout=timeout,
        no_progress=True,
        sleep=lambda _seconds: None,
        monotonic=_Clock(step=1.0),
    )


def test_timeout_names_the_job_last_state_and_percent(capsys: pytest.CaptureFixture[str]) -> None:
    client = _Client(
        {"state": "queued", "percent": 0},
        {"state": "running", "percent": 42},
    )
    with pytest.raises(typer.Exit) as exc:
        _wait(client, timeout=10.0)
    assert exc.value.exit_code == 1
    assert client.calls >= 2
    err = capsys.readouterr().err
    assert "Import timed out after 10 seconds." in err
    assert f"Job {_JOB_ID} was last reported as running (42%) after {client.calls} status checks." in err


def test_timeout_without_percent_reports_only_the_state(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        _wait(_Client({"state": "running"}))
    assert f"Job {_JOB_ID} was last reported as running after 1 status check." in capsys.readouterr().err


def test_timeout_before_any_poll_says_no_state_was_reported(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        _wait(_Client({"state": "running"}), timeout=0)
    assert f"Job {_JOB_ID} never reported a state." in capsys.readouterr().err


def test_a_completed_job_still_returns_its_payload() -> None:
    payload = {"state": "completed", "percent": 100}
    result = wait_for_import_job(
        _Client(payload),  # type: ignore[arg-type]
        "acme",
        _JOB_ID,
        timeout=3.0,
        no_progress=True,
        sleep=lambda _seconds: None,
        monotonic=_Clock(step=1.0),
    )
    assert result == payload


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (42, "running (42%) after 3 status checks."),
        (12.5, "running (12.5%) after 3 status checks."),
        (None, "running after 3 status checks."),
    ],
)
def test_format_import_timeout(percent: float | None, expected: str) -> None:
    message = format_import_timeout(1, _JOB_ID, last_state="running", last_percent=percent, polls=3)
    assert message.startswith("Import timed out after 1 second. ")
    assert message.endswith(expected)


def test_a_boolean_percent_is_ignored(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        _wait(_Client({"state": "running", "percent": True}))
    assert "was last reported as running after 1 status check." in capsys.readouterr().err
