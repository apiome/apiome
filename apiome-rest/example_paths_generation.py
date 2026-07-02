#!/usr/bin/env python3
"""
Example demonstrating paths generation without database connection.
This simulates what the output would look like with actual paths.
"""

import sys
import os
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from app.paths_generator import generate_paths_for_openapi


def example_paths_generation():
    """Example showing how paths are generated from database records."""
    print("=" * 70)
    print("Example: OpenAPI Paths Generation from Database Records")
    print("=" * 70)

    # Simulate path data that would come from the database
    paths_data = [
        {
            'id': 'path-1',
            'pathname': '/users',
            'summary': 'User management',
            'description': 'Endpoints for managing users',
            'operations': [
                {
                    'id': 'op-1',
                    'operation': 'GET',
                    'description': {
                        'id': 'desc-1',
                        'summary': 'List all users',
                        'description': 'Returns a list of all users in the system',
                        'operationId': 'listUsers',
                        'tags': ['users'],
                        'deprecated': False,
                    },
                    'parameters': [
                        {
                            'id': 'param-1',
                            'name': 'limit',
                            'in_location': 'query',
                            'description': 'Maximum number of users to return',
                            'data': {
                                'type': 'integer',
                                'default': 10,
                                'minimum': 1,
                                'maximum': 100
                            }
                        }
                    ],
                    'requestBody': None,
                    'responses': [
                        {
                            'id': 'resp-1',
                            'status_code': '200',
                            'description': 'Successful response',
                            'content_types': [
                                {
                                    'id': 'ct-1',
                                    'media_type': 'application/json',
                                    'class_id': 'class-1',
                                    'class_name': 'User',
                                    'inline_schema': None,
                                    'examples': None
                                }
                            ]
                        }
                    ]
                },
                {
                    'id': 'op-2',
                    'operation': 'POST',
                    'description': {
                        'id': 'desc-2',
                        'summary': 'Create a new user',
                        'description': 'Creates a new user in the system',
                        'operationId': 'createUser',
                        'tags': ['users'],
                        'deprecated': False,
                    },
                    'parameters': [],
                    'requestBody': {
                        'id': 'rb-1',
                        'name': 'CreateUserRequest',
                        'description': 'User data to create',
                        'required': True,
                        'content_types': [
                            {
                                'id': 'ct-2',
                                'media_type': 'application/json',
                                'class_id': 'class-1',
                                'class_name': 'User',
                                'inline_schema': None,
                                'encoding': None,
                                'examples': None
                            }
                        ]
                    },
                    'responses': [
                        {
                            'id': 'resp-2',
                            'status_code': '201',
                            'description': 'User created successfully',
                            'content_types': [
                                {
                                    'id': 'ct-3',
                                    'media_type': 'application/json',
                                    'class_id': 'class-1',
                                    'class_name': 'User',
                                    'inline_schema': None,
                                    'examples': None
                                }
                            ]
                        },
                        {
                            'id': 'resp-3',
                            'status_code': '400',
                            'description': 'Invalid request',
                            'content_types': []
                        }
                    ]
                }
            ]
        },
        {
            'id': 'path-2',
            'pathname': '/users/{userId}',
            'summary': 'Individual user operations',
            'description': 'Endpoints for managing a specific user',
            'operations': [
                {
                    'id': 'op-3',
                    'operation': 'GET',
                    'description': {
                        'id': 'desc-3',
                        'summary': 'Get user by ID',
                        'description': 'Returns a single user by their ID',
                        'operationId': 'getUserById',
                        'tags': ['users'],
                        'deprecated': False,
                    },
                    'parameters': [
                        {
                            'id': 'param-2',
                            'name': 'userId',
                            'in_location': 'path',
                            'description': 'ID of the user to retrieve',
                            'data': {
                                'type': 'string',
                                'format': 'uuid'
                            }
                        }
                    ],
                    'requestBody': None,
                    'responses': [
                        {
                            'id': 'resp-4',
                            'status_code': '200',
                            'description': 'User found',
                            'content_types': [
                                {
                                    'id': 'ct-4',
                                    'media_type': 'application/json',
                                    'class_id': 'class-1',
                                    'class_name': 'User',
                                    'inline_schema': None,
                                    'examples': None
                                }
                            ]
                        },
                        {
                            'id': 'resp-5',
                            'status_code': '404',
                            'description': 'User not found',
                            'content_types': []
                        }
                    ]
                }
            ]
        }
    ]

    # Generate OpenAPI paths
    openapi_paths = generate_paths_for_openapi(paths_data)

    print("\nGenerated OpenAPI Paths:")
    print(json.dumps(openapi_paths, indent=2))

    print("\n" + "=" * 70)
    print("Summary:")
    print(f"  Total paths: {len(openapi_paths)}")
    print(f"  Paths: {list(openapi_paths.keys())}")

    # Count total operations
    total_ops = sum(
        len([k for k in path.keys() if k in ['get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace']])
        for path in openapi_paths.values()
    )
    print(f"  Total operations: {total_ops}")
    print("=" * 70)


if __name__ == "__main__":
    example_paths_generation()
