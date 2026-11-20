"""
Arazzo Specification Generator

Generates Arazzo 1.0.x or 1.1.x workflow specifications from class definitions.
Arazzo is a specification for describing sequences of API calls and their dependencies.

The written version follows the same rules as the Arazzo emitter (``arazzo_emitter.py``):
an explicit ``arazzo_version`` wins; otherwise ``1.1.0`` when a source description is
AsyncAPI (only 1.1 can express one) and ``1.0.1`` for an all-OpenAPI document, so a
document that needs nothing from 1.1 is never pushed onto a newer version.
"""

import re
from typing import Any, Dict, List, Optional

from .arazzo_spec import (
    SOURCE_TYPE_ASYNCAPI,
    ArazzoVersionError,
    default_arazzo_version,
    supports_async_sources,
    validate_arazzo_version,
)

#: A full ``major.minor.patch[-pre]`` version, the form the Arazzo schemas require of ``arazzo``.
_FULL_VERSION = re.compile(r"^\d+\.\d+\.\d+(-.+)?$")


def resolve_generator_arazzo_version(
    arazzo_version: Optional[str],
    source_descriptions: List[Dict[str, Any]],
) -> str:
    """
    Choose the ``arazzo`` version a generated document declares.

    Args:
        arazzo_version: The caller's requested version (``"1.0.1"``, ``"1.1.0"`` …), or
            ``None`` / blank for the default.
        source_descriptions: The document's ``sourceDescriptions`` entries.

    Returns:
        The requested version when given; otherwise ``1.1.0`` when any source description
        is ``type: asyncapi`` and ``1.0.1`` when none is.

    Raises:
        ArazzoVersionError: When the requested version is not a full ``major.minor.patch``
            in a supported line (1.0.x, 1.1.x), or is a 1.0.x version for a document with
            an AsyncAPI source description, which 1.0 cannot express.
    """
    has_async_sources = any(
        isinstance(source, dict) and source.get("type") == SOURCE_TYPE_ASYNCAPI
        for source in source_descriptions
    )
    if arazzo_version is None or not arazzo_version.strip():
        return default_arazzo_version(has_async_sources=has_async_sources)

    requested = arazzo_version.strip()
    if not _FULL_VERSION.match(requested):
        raise ArazzoVersionError(
            f"`{requested}` is not a full Arazzo version "
            "(expected `major.minor.patch`, for example `1.1.0`)."
        )
    line = validate_arazzo_version(requested)
    if has_async_sources and not supports_async_sources(line):
        raise ArazzoVersionError(
            f"Arazzo {requested} cannot describe an AsyncAPI source; use 1.1.0 or later."
        )
    return requested


