"""Who administers a tenant — the recipients of a notification about the tenant itself.

Used by notifications that concern the workspace as a whole rather than one project: a sign-in
blocked by the seat limit (EID-1.3, #5013) and a tenant bucket that stopped answering (COA-5.15,
#7092).
"""

from __future__ import annotations

from typing import Any, List

__all__ = ["tenant_admin_ids"]


def tenant_admin_ids(cursor: Any, tenant_id: str) -> List[str]:
    """The tenant's active owners and tenant administrators.

    Args:
        cursor: An open cursor (the caller's transaction).
        tenant_id: The tenant.

    Returns:
        Their user ids, in a stable order. A deleted or inactive member is never included.
    """
    cursor.execute(
        """
        SELECT DISTINCT tu.user_id::text AS user_id
        FROM apiome.tenant_users tu
        JOIN apiome.users u ON u.id = tu.user_id AND u.deleted_at IS NULL
        WHERE tu.tenant_id = %s::uuid
          AND tu.status = 'active'
          AND (
              EXISTS (
                  SELECT 1 FROM apiome.tenant_user_roles tur
                  JOIN apiome.roles r ON r.id = tur.role_id
                  WHERE tur.tenant_id = tu.tenant_id AND tur.user_id = tu.user_id AND r.slug = 'owner'
              )
              OR EXISTS (
                  SELECT 1 FROM apiome.tenant_administrators ta
                  WHERE ta.tenant_id = tu.tenant_id AND ta.user_id = tu.user_id
              )
          )
        ORDER BY 1
        """,
        (tenant_id,),
    )
    return [str(row["user_id"]) for row in cursor.fetchall()]
