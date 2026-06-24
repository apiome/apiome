"""Canonical ``objectified-rest`` URL paths (relative to ``base_url``)."""

from __future__ import annotations

from uuid import UUID

V1 = "/v1"


def health() -> str:
    return "/health"


def tenants_me() -> str:
    return f"{V1}/tenants/me"


def tenant(tenant_slug: str) -> str:
    return f"{V1}/tenants/{tenant_slug}"


def tenant_imports(tenant_slug: str) -> str:
    return f"{V1}/tenants/{tenant_slug}/imports"


def tenant_import(tenant_slug: str, job_id: str) -> str:
    return f"{V1}/tenants/{tenant_slug}/imports/{job_id}"


def tenant_imports_upload(tenant_slug: str) -> str:
    return f"{V1}/tenants/{tenant_slug}/imports/upload"


def tenant_repositories(tenant_slug: str) -> str:
    return f"{V1}/tenants/{tenant_slug}/repositories"


def tenant_repository(tenant_slug: str, repository_id: str | UUID) -> str:
    return f"{V1}/tenants/{tenant_slug}/repositories/{repository_id}"


def tenant_repository_files(tenant_slug: str, repository_id: str | UUID) -> str:
    return f"{tenant_repository(tenant_slug, repository_id)}/files"


def tenant_repository_file_content(
    tenant_slug: str,
    repository_id: str | UUID,
    file_id: str | UUID,
) -> str:
    return f"{tenant_repository_files(tenant_slug, repository_id)}/{file_id}/content"


def projects(tenant_slug: str) -> str:
    return f"{V1}/projects/{tenant_slug}"


def project(tenant_slug: str, project_id: str | UUID) -> str:
    return f"{V1}/projects/{tenant_slug}/{project_id}"


def project_by_slug(tenant_slug: str, project_slug: str) -> str:
    return f"{V1}/projects/{tenant_slug}/by-slug/{project_slug}"


def versions(tenant_slug: str, project_id: str | UUID) -> str:
    return f"{V1}/versions/{tenant_slug}/{project_id}"


def version_record(
    tenant_slug: str,
    project_id: str | UUID,
    version_record_id: str | UUID,
) -> str:
    return f"{V1}/versions/{tenant_slug}/{project_id}/{version_record_id}"


def version_by_semver(
    tenant_slug: str,
    project_id: str | UUID,
    version_semver: str,
) -> str:
    return f"{V1}/versions/{tenant_slug}/{project_id}/by-version/{version_semver}"


def version_lint(
    tenant_slug: str,
    project_id: str | UUID,
    version_record_id: str | UUID,
) -> str:
    """Quality-scoring / lint report for a version (GET .../lint)."""
    return f"{version_record(tenant_slug, project_id, version_record_id)}/lint"


def version_publish(
    tenant_slug: str,
    project_id: str | UUID,
    version_record_id: str | UUID,
) -> str:
    return f"{version_record(tenant_slug, project_id, version_record_id)}/publish"


def version_unpublish(
    tenant_slug: str,
    project_id: str | UUID,
    version_record_id: str | UUID,
) -> str:
    return f"{version_record(tenant_slug, project_id, version_record_id)}/unpublish"


def classes(tenant_slug: str) -> str:
    return f"{V1}/classes/{tenant_slug}"


def class_record(tenant_slug: str, class_id: str | UUID) -> str:
    return f"{V1}/classes/{tenant_slug}/{class_id}"


def primitives(tenant_slug: str) -> str:
    return f"{V1}/primitives/{tenant_slug}"


def primitive(tenant_slug: str, primitive_id: str | UUID) -> str:
    return f"{V1}/primitives/{tenant_slug}/{primitive_id}"


def primitives_import(tenant_slug: str) -> str:
    return f"{V1}/primitives/{tenant_slug}/import"


def properties(tenant_slug: str, project_id: str | UUID) -> str:
    return f"{V1}/properties/{tenant_slug}/{project_id}"


def property_record(
    tenant_slug: str,
    project_id: str | UUID,
    property_id: str | UUID,
) -> str:
    return f"{V1}/properties/{tenant_slug}/{project_id}/{property_id}"


def paths(tenant_slug: str, version_record_id: str | UUID) -> str:
    return f"{V1}/paths/{tenant_slug}/{version_record_id}"


def path_record(
    tenant_slug: str,
    version_record_id: str | UUID,
    path_id: str | UUID,
) -> str:
    return f"{paths(tenant_slug, version_record_id)}/{path_id}"


def path_operations(
    tenant_slug: str,
    version_record_id: str | UUID,
    path_id: str | UUID,
) -> str:
    return f"{path_record(tenant_slug, version_record_id, path_id)}/operations"


def path_operation(
    tenant_slug: str,
    version_record_id: str | UUID,
    path_id: str | UUID,
    operation_id: str | UUID,
) -> str:
    return f"{path_operations(tenant_slug, version_record_id, path_id)}/{operation_id}"


def path_full(
    tenant_slug: str,
    version_record_id: str | UUID,
    path_id: str | UUID,
) -> str:
    return f"{path_record(tenant_slug, version_record_id, path_id)}/full"


def browse_tenants() -> str:
    return f"{V1}/browse/tenants"


def browse_projects(tenant_slug: str) -> str:
    return f"{V1}/browse/tenants/{tenant_slug}/projects"


def browse_versions(tenant_slug: str, project_slug: str) -> str:
    return f"{V1}/browse/tenants/{tenant_slug}/projects/{project_slug}/versions"


def schema_export(tenant_slug: str, project_slug: str, version_slug: str) -> str:
    return f"{V1}/schema/{tenant_slug}/{project_slug}/{version_slug}"


def swagger_export(tenant_slug: str, project_slug: str, version_slug: str) -> str:
    return f"{V1}/swagger/{tenant_slug}/{project_slug}/{version_slug}"


def arazzo_export(tenant_slug: str, project_slug: str, version_slug: str) -> str:
    return f"{V1}/arazzo/{tenant_slug}/{project_slug}/{version_slug}"


def json_export(tenant_slug: str, project_slug: str, version_slug: str) -> str:
    return f"{V1}/json/{tenant_slug}/{project_slug}/{version_slug}"