def generate_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_id: str,
    classes: List[Dict[str, Any]],
    project_description: Optional[str] = None,
    *,
    arazzo_version: Optional[str] = None,
    source_descriptions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Generate a complete Arazzo specification from class definitions.

    Args:
        tenant_slug: The tenant identifier
        project_slug: The project identifier
        version_id: The version identifier
        classes: List of class data dictionaries
        project_description: Optional project description
        arazzo_version: Arazzo version to write (``1.0.1``, ``1.1.0`` …); ``None`` picks
            the default (see :func:`resolve_generator_arazzo_version`)
        source_descriptions: ``sourceDescriptions`` entries to declare instead of the
            default single OpenAPI source for the version; an ``asyncapi`` entry makes
            ``1.1.0`` the default

    Returns:
        Arazzo document as a dictionary

    Raises:
        ArazzoVersionError: When ``arazzo_version`` is unsupported or cannot describe
            the source descriptions
    """
    if source_descriptions is None:
        source_descriptions = [
            {
                "name": "openapi-source",
                "type": "openapi",
                "url": f"/v1/schema/{tenant_slug}/{project_slug}/{version_id}",
                "description": "OpenAPI specification containing schema definitions"
            }
        ]
    resolved_version = resolve_generator_arazzo_version(arazzo_version, source_descriptions)

    # Generate workflows based on CRUD operations for each class
    workflows = []

    for class_data in classes:
        class_name = class_data['name']
        class_description = class_data.get('description') or f"Operations for {class_name}"

        # Build steps for CRUD operations
        steps = [
            {
                "stepId": f"create{class_name}",
                "description": f"Create a new {class_name}",
                "operationId": f"create{class_name}",
                "parameters": [],
                "requestBody": {
                    "contentType": "application/json",
                    "payload": {
                        "$ref": f"#/components/schemas/{class_name}"
                    }
                },
                "successCriteria": [
                    {
                        "condition": "$statusCode == 201",
                        "type": "simple"
                    }
                ],
                "outputs": {
                    f"{class_name.lower()}Id": "$response.body.id"
                }
            },
            {
                "stepId": f"get{class_name}",
                "description": f"Retrieve a {class_name} by ID",
                "operationId": f"get{class_name}ById",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "value": f"$steps.create{class_name}.outputs.{class_name.lower()}Id"
                    }
                ],
                "successCriteria": [
                    {
                        "condition": "$statusCode == 200",
                        "type": "simple"
                    }
                ],
                "dependsOn": [f"create{class_name}"]
            },
            {
                "stepId": f"update{class_name}",
                "description": f"Update an existing {class_name}",
                "operationId": f"update{class_name}",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "value": f"$steps.create{class_name}.outputs.{class_name.lower()}Id"
                    }
                ],
                "requestBody": {
                    "contentType": "application/json",
                    "payload": {
                        "$ref": f"#/components/schemas/{class_name}"
                    }
                },
                "successCriteria": [
                    {
                        "condition": "$statusCode == 200",
                        "type": "simple"
                    }
                ],
                "dependsOn": [f"create{class_name}"]
            },
            {
                "stepId": f"delete{class_name}",
                "description": f"Delete a {class_name}",
                "operationId": f"delete{class_name}",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "value": f"$steps.create{class_name}.outputs.{class_name.lower()}Id"
                    }
                ],
                "successCriteria": [
                    {
                        "condition": "$statusCode == 204",
                        "type": "simple"
                    }
                ],
                "dependsOn": [f"update{class_name}"]
            }
        ]

        workflows.append({
            "workflowId": f"{class_name.lower()}Workflow",
            "summary": f"{class_name} CRUD Workflow",
            "description": class_description,
            "steps": steps
        })

    # Use project description if provided and not empty, otherwise use default
    description = project_description if project_description and project_description.strip() else \
                  f"Generated Arazzo {resolved_version} workflow specification from Apiome Studio"

    # Build the complete Arazzo document
    arazzo_doc = {
        "arazzo": resolved_version,
        "info": {
            "title": f"{project_slug} Workflows",
            "version": version_id,
            "description": description
        },
        "sourceDescriptions": source_descriptions,
        "workflows": workflows
    }

    return arazzo_doc


def generate_class_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_id: str,
    class_data: Dict[str, Any],
    *,
    arazzo_version: Optional[str] = None,
    source_descriptions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Generate an Arazzo specification for a single class.

    Args:
        tenant_slug: The tenant identifier
        project_slug: The project identifier
        version_id: The version identifier
        class_data: Class data dictionary
        arazzo_version: Arazzo version to write (``1.0.1``, ``1.1.0`` …); ``None`` picks
            the default (see :func:`resolve_generator_arazzo_version`)
        source_descriptions: ``sourceDescriptions`` entries to declare instead of the
            default single OpenAPI source for the class; an ``asyncapi`` entry makes
            ``1.1.0`` the default

    Returns:
        Arazzo document as a dictionary

    Raises:
        ArazzoVersionError: When ``arazzo_version`` is unsupported or cannot describe
            the source descriptions
    """
    class_name = class_data['name']
    class_description = class_data.get('description') or f"Operations for {class_name}"

    if source_descriptions is None:
        source_descriptions = [
            {
                "name": "openapi-source",
                "type": "openapi",
                "url": f"/v1/schema/{tenant_slug}/{project_slug}/{version_id}/{class_name}",
                "description": f"OpenAPI specification for {class_name}"
            }
        ]
    resolved_version = resolve_generator_arazzo_version(arazzo_version, source_descriptions)

    # Build steps for CRUD operations
    steps = [
        {
            "stepId": f"create{class_name}",
            "description": f"Create a new {class_name}",
            "operationId": f"create{class_name}",
            "parameters": [],
            "requestBody": {
                "contentType": "application/json",
                "payload": {
                    "$ref": f"#/components/schemas/{class_name}"
                }
            },
            "successCriteria": [
                {
                    "condition": "$statusCode == 201",
                    "type": "simple"
                }
            ],
            "outputs": {
                f"{class_name.lower()}Id": "$response.body.id"
            }
        },
        {
            "stepId": f"get{class_name}",
            "description": f"Retrieve a {class_name} by ID",
            "operationId": f"get{class_name}ById",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "value": f"$steps.create{class_name}.outputs.{class_name.lower()}Id"
                }
            ],
            "successCriteria": [
                {
                    "condition": "$statusCode == 200",
                    "type": "simple"
                }
            ],
            "dependsOn": [f"create{class_name}"]
        },
        {
            "stepId": f"update{class_name}",
            "description": f"Update an existing {class_name}",
            "operationId": f"update{class_name}",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "value": f"$steps.create{class_name}.outputs.{class_name.lower()}Id"
                }
            ],
            "requestBody": {
                "contentType": "application/json",
                "payload": {
                    "$ref": f"#/components/schemas/{class_name}"
                }
            },
            "successCriteria": [
                {
                    "condition": "$statusCode == 200",
                    "type": "simple"
                }
            ],
            "dependsOn": [f"create{class_name}"]
        },
        {
            "stepId": f"delete{class_name}",
            "description": f"Delete a {class_name}",
            "operationId": f"delete{class_name}",
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "value": f"$steps.create{class_name}.outputs.{class_name.lower()}Id"
                }
            ],
            "successCriteria": [
                {
                    "condition": "$statusCode == 204",
                    "type": "simple"
                }
            ],
            "dependsOn": [f"update{class_name}"]
        }
    ]

    workflow = {
        "workflowId": f"{class_name.lower()}Workflow",
        "summary": f"{class_name} CRUD Workflow",
        "description": class_description,
        "steps": steps
    }

    # Build the Arazzo document for single class
    arazzo_doc = {
        "arazzo": resolved_version,
        "info": {
            "title": f"{class_name} Workflow",
            "version": version_id,
            "description": f"Arazzo workflow specification for {tenant_slug}/{project_slug}/{version_id}/{class_name}"
        },
        "sourceDescriptions": source_descriptions,
        "workflows": [workflow]
    }

    return arazzo_doc

