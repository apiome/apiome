"""Declared test intent on a canonical model — FMT-10.3 (#5477).

Some sources carry tests beside the API they describe: a SoapUI / ReadyAPI project keeps test
suites, cases, steps and assertions next to its interfaces. Those tests are not part of the API's
shape, but they are what the source's owners expect the API to do — the same signal the
contract-testing roadmap (``ROADMAP_CONTRACT_TESTING_GATES.md``) gates on — so an import records
them instead of discarding them.

They are recorded **format-neutrally**, on the model root, under :data:`DECLARED_TESTS_EXTRAS_KEY`:

.. code-block:: json

    {
      "source_format": "soapui",
      "counts": {"suites": 1, "cases": 2, "steps": 7, "assertions": 5},
      "suites": [
        {"name": "Order lifecycle", "run_type": "SEQUENTIAL", "cases": [
          {"name": "Place and cancel", "steps": [
            {"name": "POST orders", "type": "restrequest", "operation": "<operation key>",
             "target": "Orders placeOrder",
             "assertions": [{"type": "Valid HTTP Status Codes", "name": "Created",
                             "expects": {"codes": "201"}}]}
          ]}
        ]}
      ]
    }

A step that calls an operation names it by its canonical operation key (``operation``), so a
consumer can join a test to the operation it exercises; ``null`` when the step's target is not in
the model. Nothing here is executed: the record is *declared* intent. Values in ``expects`` have
passed the secret-scrub gate. :func:`app.catalog_parsed_model.derive_parsed_model` shows the record
on the catalog item as a **Declared tests** group.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["DECLARED_TESTS_EXTRAS_KEY", "build_declared_tests", "declared_tests_of"]

#: The root extras key holding the declared test intent.
DECLARED_TESTS_EXTRAS_KEY = "declared_tests"


def build_declared_tests(source_format: str, suites: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Assemble the declared-test-intent record, with its counts.

    Args:
        source_format: The registry key of the format the tests were read from.
        suites: ``{name, cases: [{name, steps: [{…, assertions: […]}]}]}`` per suite, already
            linked to operation keys and scrubbed.

    Returns:
        The record, or ``None`` when there are no suites (so an import without tests adds no key).
    """
    if not suites:
        return None
    cases = [case for suite in suites for case in suite.get("cases") or []]
    steps = [step for case in cases for step in case.get("steps") or []]
    return {
        "source_format": source_format,
        "counts": {
            "suites": len(suites),
            "cases": len(cases),
            "steps": len(steps),
            "assertions": sum(len(step.get("assertions") or []) for step in steps),
        },
        "suites": [dict(suite) for suite in suites],
    }


def declared_tests_of(extras: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The declared test suites on a model root's ``extras``, or ``[]`` when there are none.

    Args:
        extras: The model root's ``extras``.

    Returns:
        The suites, each ``{name, cases: [...]}``; malformed entries are skipped.
    """
    record = (extras or {}).get(DECLARED_TESTS_EXTRAS_KEY)
    if not isinstance(record, Mapping):
        return []
    return [suite for suite in record.get("suites") or [] if isinstance(suite, dict)]
