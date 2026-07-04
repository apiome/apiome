"""Arazzo → canonical model normalizer — MFI-30.2 (#4395).

Maps a parsed **Arazzo** workflow document into a :class:`~app.canonical_model.CanonicalApi`:

* ``info`` → :class:`~app.canonical_model.ApiIdentity` + title/version/description;
* each ``workflow`` → a :class:`~app.canonical_model.Service` (``workflowId`` as key);
* each workflow ``step`` → an :class:`~app.canonical_model.Operation` keyed by
  ``{workflowId}#{stepId}`` with the referenced ``operationId`` / ``operationRef`` preserved
  in ``extras``;
* ``sourceDescriptions`` → the artifact root ``extras`` bag for fidelity and lint.

Workflow step order is captured on each service's ``extras.stepOrder`` so reordering diffs
at the workflow level even though operations are sorted by stable key.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["ArazzoNormalizer", "ARAZZO_FORMAT"]

ARAZZO_FORMAT = "arazzo"


class ArazzoNormalizer(Normalizer, register=True):
    """Normalize a parsed Arazzo workflow document into a :class:`CanonicalApi`."""

    format = ARAZZO_FORMAT
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, dict):
            raise ValueError("Arazzo source must be a parsed mapping (dict)")
        self._validate_version(source)

        info = source.get("info") or {}
        source_descriptions = source.get("sourceDescriptions") or []

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="http",
            identity=ApiIdentity(name=info.get("title") or "Untitled Workflow"),
            version=info.get("version"),
            title=info.get("title"),
            description=info.get("description"),
            services=self._services(source),
            raw=source if include_raw else None,
            extras={
                "arazzo": source.get("arazzo"),
                "sourceDescriptions": source_descriptions,
            },
        )
        return normalize_ordering(api)

    @staticmethod
    def _validate_version(source: Dict[str, Any]) -> None:
        version = source.get("arazzo")
        if isinstance(version, str) and version.strip():
            return
        raise ValueError(
            "not an Arazzo document (missing or unsupported `arazzo` version marker)"
        )

    def _services(self, source: Dict[str, Any]) -> List[Service]:
        workflows = source.get("workflows") or []
        services: List[Service] = []
        for workflow in workflows:
            if not isinstance(workflow, dict):
                continue
            workflow_id = workflow.get("workflowId")
            if not isinstance(workflow_id, str) or not workflow_id.strip():
                continue
            steps = workflow.get("steps") or []
            step_order = [
                step["stepId"]
                for step in steps
                if isinstance(step, dict)
                and isinstance(step.get("stepId"), str)
                and step["stepId"].strip()
            ]
            operations = [
                op
                for index, step in enumerate(steps)
                if isinstance(step, dict)
                for op in [self._step_operation(workflow_id, step, index)]
            ]
            service_extras: Dict[str, Any] = {
                "workflowId": workflow_id,
                "stepOrder": step_order,
            }
            if isinstance(workflow.get("inputs"), dict):
                service_extras["inputs"] = workflow["inputs"]
            services.append(
                Service(
                    key=workflow_id,
                    name=workflow_id,
                    description=workflow.get("description") or workflow.get("summary"),
                    operations=operations,
                    extras=service_extras,
                )
            )
        return services

    @staticmethod
    def _step_operation(
        workflow_id: str, step: Dict[str, Any], index: int
    ) -> Operation:
        step_id = step.get("stepId")
        if not isinstance(step_id, str) or not step_id.strip():
            step_id = f"step{index}"
        op_key = Keys.workflow_step(workflow_id, step_id)

        extras: Dict[str, Any] = {"stepIndex": index, "stepId": step_id}
        if step.get("operationId"):
            extras["operationId"] = step["operationId"]
        if step.get("operationRef"):
            extras["operationRef"] = step["operationRef"]
        if step.get("dependsOn"):
            extras["dependsOn"] = step["dependsOn"]
        if step.get("successCriteria") is not None:
            extras["successCriteria"] = step["successCriteria"]
        if step.get("parameters"):
            extras["parameters"] = step["parameters"]
        if step.get("requestBody"):
            extras["requestBody"] = step["requestBody"]
        if step.get("outputs"):
            extras["outputs"] = step["outputs"]

        referenced = step.get("operationId") or step.get("operationRef") or step_id
        return Operation(
            key=op_key,
            name=step_id,
            kind=OperationKind.ONE_WAY,
            description=step.get("description") or step.get("summary"),
            extras=extras,
            tags=[workflow_id],
        )
