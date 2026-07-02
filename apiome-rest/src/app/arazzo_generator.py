"""
Arazzo Specification Generator

Generates Arazzo v1.0.1 workflow specifications from class definitions.
Arazzo is a specification for describing sequences of API calls and their dependencies.
"""

from typing import Dict, Any, List, Optional


def generate_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_id: str,
    classes: List[Dict[str, Any]],
    project_description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate a complete Arazzo v1.0.1 specification from class definitions.

    Args:
        tenant_slug: The tenant identifier
        project_slug: The project identifier
        version_id: The version identifier
        classes: List of class data dictionaries
        project_description: Optional project description

    Returns:
        Arazzo document as a dictionary
    """
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
                  "Generated Arazzo 1.0.1 workflow specification from Apiome Studio"

    # Build the complete Arazzo document
    arazzo_doc = {
        "arazzo": "1.0.1",
        "info": {
            "title": f"{project_slug} Workflows",
            "version": version_id,
            "description": description
        },
        "sourceDescriptions": [
            {
                "name": "openapi-source",
                "type": "openapi",
                "url": f"/v1/schema/{tenant_slug}/{project_slug}/{version_id}",
                "description": "OpenAPI specification containing schema definitions"
            }
        ],
        "workflows": workflows
    }

    return arazzo_doc


def generate_class_arazzo_spec(
    tenant_slug: str,
    project_slug: str,
    version_id: str,
    class_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate an Arazzo specification for a single class.

    Args:
        tenant_slug: The tenant identifier
        project_slug: The project identifier
        version_id: The version identifier
        class_data: Class data dictionary

    Returns:
        Arazzo document as a dictionary
    """
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

    workflow = {
        "workflowId": f"{class_name.lower()}Workflow",
        "summary": f"{class_name} CRUD Workflow",
        "description": class_description,
        "steps": steps
    }

    # Build the Arazzo document for single class
    arazzo_doc = {
        "arazzo": "1.0.1",
        "info": {
            "title": f"{class_name} Workflow",
            "version": version_id,
            "description": f"Arazzo workflow specification for {tenant_slug}/{project_slug}/{version_id}/{class_name}"
        },
        "sourceDescriptions": [
            {
                "name": "openapi-source",
                "type": "openapi",
                "url": f"/v1/schema/{tenant_slug}/{project_slug}/{version_id}/{class_name}",
                "description": f"OpenAPI specification for {class_name}"
            }
        ],
        "workflows": [workflow]
    }

    return arazzo_doc

